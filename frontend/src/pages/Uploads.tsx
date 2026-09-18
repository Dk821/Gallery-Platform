import {
  ChangeEvent,
  DragEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import AdminLayout from "../components/AdminLayout";
import { adminService, AlbumItem, ClientListItem, UploadSessionListItem } from "../services/admin";

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

interface UploadItem {
  id: string;
  file: File | null;
  filename: string;
  size?: number;
  progress: number;
  status: "queued" | "uploading" | "finalizing" | "done" | "error" | "cancelled";
  error?: string;
  cancel?: () => void;
  restored?: boolean;
  // Set once the browser's direct PUT to Drive has finished (Section:
  // architecture change) - lets retryItem() below skip straight to
  // re-confirming with the backend instead of re-uploading the whole
  // file again, if only that last confirmation step failed.
  driveFileId?: string;
  reportedSize?: number;
  reportedMimeType?: string;
}

const STATUS_LABEL: Record<UploadItem["status"], string> = {
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
function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exponent;
  const precision = exponent === 0 ? 0 : value < 10 ? 1 : 0;
  return `${value.toFixed(precision)} ${units[exponent]}`;
}

const VIDEO_EXTENSIONS = new Set(["mp4", "mov", "webm"]);

// Restored sessions only carry the filename (no File object / MIME type),
// so file-type detection has to work off the extension either way - this
// keeps new and restored rows visually consistent.
function isVideoFilename(filename: string): boolean {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  return VIDEO_EXTENSIONS.has(ext);
}

// Caps how many files this page will have in flight (sending bytes
// directly to Drive, or awaiting the backend's post-upload confirmation)
// at once. Without this, selecting a big batch (a whole shoot: 100+
// photos and videos) fired every file's direct-to-Drive PUT
// simultaneously - which the browser's own per-origin connection limit
// would partly queue anyway, but a large burst is still harder to reason
// about and retry than a batch that quietly works its way through a
// small number of slots.
const MAX_CONCURRENT_UPLOADS = 4;

export default function Uploads() {
  const [clients, setClients] = useState<ClientListItem[]>([]);
  const [albums, setAlbums] = useState<AlbumItem[]>([]);
  const [clientId, setClientId] = useState<number | null>(null);
  const [albumId, setAlbumId] = useState<number | null>(null);
  const [items, setItems] = useState<UploadItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [paused, setPaused] = useState(false);
  const [toast, setToast] = useState<{ text: string; kind: "success" | "warn" } | null>(null);
  const toastShownRef = useRef(false);

  useEffect(() => {
    Promise.all([adminService.listClients(1, 200), adminService.listAlbums(1, 200)])
      .then(([clientPage, albumPage]) => {
        setClients(clientPage.items);
        setAlbums(albumPage.items);
        if (clientPage.items.length > 0) setClientId(clientPage.items[0].id);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load clients."));
  }, []);

  // Refresh-recovery (Section 4): only restore ACTIVE uploads (queued /
  // uploading). Completed, failed, and cancelled sessions are not shown as
  // history — the panel is for active uploads only (Google Drive pattern).
  useEffect(() => {
    let cancelled = false;
    adminService
      .listUploadSessions(100)
      .then((sessions: UploadSessionListItem[]) => {
        if (cancelled) return;
        // Only keep sessions that are still in-flight on the server.
        // Completed / failed / cancelled sessions are deliberately excluded
        // so the upload panel never turns into a history list.
        const active = sessions.filter(
          (s) => s.status === "queued" || s.status === "uploading"
        );
        // Unlike the old byte-relaying flow, a restored "active" session
        // can never actually resume: the browser talks to Drive directly
        // now, and the File object that PUT was reading from is gone the
        // moment the tab was closed/refreshed - there is nothing left on
        // this server that could still be transferring it. Show these as
        // needing a fresh upload rather than polling a session that will
        // just sit there until the server's own staleness sweep eventually
        // times it out.
        const restored: UploadItem[] = active.map((s) => ({
          id: s.upload_id,
          file: null,
          filename: s.filename,
          size: s.total_bytes,
          progress: s.percentage,
          status: "error",
          error: "This upload was interrupted (browser closed or refreshed). Please re-select and upload this file again.",
          restored: true,
        }));
        setItems((prev) => {
          const ids = new Set(prev.map((i) => i.id));
          return [...prev, ...restored.filter((r) => !ids.has(r.id))];
        });
      })
      .catch(() => {
        // Non-fatal: the page still fully works for new uploads; we just
        // don't restore active sessions if the backend isn't reachable.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const albumsForClient = albums.filter((a) => a.client_id === clientId);

  useEffect(() => {
    if (albumsForClient.length > 0 && !albumsForClient.some((a) => a.id === albumId)) {
      setAlbumId(albumsForClient[0].id);
    }
    if (albumsForClient.length === 0) {
      setAlbumId(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId, albums]);

  const summary = useMemo(() => {
    const total = items.length;
    const completed = items.filter((i) => i.status === "done").length;
    const failed = items.filter((i) => i.status === "error").length;
    const cancelled = items.filter((i) => i.status === "cancelled").length;
    const overallPercent =
      total === 0 ? 0 : Math.round(items.reduce((sum, i) => sum + (i.status === "done" ? 100 : i.progress), 0) / total);
    return { total, completed, failed, cancelled, overallPercent };
  }, [items]);

  // Concurrency scheduler: the single place that decides whether a queued
  // file is allowed to start. Runs whenever the queue changes (a new batch
  // is added, an upload finishes/fails/is cancelled, pause is toggled) and
  // tops up the in-flight count to MAX_CONCURRENT_UPLOADS rather than
  // starting everything at once. "Active" includes "finalizing" - the
  // browser's XHR connection for that file stays open for the whole
  // request/response cycle, which doesn't complete until the server has
  // finished relaying the file to Drive, not just until the bytes are sent
  // - so a "finalizing" item is still occupying a real connection/slot.
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
  // the batch. Only auto-dismiss the panel if nothing failed - a failed
  // upload staying on screen until the person retries or explicitly
  // clears it is more important than a tidy panel; silently vanishing
  // failures after 3 seconds (the old behavior) meant they were easy to
  // miss entirely.
  useEffect(() => {
    if (items.length === 0) return;
    const allTerminal = items.every(
      (i) => i.status === "done" || i.status === "error" || i.status === "cancelled"
    );
    if (!allTerminal) return;

    if (!toastShownRef.current) {
      toastShownRef.current = true;
      const doneCount = items.filter((i) => i.status === "done").length;
      const failedCount = items.filter((i) => i.status === "error").length;
      const cancelledCount = items.filter((i) => i.status === "cancelled").length;
      if (failedCount === 0 && cancelledCount === 0 && doneCount > 0) {
        setToast({
          text: `All ${doneCount} file${doneCount === 1 ? "" : "s"} uploaded successfully!`,
          kind: "success",
        });
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

  // Best-effort progress reporting to the backend (Section 8) while
  // uploadToDrive's own onProgress already drives the visible bar - this
  // just lets OTHER views (a second tab, this page after a refresh) see
  // roughly where things stand. Throttled to ~1/second; a dropped ping is
  // never fatal, so failures are swallowed here rather than surfaced.
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

    const { promise, cancel } = adminService.uploadToDrive(uploadUrl, item.file, (percent) => {
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, progress: percent } : i)));
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
              ? { ...i, status: "cancelled" }
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
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, status: "done", progress: 100 } : i)));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not confirm the upload.";
      // driveFileId (set above) stays on the item - the file is already
      // safely in Drive, so a retry from here should call completeUpload
      // again, NOT re-upload the bytes (see retryItem below).
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, status: "error", error: message } : i)));
    }
  }

  async function startUpload(item: UploadItem) {
    if (!albumId || !item.file) return;
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
        prev.map((i) => (i.id === item.id ? { ...i, status: "cancelled", cancel: undefined } : i))
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
      const session = await adminService.createUploadSession(albumId, uploadId, item.filename, item.file.size);
      if (cancelledEarly) return; // user cancelled during reservation

      if (!session.upload_url) {
        // Idempotent replay: this upload_id already finished earlier -
        // nothing to send.
        setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, status: "done", progress: 100 } : i)));
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
              ? { ...i, status: "cancelled" }
              : { ...i, status: "error", error: message }
            : i
        )
      );
    }
  }

  // Aborts an in-flight/uploading file, or - for one that hasn't started
  // yet (still queued, e.g. because the queue is paused) - simply marks
  // it cancelled locally since there's nothing on the wire to abort.
  function cancelItem(item: UploadItem) {
    if (item.cancel) {
      item.cancel();
    } else {
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, status: "cancelled" } : i)));
    }
    if (item.status === "uploading" || item.status === "finalizing") {
      // Tell the backend too (best-effort): without this the session
      // just sits in "uploading" server-side until the staleness sweep
      // eventually times it out (Section 4/9) - this server has no other
      // way to learn the browser gave up on a direct-to-Drive transfer.
      adminService.abandonUploadSession(item.id).catch(() => {});
    }
  }

  // Shared by both the file picker and drag-and-drop - same UploadItem
  // shape, same startUpload() call, same idempotency behavior either way.
  function handleFiles(files: File[]) {
    if (files.length === 0 || !albumId) return;

    toastShownRef.current = false; // a fresh batch gets its own completion toast
    const newItems: UploadItem[] = files.map((file) => ({
      id: generateUploadId(),
      file,
      filename: file.name,
      size: file.size,
      progress: 0,
      status: "queued",
    }));
    setItems((prev) => [...newItems, ...prev]);
    // Leave these as "queued" - the concurrency scheduler effect above
    // starts as many as MAX_CONCURRENT_UPLOADS allows (immediately, unless
    // paused) and picks up the rest as slots free up.
  }

  function handleFilesSelected(e: ChangeEvent<HTMLInputElement>) {
    const fileList = e.target.files;
    handleFiles(fileList ? Array.from(fileList) : []);
    e.target.value = ""; // allow re-selecting the same file later
  }

  function handleDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setDragActive(false);
    if (!albumId) return;
    handleFiles(Array.from(e.dataTransfer.files));
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
        setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, status: "done", progress: 100 } : i)));
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

  return (
    <AdminLayout>
      <h1 className="admin-page-title">Uploads</h1>
      <p className="admin-page-subtitle">Upload photos and videos directly into an album's Drive folder.</p>

      {error && <p className="auth-error">{error}</p>}

      {clients.length === 0 ? (
        <div className="empty-state">Create a client and an album before uploading files.</div>
      ) : (
        <>
          <div className="admin-panel-card upload-panel-card">
            <div className="upload-field-row">
              <label className="upload-field">
                Client
                <select
                  value={clientId ?? ""}
                  onChange={(e) => setClientId(Number(e.target.value))}
                  className="upload-select"
                >
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.client_name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="upload-field">
                Album
                <select
                  value={albumId ?? ""}
                  onChange={(e) => setAlbumId(Number(e.target.value))}
                  className="upload-select"
                  disabled={albumsForClient.length === 0}
                >
                  {albumsForClient.length === 0 && <option value="">No albums for this client</option>}
                  {albumsForClient.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.album_name}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <label
              className={"upload-dropzone" + (dragActive ? " upload-dropzone--active" : "")}
              style={{ opacity: albumId ? 1 : 0.5, cursor: albumId ? "pointer" : "not-allowed" }}
              onDragOver={(e) => {
                e.preventDefault();
                if (albumId) setDragActive(true);
              }}
              onDragLeave={() => setDragActive(false)}
              onDrop={handleDrop}
            >
              <span className="upload-dropzone__icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <path
                    d="M7 18a4.5 4.5 0 01-.4-8.98 5.5 5.5 0 0110.7-1.9A4.5 4.5 0 0117 18H7z"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path d="M12 12v6m-2.5-3.5L12 18l2.5-2.5" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
              <span className="upload-dropzone__title">Drag photos and videos here, or click to browse</span>
              <span className="upload-dropzone__hint">JPG, PNG, WEBP, GIF, MP4, MOV, WEBM</span>
              <input
                type="file"
                multiple
                accept=".jpg,.jpeg,.png,.webp,.gif,.mp4,.mov,.webm"
                onChange={handleFilesSelected}
                disabled={!albumId}
                style={{ display: "none" }}
              />
            </label>
          </div>

          {summary.total > 0 && (
            <div className="admin-panel-card upload-panel-card" style={{ marginTop: "1.5rem" }}>
              <div className="upload-summary-header">
                <span className="upload-summary-title">
                  {paused ? "Paused" : "Uploading"} {summary.total} {summary.total === 1 ? "file" : "files"}
                </span>
                <div style={{ display: "flex", alignItems: "center", gap: "0.9rem" }}>
                  <span className="upload-summary-pct">{summary.overallPercent}%</span>
                  <button
                    className="btn-text"
                    onClick={() => setPaused((p) => !p)}
                    title={paused ? "Resume starting queued uploads" : "Pause starting new uploads (in-flight files keep going)"}
                  >
                    {paused ? "Resume" : "Pause"}
                  </button>
                  <button className="btn-text" onClick={clearList} title="Clear this list">
                    Clear
                  </button>
                </div>
              </div>

              <div className="upload-progress-track">
                <div className="upload-progress-fill" style={{ width: `${summary.overallPercent}%` }} />
              </div>

              <div className="upload-summary-footer">
                <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                  {summary.completed} / {summary.total} completed
                  {summary.failed > 0 && ` · ${summary.failed} failed`}
                  {summary.cancelled > 0 && ` · ${summary.cancelled} cancelled`}
                </span>
                {summary.failed > 0 && (
                  <button className="btn-secondary" onClick={retryAllFailed}>
                    Retry Failed
                  </button>
                )}
              </div>

              <div className="upload-list">
                {items.map((item) => {
                  // Cancel only works while bytes are still queued/being sent
                  // (xhr.abort() actually stops something in that window).
                  // Once "finalizing" the browser has already sent every
                  // byte and our server is relaying to Drive - aborting the
                  // client-side xhr at that point wouldn't stop anything
                  // real, just misleadingly show "cancelled" in the UI.
                  // Restored items (from a page refresh) never got a local
                  // `cancel` fn in this session either, for the same reason.
                  const canCancel = !item.restored && (item.status === "queued" || item.status === "uploading");
                  const video = isVideoFilename(item.filename);
                  return (
                    <div key={item.id} className="upload-row">
                      <div className={"upload-row__icon" + (video ? " upload-row__icon--video" : " upload-row__icon--photo")}>
                        {video ? (
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                            <rect x="3" y="6" width="13" height="12" rx="2" strokeWidth="1.8" />
                            <path d="M16 10l5-3v10l-5-3" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        ) : (
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                            <rect x="3" y="5" width="18" height="14" rx="2" strokeWidth="1.8" />
                            <circle cx="8.5" cy="10" r="1.5" strokeWidth="1.8" />
                            <path
                              d="M21 16l-5.5-5.5a2 2 0 00-2.8 0L5 18"
                              strokeWidth="1.8"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                        )}
                      </div>
                      <div className="upload-row__body">
                        <div className="upload-row__top">
                          <span className="upload-row__name">{item.filename}</span>
                          <span className={"upload-row__badge upload-row__badge--" + item.status}>
                            {STATUS_LABEL[item.status]}
                          </span>
                        </div>
                        <div className="upload-row__meta-row">
                          <span className="upload-row__meta">
                            {item.size != null && <span className="upload-row__size">{formatBytes(item.size)}</span>}
                            {item.size != null && <span className="upload-row__meta-sep">·</span>}
                            {item.status === "done" && "100%"}
                            {item.status === "uploading" && `${item.progress}% sent`}
                            {item.status === "finalizing" && `${item.progress}% (finalizing)`}
                            {item.status === "queued" && (paused ? "Paused" : "Waiting")}
                            {item.status === "error" && "Failed"}
                            {item.status === "cancelled" && "Cancelled"}
                          </span>
                          {canCancel && (
                            <button className="upload-row__cancel" onClick={() => cancelItem(item)} title="Cancel this file">
                              Cancel
                            </button>
                          )}
                        </div>
                        <div className="upload-progress-track upload-progress-track--thin">
                          <div
                            className={"upload-progress-fill" + (item.status === "error" ? " upload-progress-fill--error" : "")}
                            style={{ width: `${item.status === "done" ? 100 : item.progress}%` }}
                          />
                        </div>
                        {item.status === "error" && (
                          <div className="upload-row__error">
                            <span style={{ color: "var(--danger)", fontSize: "0.8rem" }}>{item.error}</span>
                            {item.file ? (
                              <button className="btn-text" onClick={() => retryItem(item)}>
                                Retry
                              </button>
                            ) : (
                              <span style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>
                                Select the file again to retry
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}

      {toast && (
        <div className={"upload-toast" + (toast.kind === "success" ? " upload-toast--success" : " upload-toast--warn")}>
          <span>{toast.text}</span>
          <button className="upload-toast__close" onClick={() => setToast(null)} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}
    </AdminLayout>
  );
}
