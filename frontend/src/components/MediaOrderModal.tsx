import { useEffect, useRef, useState } from "react";
import Modal from "./Modal";
import { adminService, MediaItem } from "../services/admin";

const PAGE_LIMIT = 200;
// Same ceiling Book View uses: far above a real album, low enough that a
// pathological one can't freeze the browser while loading the order screen.
const HARD_CAP = 2000;

interface MediaOrderModalProps {
  albumId: number;
  albumName: string;
  onClose: () => void;
  onSaved: () => void;
}

/**
 * Drag-and-drop book order for one album. The whole album is loaded (the
 * reorder endpoint requires the complete list), shown in the order clients
 * read it, then saved in one request. Up/down buttons are the touch and
 * keyboard path; native drag & drop is the fast path on desktop.
 */
export default function MediaOrderModal({ albumId, albumName, onClose, onSaved }: MediaOrderModalProps) {
  const [items, setItems] = useState<MediaItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const dragFrom = useRef<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setLoadError(null);
      try {
        const collected: MediaItem[] = [];
        let page = 1;
        for (;;) {
          const res = await adminService.listAlbumMedia(albumId, page, PAGE_LIMIT);
          collected.push(...res.items);
          if (!res.has_more) break;
          if (collected.length >= HARD_CAP) {
            if (!cancelled) setTruncated(true);
            break;
          }
          page += 1;
        }
        if (cancelled) return;
        collected.sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);
        setItems(collected);
      } catch (err) {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : "Could not load this album's photos.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [albumId]);

  function move(from: number, to: number) {
    if (to < 0 || to >= items.length || from === to) return;
    setItems((prev) => {
      const next = [...prev];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
    setDirty(true);
    setSaveError(null);
  }

  function handleDrop(to: number) {
    if (dragFrom.current !== null) move(dragFrom.current, to);
    dragFrom.current = null;
    setOverIndex(null);
  }

  function requestClose() {
    if (saving) return;
    if (dirty && !window.confirm("Discard your unsaved order changes?")) return;
    onClose();
  }

  async function save() {
    if (saving || items.length === 0) return;
    setSaving(true);
    setSaveError(null);
    try {
      await adminService.reorderAlbumMedia(
        albumId,
        items.map((item) => item.id)
      );
      onSaved();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Could not save the new order.");
      setSaving(false);
    }
  }

  const description = truncated
    ? `This album has more than ${HARD_CAP} items, so its order can't be changed here.`
    : "Drag photos into the order they should appear in the book. Page notes follow their photo.";

  return (
    <Modal title={`Reorder · ${albumName}`} description={description} onClose={requestClose} className="media-order-modal">
      <div className="media-order">
        {loading && <p className="media-order__status">Loading photos…</p>}

        {!loading && loadError && (
          <div className="media-order__status">
            <p>{loadError}</p>
          </div>
        )}

        {!loading && !loadError && items.length === 0 && (
          <p className="media-order__status">This album has no photos to reorder yet.</p>
        )}

        {!loading && !loadError && items.length > 0 && (
          <ol className="media-order__list" aria-label="Book order">
            {items.map((item, index) => (
              <li
                key={item.id}
                className={
                  "media-order__row" +
                  (overIndex === index && dragFrom.current !== null && dragFrom.current !== index ? " is-drop-target" : "") +
                  (dragFrom.current === index ? " is-dragging" : "")
                }
                draggable={!truncated && !saving}
                onDragStart={() => {
                  dragFrom.current = index;
                  // Repaint so the row picks up is-dragging immediately;
                  // refs alone don't trigger a render.
                  setOverIndex(index);
                }}
                onDragOver={(e) => {
                  if (dragFrom.current === null) return;
                  e.preventDefault();
                  setOverIndex(index);
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  handleDrop(index);
                }}
                onDragEnd={() => {
                  dragFrom.current = null;
                  setOverIndex(null);
                }}
              >
                <span className="media-order__handle" aria-hidden="true">
                  <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor">
                    <circle cx="5" cy="3.5" r="1.2" />
                    <circle cx="11" cy="3.5" r="1.2" />
                    <circle cx="5" cy="8" r="1.2" />
                    <circle cx="11" cy="8" r="1.2" />
                    <circle cx="5" cy="12.5" r="1.2" />
                    <circle cx="11" cy="12.5" r="1.2" />
                  </svg>
                </span>

                <span className="media-order__page">Page {index + 1}</span>

                {item.has_thumbnail ? (
                  <img
                    className="media-order__thumb"
                    src={adminService.adminThumbnailUrl(item.id)}
                    alt=""
                    loading="lazy"
                  />
                ) : (
                  <span className="media-order__thumb media-order__thumb--empty" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                      <rect x="3" y="3" width="18" height="18" rx="2" />
                      <circle cx="8.5" cy="8.5" r="1.5" fill="currentColor" stroke="none" />
                      <path d="M21 15l-5-5L5 21" />
                    </svg>
                  </span>
                )}

                <span className="media-order__name" title={item.file_name}>
                  {item.file_name}
                </span>

                <span className="media-order__type">{item.file_type === "video" ? "Video" : "Photo"}</span>

                <span className="media-order__controls">
                  <button
                    type="button"
                    className="media-order__move"
                    aria-label={`Move ${item.file_name} earlier`}
                    title="Move earlier"
                    disabled={index === 0 || saving || truncated}
                    onClick={() => move(index, index - 1)}
                  >
                    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M4 10l4-4 4 4" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    className="media-order__move"
                    aria-label={`Move ${item.file_name} later`}
                    title="Move later"
                    disabled={index === items.length - 1 || saving || truncated}
                    onClick={() => move(index, index + 1)}
                  >
                    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                </span>
              </li>
            ))}
          </ol>
        )}

        {saveError && (
          <p className="media-order__error" role="alert">
            {saveError}
          </p>
        )}

        <div className="modal-actions">
          <button type="button" className="btn-secondary" onClick={requestClose} disabled={saving}>
            Cancel
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={save}
            disabled={saving || loading || !!loadError || items.length === 0 || !dirty || truncated}
          >
            {saving ? "Saving…" : "Save order"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
