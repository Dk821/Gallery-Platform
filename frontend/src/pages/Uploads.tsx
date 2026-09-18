import { ChangeEvent, DragEvent, useEffect, useState } from "react";
import AdminLayout from "../components/AdminLayout";
import { adminService, AlbumItem, ClientListItem } from "../services/admin";
import { STATUS_LABEL, UploadItem, formatBytes, useUploads } from "../contexts/Uploadcontext";

const VIDEO_EXTENSIONS = new Set(["mp4", "mov", "webm"]);

// Restored sessions only carry the filename (no File object / MIME type),
// so file-type detection has to work off the extension either way - this
// keeps new and restored rows visually consistent.
function isVideoFilename(filename: string): boolean {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  return VIDEO_EXTENSIONS.has(ext);
}

export default function Uploads() {
  // Everything about the actual upload queue/transfer lives in
  // UploadContext now (mounted once at the app root - see App.tsx) so it
  // survives navigating to another admin page and back. This component
  // only owns what's genuinely page-local: the client/album picker and
  // the dropzone's drag state.
  const { items, summary, paused, setPaused, toast, dismissToast, addFiles, cancelItem, retryItem, retryAllFailed, clearList } =
    useUploads();

  const [clients, setClients] = useState<ClientListItem[]>([]);
  const [albums, setAlbums] = useState<AlbumItem[]>([]);
  const [clientId, setClientId] = useState<number | null>(null);
  const [albumId, setAlbumId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([adminService.listClients(1, 200), adminService.listAlbums(1, 200)])
      .then(([clientPage, albumPage]) => {
        if (cancelled) return;
        setClients(clientPage.items);
        setAlbums(albumPage.items);
        if (clientPage.items.length > 0) setClientId(clientPage.items[0].id);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load clients.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
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

  // Shared by both the file picker and drag-and-drop - same UploadItem
  // shape, same startUpload() call, same idempotency behavior either way.
  function handleFilesSelected(e: ChangeEvent<HTMLInputElement>) {
    const fileList = e.target.files;
    if (fileList && albumId) addFiles(Array.from(fileList), albumId);
    e.target.value = ""; // allow re-selecting the same file later
  }

  function handleDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setDragActive(false);
    if (!albumId) return;
    addFiles(Array.from(e.dataTransfer.files), albumId);
  }

  return (
    <AdminLayout>
      <h1 className="admin-page-title">Uploads</h1>
      <p className="admin-page-subtitle">Upload photos and videos directly into an album's Drive folder.</p>

      {error && <p className="auth-error">{error}</p>}

      {loading ? (
        <div className="empty-state">Loading clients and albums…</div>
      ) : clients.length === 0 ? (
        <div className="empty-state">Create a client and an album before uploading files.</div>
      ) : (
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
      )}

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
                {items.map((item: UploadItem) => {
                  // Cancel only works while bytes are still queued/being
                  // sent (xhr.abort() actually stops something in that
                  // window). Once "finalizing" the browser has already
                  // sent every byte and is just awaiting the backend's
                  // confirmation call - aborting the client-side xhr at
                  // that point wouldn't stop anything real, just
                  // misleadingly show "cancelled" in the UI. Restored
                  // items (from a page refresh) never got a local
                  // `cancel` fn in this session either, for the same
                  // reason.
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

      {toast && (
        <div className={"upload-toast" + (toast.kind === "success" ? " upload-toast--success" : " upload-toast--warn")}>
          <span>{toast.text}</span>
          <button className="upload-toast__close" onClick={dismissToast} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}
    </AdminLayout>
  );
}