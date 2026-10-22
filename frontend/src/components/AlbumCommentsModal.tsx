import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Modal from "./Modal";
import { adminService, AlbumComment, AlbumItem } from "../services/admin";

type CommentFilter = "all" | "open" | "resolved";

interface AlbumCommentsModalProps {
  album: AlbumItem;
  onClose: () => void;
  // Keeps the album's badge count in step with the list without refetching
  // the whole page after every resolve / delete.
  onCountChange: (count: number) => void;
}

/**
 * Every page note on one album, grouped by the page it belongs to. More than
 * one client can hold a gallery link, so a page may carry several notes.
 */
export default function AlbumCommentsModal({ album, onClose, onCountChange }: AlbumCommentsModalProps) {
  const [comments, setComments] = useState<AlbumComment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [filter, setFilter] = useState<CommentFilter>("all");
  const [busyId, setBusyId] = useState<number | null>(null);

  // The parent passes a fresh arrow for onCountChange on every render, so it
  // is held in a ref: the load effect must depend only on the album, or one
  // count update would re-trigger the fetch in a loop.
  const onCountChangeRef = useRef(onCountChange);
  useEffect(() => {
    onCountChangeRef.current = onCountChange;
  }, [onCountChange]);

  const applyComments = useCallback((next: AlbumComment[]) => {
    setComments(next);
    onCountChangeRef.current(next.length);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      applyComments(await adminService.listAlbumComments(album.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this album's notes.");
    } finally {
      setLoading(false);
    }
  }, [album.id, applyComments]);

  useEffect(() => {
    load();
  }, [load]);

  const openCount = comments.filter((c) => c.status === "open").length;
  const resolvedCount = comments.length - openCount;

  // Build page groups from the filtered set, in page order.
  const groups = useMemo(() => {
    const visible = filter === "all" ? comments : comments.filter((c) => c.status === filter);
    const byPage = new Map<number, AlbumComment[]>();
    for (const note of visible) {
      const bucket = byPage.get(note.page_number);
      if (bucket) bucket.push(note);
      else byPage.set(note.page_number, [note]);
    }
    return Array.from(byPage.entries()).sort((a, b) => a[0] - b[0]);
  }, [comments, filter]);

  async function toggleStatus(note: AlbumComment) {
    if (busyId !== null) return;
    setBusyId(note.id);
    setActionError(null);
    try {
      const updated = await adminService.updateAlbumComment(note.id, {
        status: note.status === "open" ? "resolved" : "open",
      });
      applyComments(comments.map((c) => (c.id === updated.id ? updated : c)));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not update the note.");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(note: AlbumComment) {
    if (busyId !== null) return;
    if (!window.confirm("Delete this note permanently? The client will no longer see it.")) return;
    setBusyId(note.id);
    setActionError(null);
    try {
      await adminService.removeAlbumComment(note.id);
      applyComments(comments.filter((c) => c.id !== note.id));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not delete the note.");
    } finally {
      setBusyId(null);
    }
  }

  const description =
    comments.length === 0
      ? "Notes clients leave while reading the Book View land here."
      : `${comments.length} note${comments.length === 1 ? "" : "s"} · ${openCount} awaiting review.`;

  return (
    <Modal title={`Notes · ${album.album_name}`} description={description} onClose={onClose} className="comments-modal">
      <div className="comments-panel">
        {comments.length > 0 && (
          <div className="comments-filter" role="group" aria-label="Filter notes">
            <button
              type="button"
              className={`comments-filter__chip${filter === "all" ? " is-active" : ""}`}
              aria-pressed={filter === "all"}
              onClick={() => setFilter("all")}
            >
              All <span>{comments.length}</span>
            </button>
            <button
              type="button"
              className={`comments-filter__chip${filter === "open" ? " is-active" : ""}`}
              aria-pressed={filter === "open"}
              onClick={() => setFilter("open")}
            >
              Open <span>{openCount}</span>
            </button>
            <button
              type="button"
              className={`comments-filter__chip${filter === "resolved" ? " is-active" : ""}`}
              aria-pressed={filter === "resolved"}
              onClick={() => setFilter("resolved")}
            >
              Resolved <span>{resolvedCount}</span>
            </button>
          </div>
        )}

        {loading && <div className="comments-empty">Loading notes…</div>}

        {!loading && error && (
          <div className="comments-empty">
            <p>{error}</p>
            <button type="button" className="btn-secondary" onClick={load}>
              Try again
            </button>
          </div>
        )}

        {!loading && !error && comments.length === 0 && (
          <div className="comments-empty">No page notes on this album yet.</div>
        )}

        {!loading && !error && comments.length > 0 && groups.length === 0 && (
          <div className="comments-empty">No {filter} notes. Try another filter.</div>
        )}

        {!loading && !error && groups.length > 0 && (
          <ul className="comments-list">
            {groups.map(([page, notes]) => {
              const first = notes[0];
              return (
                <li key={page} className="comments-group">
                  <div className="comments-group__head">
                    <span className="comments-group__page">Page {page}</span>
                    {first.media_id && first.has_thumbnail ? (
                      <img
                        className="comments-group__thumb"
                        src={adminService.adminThumbnailUrl(first.media_id)}
                        alt=""
                        loading="lazy"
                      />
                    ) : (
                      <span className="comments-group__thumb comments-group__thumb--empty" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                          <rect x="3" y="3" width="18" height="18" rx="2" />
                          <circle cx="8.5" cy="8.5" r="1.5" fill="currentColor" stroke="none" />
                          <path d="M21 15l-5-5L5 21" />
                        </svg>
                      </span>
                    )}
                    <span className="comments-group__file">
                      {first.media_file_name ?? "Photo no longer available"}
                    </span>
                    {notes.length > 1 && (
                      <span className="comments-group__count">
                        {notes.length} notes
                      </span>
                    )}
                  </div>

                  <ul className="comments-group__notes">
                    {notes.map((note) => (
                      <li key={note.id} className={`admin-comment admin-comment--${note.status}`}>
                        <div className="admin-comment__meta">
                          <span className={`comment-status comment-status--${note.status}`}>
                            {note.status === "open" ? "Open" : "Resolved"}
                          </span>
                          <time dateTime={note.created_at}>{new Date(note.created_at).toLocaleString()}</time>
                          {note.updated_at !== note.created_at && (
                            <span className="admin-comment__edited">
                              edited {new Date(note.updated_at).toLocaleString()}
                            </span>
                          )}
                        </div>

                        <p className="admin-comment__text">{note.comment}</p>

                        <div className="admin-comment__actions">
                          <button
                            type="button"
                            className="btn-text"
                            onClick={() => toggleStatus(note)}
                            disabled={busyId === note.id}
                          >
                            {note.status === "open" ? "Mark resolved" : "Reopen"}
                          </button>
                          <button
                            type="button"
                            className="btn-text btn-text--danger"
                            onClick={() => remove(note)}
                            disabled={busyId === note.id}
                          >
                            Delete
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                </li>
              );
            })}
          </ul>
        )}

        {actionError && (
          <p className="comments-action-error" role="alert">
            {actionError}
          </p>
        )}
      </div>
    </Modal>
  );
}
