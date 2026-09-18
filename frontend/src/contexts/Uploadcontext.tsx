import { ReactNode, createContext, startTransition, useContext, useEffect, useMemo, useRef, useState } from "react";
import { adminService, UploadSessionListItem } from "../services/admin";

// Generates a short, DB-safe unique id for an upload attempt. Deliberately
// does NOT embed the filename (unlike the old `${file.name}-${file.size}-...`
// scheme) - upload_session.upload_id is a VARCHAR(100) column, and a long
// filename alone can exceed that, which previously crashed the upload with
// a raw 500 (MySQL: "Data too long for column 'upload_id'") instead of
// ever reaching a validation error. The filename is already sent/stored
// separately (item.filename / the `filename` field) so it doesn't need to
// live inside the id at all.
function generateUploadId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

// Browser-memory management: once an upload reaches a terminal state that
// no longer needs the File's bytes (done / cancelled), drop the File
// reference from the item. Keeping it around until the list auto-clears
// would pin potentially hundreds of File handles (each a reference to a
// real file on disk) in React state for no benefit. Files whose OTHER
// reference state is fatal (error - may be retried; or errored while
// finalizing with a driveFileId - retried via the backend confirm only)
// deliberately keep their File/fields so a retry still works.
function withReleasedFile<T extends UploadItem>(item: T): T {
  return { ...item, file: null };
}

export interface UploadItem {
  id: string;
  file: File | null;
  filename: string;
  size?: number;
  status: "queued" | "uploading" | "finalizing" | "done" | "error" | "cancelled";
  progress: number;
  error?: string;
  cancel?: () => void;
  restored?: boolean;
  // The album this file is headed to - captured on the item at add time
  // (not read from page state at upload time), so this keeps working
  // correctly even if the person switches the album picker on the Uploads
  // page - or navigates away from it entirely - while a batch is still in
  // flight.
  albumId: number;
  // Set once the browser's direct PUT to Drive has finished (Section:
  // architecture change) - lets retryItem() below skip straight to
  // re-confirming with the backend instead of re-uploading the whole
  // file again, if only that last confirmation step failed.
  driveFileId?: string;
  reportedSize?: number;
  reportedMimeType?: string;
}

export const STATUS_LABEL: Record<UploadItem["status"], string> = {
  queued: "Queued",
  uploading: "Uploading",
  finalizing: "Finalizing",
  done: "Done",
  error: "Failed",
  cancelled: "Cancelled",
};

// Human-readable file size, e.g. "24.3 MB". Used for both freshly-picked
// files (which carry the real File object) and sessions restored after a
// page refresh (which only have the server's total_bytes).
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exponent;
  const precision = exponent === 0 ? 0 : value < 10 ? 1 : 0;
  return `${value.toFixed(precision)} ${units[exponent]}`;
}

// Caps how many files this app will have in flight (sending bytes directly
// to Drive, or awaiting the backend's post-upload confirmation) at once.
// Without this, selecting a big batch (a whole shoot: 100+ photos and
// videos) fired every file's direct-to-Drive PUT simultaneously - which
// the browser's own per-origin connection limit would partly queue anyway,
// but a large burst is still harder to reason about and retry than a
// batch that quietly works its way through a small number of slots.
const MAX_CONCURRENT_UPLOADS = 4;

// Caps how many File objects can enter the queue in a SINGLE selection.
// This is a browser-memory guard, not a download policy: every picked file
// is kept as a File reference inside UploadItem (so it can be PUT to Drive
// and retried), and thousands of them held in React state (past thumbnail
// previews, revoke-on-close of blob URLs, etc.) is real pressure. Retry/
// add-files still lets a huge shoot through in chunks - a single mount of
// more than this is almost always an accidental select-all.
const MAX_FILES_PER_SELECTION = 200;

export interface UploadSummary {
  total: number;
  active: number;
  completed: number;
  failed: number;
  cancelled: number;
  overallPercent: number;
}

interface UploadContextValue {
  items: UploadItem[];
  summary: UploadSummary;
  paused: boolean;
  setPaused: (value: boolean | ((prev: boolean) => boolean)) => void;
  toast: { text: string; kind: "success" | "warn" } | null;
  dismissToast: () => void;
  addFiles: (files: File[], albumId: number) => void;
  cancelItem: (item: UploadItem) => void;
  retryItem: (item: UploadItem) => void;
  retryAllFailed: () => void;
  clearList: () => void;
}

const UploadContext = createContext<UploadContextValue | null>(null);

// Mounted ONCE at the app root (see App.tsx), above the router - so
// navigating between admin pages (Uploads -> Clients -> back) never
// unmounts this. The in-flight direct-to-Drive PUTs and their promise
// chains were never actually tied to the Uploads page's lifecycle (a
// browser XHR keeps running regardless of what React unmounts), but
// before this the page had no way to keep SHOWING their progress after a
// navigation, and losing track of them here meant a subsequent visit to
// Uploads treated them as abandoned. This provider is what fixes that.
//
// This only survives IN-APP (client-side route) navigation, for as long
// as the browser tab itself stays open - a full page reload, tab close,
// or browser crash still ends the JS context entirely, taking any
// in-flight direct-to-Drive transfer with it. There is no way around that
// with this architecture without going back to relaying uploads through
// the VPS, which is the exact thing this architecture was built to avoid.
export function UploadProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [paused, setPaused] = useState(false);
  const [toast, setToast] = useState<{ text: string; kind: "success" | "warn" } | null>(null);
  const toastShownRef = useRef(false);

  // Refresh-recovery (Section 4): only restore ACTIVE uploads (queued /
  // uploading). Runs ONCE for the life of the app (this provider never
  // unmounts on navigation) rather than on every visit to the Uploads
  // page, which is both more correct (no risk of re-adding/re-flagging
  // items already handled this session) and cheaper.
  useEffect(() => {
    let cancelled = false;
    adminService
      .listUploadSessions(100)
      .then((sessions: UploadSessionListItem[]) => {
        if (cancelled) return;
        const active = sessions.filter((s) => s.status === "queued" || s.status === "uploading");
        // Unlike the old byte-relaying flow, a restored "active" session
        // can never actually resume: the browser talks to Drive directly
        // now, and the File object that PUT was reading from only exists
        // in a JS context that's gone once its tab is closed/refreshed -
        // there is nothing left on this server that could still be
        // transferring it. Show these as needing a fresh upload rather
        // than polling a session that will just sit there until the
        // server's own staleness sweep eventually times it out.
        const restored: UploadItem[] = active.map((s) => ({
          id: s.upload_id,
          file: null,
          filename: s.filename,
          size: s.total_bytes,
          progress: s.percentage,
          status: "error",
          error:
            "This upload was interrupted (browser closed or refreshed). Please re-select and upload this file again.",
          restored: true,
          albumId: 0,
        }));
        setItems((prev) => {
          const ids = new Set(prev.map((i) => i.id));
          return [...prev, ...restored.filter((r) => !ids.has(r.id))];
        });
      })
      .catch(() => {
        // Non-fatal: the app still fully works for new uploads; we just
        // don't restore active sessions if the backend isn't reachable.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const summary = useMemo<UploadSummary>(() => {
    const total = items.length;
    const active = items.filter((i) => i.status === "uploading" || i.status === "finalizing").length;
    const completed = items.filter((i) => i.status === "done").length;
    const failed = items.filter((i) => i.status === "error").length;
    const cancelled = items.filter((i) => i.status === "cancelled").length;
    const overallPercent =
      total === 0 ? 0 : Math.round(items.reduce((sum, i) => sum + (i.status === "done" ? 100 : i.progress), 0) / total);
    return { total, active, completed, failed, cancelled, overallPercent };
  }, [items]);

  // Best-effort progress reporting to the backend (Section 8) while
  // uploadToDrive's own onProgress already drives the visible bar - this
  // just lets OTHER views (a second tab, or the server's own bookkeeping)
  // see roughly where things stand. Throttled to ~1/second; a dropped
  // ping is never fatal, so failures are swallowed here rather than
  // surfaced.
  function makeThrottledProgressReporter(uploadId: string) {
    let lastSent = 0;
    let inFlight = false;
    return (bytesUploaded: number) => {
      const now = Date.now();
      if (inFlight || now - lastSent < 1000) return;
      lastSent = now;
      inFlight = true;
      adminService
        .reportUploadProgress(uploadId, bytesUploaded)
        .catch(() => {
          /* cosmetic only - never blocks or fails the upload */
        })
        .finally(() => {
          inFlight = false;
        });
    };
  }

  // Runs the direct-to-Drive PUT and the backend's finalize call for an
  // item that already has a resumable upload_url in hand - shared by
  // startUpload (fresh uploads) and retryItem's "just retry the
  // confirmation" path (an item that already has a cached driveFileId).
  async function runDirectUpload(item: UploadItem, uploadUrl: string) {
    const uploadId = item.id;
    if (!item.file) return;

    const reportProgress = makeThrottledProgressReporter(uploadId);

    let lastReportedPercent = -1;
    const { promise, cancel } = adminService.uploadToDrive(uploadUrl, item.file, (percent) => {
      if (percent !== lastReportedPercent) {
        lastReportedPercent = percent;
        // startTransition: the XHR progress event can fire dozens of times
        // per second, and each setItems() here is an URGENT (non-transition)
        // update by default. App.tsx uses BrowserRouter with
        // v7_startTransition, so navigating to Clients/Dashboard/back to
        // Uploads is a LOW-priority render that these rapid progress updates
        // would otherwise keep starving - React keeps re-rendering upload
        // progress and never gets around to mounting the newly-navigated
        // page, which is why its useEffect data fetches never ran (and the
        // Uploads page looked empty on the way back). Marking the progress
        // update as a transition lets React drop/interrupt it in favour of
        // completing the route change.
        startTransition(() => {
          setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, progress: percent } : i)));
        });
      }
      if (item.file) reportProgress(Math.round((percent / 100) * item.file.size));
    });
    setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, cancel } : i)));

    let driveResult: { driveFileId: string; size: number; mimeType: string };
    try {
      driveResult = await promise;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload to Google Drive failed.";
      const wasCancelled = message === "Upload cancelled.";
      if (!wasCancelled) {
        // This server never saw the failure (the browser talked to Drive
        // directly) - tell it explicitly so a retry with the same
        // upload_id doesn't get rejected as "already in progress"
        // (Section 4/9's idempotency check would otherwise 409 forever,
        // since nothing here ever flips this session out of "uploading").
        adminService.abandonUploadSession(uploadId).catch(() => {});
      }
      setItems((prev) =>
        prev.map((i) =>
          i.id === item.id
            ? wasCancelled
              ? withReleasedFile({ ...i, status: "cancelled" })
              : { ...i, status: "error", error: message }
            : i
        )
      );
      return;
    }

    // Cache what Drive told us BEFORE calling completeUpload - if that
    // next call fails (network drop, server restart), retryItem() can
    // skip straight back here instead of re-uploading the whole file.
    setItems((prev) =>
      prev.map((i) =>
        i.id === item.id
          ? {
              ...i,
              status: "finalizing",
              progress: 100,
              driveFileId: driveResult.driveFileId,
              reportedSize: driveResult.size,
              reportedMimeType: driveResult.mimeType,
            }
          : i
      )
    );

    try {
      await adminService.completeUpload(uploadId, driveResult.driveFileId, driveResult.size, driveResult.mimeType);
      setItems((prev) =>
        prev.map((i) => (i.id === item.id ? withReleasedFile({ ...i, status: "done", progress: 100 }) : i))
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not confirm the upload.";
      // driveFileId (set above) stays on the item - the file is already
      // safely in Drive, so a retry from here should call completeUpload
      // again, NOT re-upload the bytes (see retryItem below).
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, status: "error", error: message } : i)));
    }
  }

  async function startUpload(item: UploadItem) {
    if (!item.file) return;
    // item.id is reused verbatim as the upload_id on every retry of THIS
    // item (see retryItem/retryAllFailed below), so the backend can tell
    // "the browser retried this exact upload" apart from "this is a new
    // upload" (Section 4) - a real retry never produces a duplicate file.
    const uploadId = item.id;

    // Mark the item "uploading" with a pre-flight cancel synchronously so
    // the concurrency scheduler counts this slot as taken while we await
    // session reservation below - otherwise the item would still be
    // "queued" (no `cancel`) during the async window and a re-run of the
    // scheduler would re-pick it (or oversubscribe the slot).
    let cancelledEarly = false;
    const preflightCancel = () => {
      cancelledEarly = true;
      setItems((prev) =>
        prev.map((i) => (i.id === item.id ? withReleasedFile({ ...i, status: "cancelled", cancel: undefined }) : i))
      );
    };
    setItems((prev) =>
      prev.map((i) => (i.id === item.id ? { ...i, status: "uploading", cancel: preflightCancel } : i))
    );

    try {
      // 1. Ask the backend to open a Google Drive resumable-upload session
      // - this server never receives the file's bytes at all. The
      // returned upload_url is what the BROWSER PUTs directly to Google
      // from here on (step 2, inside runDirectUpload).
      const session = await adminService.createUploadSession(item.albumId, uploadId, item.filename, item.file.size);
      if (cancelledEarly) return; // user cancelled during reservation

      if (!session.upload_url) {
        // Idempotent replay: this upload_id already finished earlier -
        // nothing to send.
        setItems((prev) =>
          prev.map((i) => (i.id === item.id ? withReleasedFile({ ...i, status: "done", progress: 100 }) : i))
        );
        return;
      }

      // 2 & 3. PUT the bytes straight to Drive, then confirm with the
      // backend so it can create the Media record.
      await runDirectUpload(item, session.upload_url);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload failed.";
      const wasCancelled = message === "Upload cancelled." || cancelledEarly;
      setItems((prev) =>
        prev.map((i) =>
          i.id === item.id
            ? wasCancelled
              ? withReleasedFile({ ...i, status: "cancelled" })
              : { ...i, status: "error", error: message }
            : i
        )
      );
    }
  }

  // Concurrency scheduler: the single place that decides whether a queued
  // file is allowed to start. Runs whenever the queue changes (a new batch
  // is added, an upload finishes/fails/is cancelled, pause is toggled) and
  // tops up the in-flight count to MAX_CONCURRENT_UPLOADS rather than
  // starting everything at once. "Active" includes "finalizing" - the
  // direct-to-Drive PUT has finished by then, but the backend confirmation
  // call is still an outstanding request occupying a real slot.
  useEffect(() => {
    if (paused) return;
    const active = items.filter((i) => i.status === "uploading" || i.status === "finalizing").length;
    const free = MAX_CONCURRENT_UPLOADS - active;
    if (free <= 0) return;
    const waiting = items.filter((i) => i.status === "queued" && i.file && !i.cancel);
    waiting.slice(0, free).forEach((i) => startUpload(i));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, paused]);

  // Auto-clear + completion toast: once every item has reached a terminal
  // state (done / error / cancelled), fire a one-time toast summarizing
  // the batch. Only auto-dismiss the list if nothing failed - a failed
  // upload staying visible until the person retries or explicitly clears
  // it is more important than a tidy list; silently vanishing failures
  // after 3 seconds would mean they're easy to miss entirely, especially
  // now that this can complete while the person is on a different page.
  useEffect(() => {
    if (items.length === 0) return;
    const allTerminal = items.every((i) => i.status === "done" || i.status === "error" || i.status === "cancelled");
    if (!allTerminal) return;

    if (!toastShownRef.current) {
      toastShownRef.current = true;
      const doneCount = items.filter((i) => i.status === "done").length;
      const failedCount = items.filter((i) => i.status === "error").length;
      const cancelledCount = items.filter((i) => i.status === "cancelled").length;
      if (failedCount === 0 && cancelledCount === 0 && doneCount > 0) {
        setToast({ text: `All ${doneCount} file${doneCount === 1 ? "" : "s"} uploaded successfully!`, kind: "success" });
      } else if (failedCount > 0) {
        setToast({
          text:
            doneCount > 0
              ? `${doneCount} uploaded, ${failedCount} failed.`
              : `Upload failed for ${failedCount} file${failedCount === 1 ? "" : "s"}.`,
          kind: "warn",
        });
      }
    }

    if (summary.failed === 0) {
      const timer = setTimeout(() => {
        setItems([]);
        toastShownRef.current = false;
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [items, summary.failed]);

  // Auto-dismiss the completion toast on its own timer.
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(timer);
  }, [toast]);

  function addFiles(files: File[], albumId: number) {
    if (files.length === 0 || !albumId) return;
    toastShownRef.current = false; // a fresh batch gets its own completion toast

    // Browser-memory guard: cap a single selection. A huge accidental
    // select-all shouldn't pin thousands of File handles in React state.
    let picked = files;
    if (picked.length > MAX_FILES_PER_SELECTION) {
      picked = picked.slice(0, MAX_FILES_PER_SELECTION);
      setToast({
        text: `Batch capped at ${MAX_FILES_PER_SELECTION} files - add the rest in another batch.`,
        kind: "warn",
      });
    }

    const newItems: UploadItem[] = picked.map((file) => ({
      id: generateUploadId(),
      file,
      filename: file.name,
      size: file.size,
      progress: 0,
      status: "queued",
      albumId,
    }));
    setItems((prev) => [...newItems, ...prev]);
    // Leave these as "queued" - the concurrency scheduler effect above
    // starts as many as MAX_CONCURRENT_UPLOADS allows (immediately, unless
    // paused) and picks up the rest as slots free up.
  }

  // Aborts an in-flight/uploading file, or - for one that hasn't started
  // yet (still queued, e.g. because the queue is paused) - simply marks
  // it cancelled locally since there's nothing on the wire to abort.
  function cancelItem(item: UploadItem) {
    if (item.cancel) {
      item.cancel();
    } else {
      setItems((prev) =>
        prev.map((i) => (i.id === item.id ? withReleasedFile({ ...i, status: "cancelled" }) : i))
      );
    }
    if (item.status === "uploading" || item.status === "finalizing") {
      // Tell the backend too (best-effort): without this the session
      // just sits in "uploading" server-side until the staleness sweep
      // eventually times it out (Section 4/9) - this server has no other
      // way to learn the browser gave up on a direct-to-Drive transfer.
      adminService.abandonUploadSession(item.id).catch(() => {});
    }
  }

  // Retries only the backend-confirmation step for an item whose file
  // already landed safely in Drive last time (driveFileId is cached) -
  // shared by retryItem and retryAllFailed below so a completeUpload
  // failure never means re-uploading the whole file again.
  function retryCompleteOnly(item: UploadItem) {
    setItems((prev) =>
      prev.map((i) => (i.id === item.id ? { ...i, status: "finalizing", cancel: undefined, error: undefined } : i))
    );
    adminService
      .completeUpload(
        item.id,
        item.driveFileId as string,
        item.reportedSize ?? item.file?.size ?? 0,
        item.reportedMimeType ?? item.file?.type ?? "application/octet-stream"
      )
      .then(() => {
        setItems((prev) =>
          prev.map((i) => (i.id === item.id ? withReleasedFile({ ...i, status: "done", progress: 100 }) : i))
        );
      })
      .catch((err) => {
        const message = err instanceof Error ? err.message : "Could not confirm the upload.";
        setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, status: "error", error: message } : i)));
      });
  }

  function retryItem(item: UploadItem) {
    if (!item.file) return; // restored items no longer have the File bytes
    toastShownRef.current = false;
    if (item.driveFileId) {
      // The file already landed safely in Drive last time - only the
      // backend's confirmation step failed (e.g. a dropped connection).
      // Retry that step directly rather than opening a brand new Drive
      // session and re-uploading the whole file.
      retryCompleteOnly(item);
      return;
    }
    setItems((prev) =>
      prev.map((i) =>
        i.id === item.id ? { ...i, status: "queued", progress: 0, cancel: undefined, error: undefined } : i
      )
    );
    // The concurrency scheduler effect picks this back up as soon as a
    // slot is free, same as any other queued item.
  }

  function retryAllFailed() {
    toastShownRef.current = false;
    // Items with a cached driveFileId only need the confirmation step
    // retried - kick those off directly rather than routing them back
    // through the "queued" scheduler, which would re-upload their bytes.
    items.filter((i) => i.status === "error" && i.file && i.driveFileId).forEach(retryCompleteOnly);
    // Everything else just moves back to "queued" - the concurrency
    // scheduler effect restarts them MAX_CONCURRENT_UPLOADS at a time
    // rather than firing them all back at the server in one burst, which
    // is exactly the "retry a big failed batch" case this matters most for.
    setItems((prev) =>
      prev.map((i) =>
        i.status === "error" && i.file && !i.driveFileId
          ? { ...i, status: "queued", progress: 0, cancel: undefined, error: undefined }
          : i
      )
    );
  }

  function clearList() {
    setItems([]);
    toastShownRef.current = false;
  }

  const value: UploadContextValue = {
    items,
    summary,
    paused,
    setPaused,
    toast,
    dismissToast: () => setToast(null),
    addFiles,
    cancelItem,
    retryItem,
    retryAllFailed,
    clearList,
  };

  return <UploadContext.Provider value={value}>{children}</UploadContext.Provider>;
}

export function useUploads(): UploadContextValue {
  const ctx = useContext(UploadContext);
  if (!ctx) {
    throw new Error("useUploads() must be used within <UploadProvider>.");
  }
  return ctx;
}