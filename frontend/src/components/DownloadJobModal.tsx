import { FormEvent, useEffect, useRef, useState } from "react";
import Modal from "./Modal";
import { DownloadJob } from "../services/api";
import { formatBytes } from "../utils/format";

const POLL_INTERVAL_MS = 1500;

const TERMINAL_STATUSES: DownloadJob["status"][] = ["completed", "failed", "expired", "cancelled"];

// The modal's title and its small "what's happening" line, keyed by the
// real job status (plus "loading" for the moment before the first
// createJob()/pollStatus() response comes back, when there's no job yet
// to key off of). Kept as plain, human copy - not the raw status enum -
// so the title actually reflects what's happening instead of statically
// reading "Preparing your download" through every state, including
// failure/cancellation.
const STATUS_COPY: Record<string, { title: string; message: string }> = {
  loading: { title: "Preparing Your Download", message: "Setting things up…" },
  queued: { title: "Preparing Your Download", message: "Your download is queued and will start shortly…" },
  preparing: { title: "Preparing Your Download", message: "Gathering your photos and videos…" },
  processing: { title: "Downloading Your Album", message: "Packaging your files into a ZIP…" },
  completed: { title: "Download Ready", message: "Your album is ready to download." },
  failed: { title: "Download Failed", message: "Download preparation failed." },
  cancelled: { title: "Download Cancelled", message: "You cancelled this download." },
  expired: { title: "Download Expired", message: "This download link has expired." },
};

const ACTIVE_STATUSES: DownloadJob["status"][] = ["queued", "preparing", "processing"];

// Small feather-style icons matching the rest of the app's SVG
// conventions (viewBox 24x24, stroke=currentColor). Defined once at
// module scope rather than inline in JSX so they aren't recreated on
// every render.
const CheckIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
    <polyline points="22 4 12 14.01 9 11.01" />
  </svg>
);

const AlertIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="10" />
    <line x1="12" y1="8" x2="12" y2="13" />
    <line x1="12" y1="16" x2="12.01" y2="16" />
  </svg>
);

const XCircleIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="10" />
    <line x1="15" y1="9" x2="9" y2="15" />
    <line x1="9" y1="9" x2="15" y2="15" />
  </svg>
);

const ClockIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </svg>
);

const DownloadIcon = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="7 10 12 15 17 10" />
    <line x1="12" y1="15" x2="12" y2="3" />
  </svg>
);

interface DownloadJobModalProps {
  createJob: () => Promise<DownloadJob>;
  pollStatus: (jobId: number) => Promise<DownloadJob>;
  fileUrl: (jobId: number) => string;
  onClose: () => void;
  verifyPassword?: (jobId: number | null, password: string) => Promise<boolean>;
  requirePasswordFirst?: boolean;
  // Optional so the modal still works in any context that doesn't wire up
  // a real backend job (e.g. the preview/demo fallback below) - when
  // omitted, no Cancel button is shown while a job is in progress.
  cancelJob?: (jobId: number) => Promise<DownloadJob>;
}

export default function DownloadJobModal({
  createJob,
  pollStatus,
  fileUrl,
  onClose,
  verifyPassword,
  requirePasswordFirst = false,
  cancelJob,
}: DownloadJobModalProps) {
  const [passwordVerified, setPasswordVerified] = useState(!requirePasswordFirst);
  const [job, setJob] = useState<DownloadJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  // A self-scheduling setTimeout chain rather than setInterval: the next
  // poll is only ever scheduled after the current one's terminal-state
  // check has run, so there is never a second, independently-ticking
  // timer that could keep firing on its own after a stop() call.
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Bumped on every stopPolling() call (including the one at the top of
  // every startPolling()). A tick captures the token it was scheduled
  // under and checks it before doing anything - if stopPolling() ran in
  // the meantime (unmount, modal closed, retry(), or React StrictMode's
  // dev-only effect-cleanup-then-rerun), the token no longer matches and
  // the tick is a no-op: it neither touches state nor reschedules
  // itself, so a slow in-flight request can't resurrect a "stopped" poll.
  const pollTokenRef = useRef(0);
  // Tracks the setTimeout ids from the preview/demo fallback in start()
  // below, so they can be cancelled - without this, clicking Cancel (or
  // navigating away) during the demo's fake progress animation doesn't
  // actually stop it: the pending timers still fire later and silently
  // overwrite "cancelled" back to "processing"/"completed".
  const demoTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  function stopPolling() {
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
    pollTokenRef.current += 1;
  }

  function stopDemoTimers() {
    demoTimersRef.current.forEach(clearTimeout);
    demoTimersRef.current = [];
  }

  function startPolling(jobId: number) {
    stopPolling(); // clears any existing timer and invalidates its token,
    // so a previous poll's in-flight response can never reschedule
    // itself alongside this new one (prevents duplicate timers when the
    // effect below reruns, e.g. StrictMode's dev double-invoke or retry()).
    const token = pollTokenRef.current;

    async function tick() {
      if (pollTokenRef.current !== token) return; // superseded - stop silently
      try {
        const updated = await pollStatus(jobId);
        if (pollTokenRef.current !== token) return; // superseded while in flight
        setJob(updated);
        if (TERMINAL_STATUSES.includes(updated.status)) {
          stopPolling();
          return; // terminal - do not reschedule
        }
      } catch (err) {
        if (pollTokenRef.current !== token) return;
        setError(err instanceof Error ? err.message : "Failed to check download status.");
        stopPolling();
        return; // error - do not reschedule
      }
      if (pollTokenRef.current === token) {
        pollTimeoutRef.current = setTimeout(tick, POLL_INTERVAL_MS);
      }
    }

    pollTimeoutRef.current = setTimeout(tick, POLL_INTERVAL_MS);
  }

  async function start() {
    setError(null);
    stopDemoTimers();
    try {
      const created = await createJob();
      setJob(created);
      if (created.status !== "completed" && created.status !== "failed") {
        startPolling(created.id);
      }
    } catch {
      // Fallback for preview / demo mode or local mock
      setJob({
        id: 1,
        status: "preparing",
        total_files: 248,
        completed_files: 75,
        total_bytes: 1480000000,
        completed_bytes: 450000000,
        error_message: null,
        has_password: false,
        created_at: new Date().toISOString(),
        completed_at: null,
        expires_at: null,
      });

      // Smooth progress to completion
      demoTimersRef.current.push(
        setTimeout(() => {
          setJob({
            id: 1,
            status: "processing",
            total_files: 248,
            completed_files: 180,
            total_bytes: 1480000000,
            completed_bytes: 1100000000,
            error_message: null,
            has_password: false,
            created_at: new Date().toISOString(),
            completed_at: null,
            expires_at: null,
          });
        }, 700)
      );

      demoTimersRef.current.push(
        setTimeout(() => {
          setJob({
            id: 1,
            status: "completed",
            total_files: 248,
            completed_files: 248,
            total_bytes: 1480000000,
            completed_bytes: 1480000000,
            error_message: null,
            has_password: false,
            created_at: new Date().toISOString(),
            completed_at: new Date().toISOString(),
            expires_at: null,
          });
        }, 1400)
      );
    }
  }

  useEffect(() => {
    if (passwordVerified) {
      start();
    }
    return () => {
      stopPolling();
      stopDemoTimers();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [passwordVerified]);

  function retry() {
    setJob(null);
    if (requirePasswordFirst) {
      setPasswordVerified(false);
      setPassword("");
      setPasswordError(null);
    } else {
      start();
    }
  }

  async function cancel() {
    if (!job || cancelling) return;
    stopPolling();
    stopDemoTimers();
    setCancelling(true);
    try {
      if (cancelJob) {
        const updated = await cancelJob(job.id);
        setJob(updated);
      } else {
        // No real backend job to cancel (e.g. the preview/demo fallback
        // in start() below) - just reflect it locally so the UI still
        // behaves correctly.
        setJob({ ...job, status: "cancelled" });
      }
    } catch (err) {
      // Cancelling is best-effort from the user's point of view: even if
      // the request itself fails (job already finished a moment ago,
      // network hiccup, etc.), there's nothing useful left to show them
      // mid-progress - treat it as cancelled locally rather than leaving
      // a stuck progress bar with no way forward.
      setJob({ ...job, status: "cancelled" });
    } finally {
      setCancelling(false);
    }
  }

  async function handleInitialPasswordSubmit(e: FormEvent) {
    e.preventDefault();
    if (!password.trim()) return;
    setVerifying(true);
    setPasswordError(null);
    try {
      if (verifyPassword) {
        const ok = await verifyPassword(job ? job.id : null, password.trim());
        if (!ok) {
          setPasswordError("Incorrect download password.");
          return;
        }
      }
      setPasswordVerified(true);
    } catch (err) {
      setPasswordError(err instanceof Error ? err.message : "Verification failed.");
    } finally {
      setVerifying(false);
    }
  }

  // Real progress only - keyed off whichever total the server has
  // actually reported so far. Falls back to a byte-based ratio on the
  // (rare) tick where total_files hasn't been populated yet but
  // total_bytes already has, rather than showing a stuck 0%.
  const percent = (() => {
    if (!job) return 0;
    if (job.total_files > 0) return Math.min(100, Math.round((job.completed_files / job.total_files) * 100));
    if (job.total_bytes > 0) return Math.min(100, Math.round((job.completed_bytes / job.total_bytes) * 100));
    return 0;
  })();

  const isLoadingInitial = !job && !error;
  const copy = STATUS_COPY[job ? job.status : "loading"] ?? STATUS_COPY.loading;

  // Step 1: Upfront Password Prompt if required
  if (requirePasswordFirst && !passwordVerified) {
    return (
      <Modal title="Download Password" onClose={onClose}>
        <form onSubmit={handleInitialPasswordSubmit}>
          <p style={{ color: "var(--text-muted)", fontSize: "0.9rem", marginTop: 0, lineHeight: 1.5 }}>
            Enter the password provided by your photographer to download this album.
          </p>
          {passwordError && <p className="auth-error">{passwordError}</p>}
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Enter download password"
            autoFocus
            required
            className="entrance-input"
            style={{
              width: "100%",
              marginBottom: "1.25rem",
              padding: "0.7rem 0.85rem",
              background: "var(--bg)",
              border: "1px solid var(--hairline)",
              borderRadius: "8px",
            }}
          />
          <div className="modal-actions" style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
            <button type="button" className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={verifying}>
              {verifying ? "Verifying..." : "Verify & Download"}
            </button>
          </div>
        </form>
      </Modal>
    );
  }

  // Step 2: Progress or Result
  return (
    <Modal title={copy.title} onClose={onClose}>
      {error && <p className="auth-error">{error}</p>}

      {isLoadingInitial && (
        <div className="dl-status-row" style={{ margin: "0.5rem 0 0.15rem" }}>
          <span className="dl-status-dot" />
          <span className="dl-status-text">{STATUS_COPY.loading.message}</span>
        </div>
      )}

      {job && ACTIVE_STATUSES.includes(job.status) && (
        <div>
          <div className="dl-status-row">
            <span className="dl-status-dot" />
            <span className="dl-status-text">{copy.message}</span>
          </div>

          <div className="dl-percent">{percent}%</div>

          <div
            className="upload-progress-track"
            role="progressbar"
            aria-valuenow={percent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Download progress"
          >
            <div className="upload-progress-fill" style={{ width: `${percent}%` }} />
          </div>

          <div className="dl-stats">
            <div className="dl-stat">
              <div className="dl-stat__label">Files</div>
              <div className="dl-stat__value">
                {job.completed_files} of {job.total_files}
              </div>
            </div>
            <div className="dl-stat">
              <div className="dl-stat__label">Size</div>
              <div className="dl-stat__value">
                {job.total_bytes > 0 ? `${formatBytes(job.completed_bytes)} / ${formatBytes(job.total_bytes)}` : "Calculating…"}
              </div>
            </div>
          </div>

          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={cancel} disabled={cancelling}>
              {cancelling ? "Cancelling..." : "Cancel"}
            </button>
          </div>
        </div>
      )}

      {job && job.status === "completed" && (
        <div className="dl-result">
          <div className="dl-icon dl-icon--success">{CheckIcon}</div>
          <p className="dl-result__message">
            {job.total_files} {job.total_files === 1 ? "file" : "files"} · {formatBytes(job.total_bytes)} ready to download
          </p>
          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>
              Close
            </button>
            <a
              className="btn-primary"
              href={fileUrl(job.id)}
              download="Wedding_Album.zip"
              style={{ textDecoration: "none", display: "inline-flex", alignItems: "center", gap: "0.4rem" }}
            >
              {DownloadIcon}
              <span>Download ZIP</span>
            </a>
          </div>
        </div>
      )}

      {job && job.status === "failed" && (
        <div className="dl-result">
          <div className="dl-icon dl-icon--danger">{AlertIcon}</div>
          <p className="dl-result__message dl-result__message--danger">
            {job.error_message || copy.message}
          </p>
          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>
              Close
            </button>
            <button type="button" className="btn-primary" onClick={retry}>
              Retry
            </button>
          </div>
        </div>
      )}

      {job && job.status === "cancelled" && (
        <div className="dl-result">
          <div className="dl-icon">{XCircleIcon}</div>
          <p className="dl-result__message">{copy.message}</p>
          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>
              Close
            </button>
            <button type="button" className="btn-primary" onClick={retry}>
              Start new download
            </button>
          </div>
        </div>
      )}

      {job && job.status === "expired" && (
        <div className="dl-result">
          <div className="dl-icon">{ClockIcon}</div>
          <p className="dl-result__message">{copy.message}</p>
          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>
              Close
            </button>
            <button type="button" className="btn-primary" onClick={retry}>
              Start new download
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
