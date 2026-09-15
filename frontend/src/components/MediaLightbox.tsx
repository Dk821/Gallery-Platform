import { ReactNode, useEffect, useRef, useState } from "react";

export interface LightboxItem {
  id: number;
  file_name: string;
  file_type: "photo" | "video";
}

interface MediaLightboxProps<T extends LightboxItem> {
  items: T[];
  startIndex: number;
  onClose: () => void;
  viewUrl: (id: number) => string;
  downloadUrl: (id: number) => string;
  // The filmstrip's small preview strip. Optional and falls back to
  // viewUrl - but for a video item, viewUrl streams the raw video file,
  // which an <img> can't render at all, so the filmstrip preview for
  // every video is effectively missing/broken unless the caller passes
  // the actual thumbnail/poster endpoint here.
  thumbnailUrl?: (id: number) => string;
  onDownload?: (item: T) => void;
  renderActions?: (item: T, index: number) => ReactNode;
}

export default function MediaLightbox<T extends LightboxItem>({
  items,
  startIndex,
  onClose,
  viewUrl,
  downloadUrl,
  thumbnailUrl,
  onDownload,
  renderActions,
}: MediaLightboxProps<T>) {
  const filmstripThumbnailUrl = thumbnailUrl ?? viewUrl;
  const [index, setIndex] = useState(startIndex);
  const [zoomed, setZoomed] = useState(false);
  const current = items[index];
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const filmstripRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setZoomed(false);
  }, [index]);

  useEffect(() => {
    closeButtonRef.current?.focus();
  }, []);

  useEffect(() => {
    if (index > items.length - 1) {
      setIndex(Math.max(items.length - 1, 0));
    }
  }, [items.length, index]);

  // Scroll active thumbnail into view in filmstrip
  useEffect(() => {
    if (filmstripRef.current) {
      const activeEl = filmstripRef.current.children[index] as HTMLElement;
      if (activeEl) {
        activeEl.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
      }
    }
  }, [index]);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") setIndex((i) => Math.min(i + 1, items.length - 1));
      if (e.key === "ArrowLeft") setIndex((i) => Math.max(i - 1, 0));
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [items.length, onClose]);

  if (!current) return null;

  return (
    <div
      className="lightbox-overlay"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={current.file_name}
    >
      {/* Top Bar */}
      <div className="lightbox-topbar" onClick={(e) => e.stopPropagation()}>
        <div className="lightbox-topbar__left">
          <span className="lightbox-counter-badge">
            {index + 1} / {items.length}
          </span>
          <span className="lightbox-topbar__name" title={current.file_name}>
            {current.file_name}
          </span>
        </div>

        <div className="lightbox-topbar__actions">
          {current.file_type === "photo" && (
            <button
              type="button"
              className="lightbox-icon-btn"
              onClick={() => setZoomed((z) => !z)}
              title={zoomed ? "Reset zoom" : "Zoom in"}
              aria-label={zoomed ? "Reset zoom" : "Zoom in"}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
                <line x1={zoomed ? "8" : "11"} y1="11" x2={zoomed ? "14" : "11"} y2="11" />
                {!zoomed && <line x1="11" y1="8" x2="11" y2="14 motion" />}
              </svg>
              <span>{zoomed ? "180%" : "Zoom"}</span>
            </button>
          )}

          {onDownload ? (
            <button
              type="button"
              className="lightbox-icon-btn lightbox-icon-btn--primary"
              onClick={() => onDownload(current)}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              <span>Download</span>
            </button>
          ) : (
            <a
              className="lightbox-icon-btn lightbox-icon-btn--primary"
              href={downloadUrl(current.id)}
              download
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              <span>Download</span>
            </a>
          )}

          {renderActions && renderActions(current, index)}

          <button
            ref={closeButtonRef}
            className="lightbox-icon-btn lightbox-icon-btn--close"
            onClick={onClose}
            aria-label="Close preview"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      {/* Main Viewing Stage */}
      <div className="lightbox-stage" onClick={(e) => e.stopPropagation()}>
        {index > 0 && (
          <button
            type="button"
            className="lightbox-nav lightbox-nav--prev"
            onClick={() => setIndex((i) => Math.max(i - 1, 0))}
            aria-label="Previous media item"
          >
            ‹
          </button>
        )}

        <div className="lightbox-media-wrapper">
          {current.file_type === "photo" ? (
            <img
              key={current.id}
              src={viewUrl(current.id)}
              alt={current.file_name}
              className={zoomed ? "zoomed" : ""}
              onClick={() => setZoomed((z) => !z)}
            />
          ) : (
            <video key={current.id} src={viewUrl(current.id)} controls autoPlay />
          )}
        </div>

        {index < items.length - 1 && (
          <button
            type="button"
            className="lightbox-nav lightbox-nav--next"
            onClick={() => setIndex((i) => Math.min(i + 1, items.length - 1))}
            aria-label="Next media item"
          >
            ›
          </button>
        )}
      </div>

      {/* Bottom Filmstrip Preview Carousel */}
      <div className="lightbox-filmstrip-bar" onClick={(e) => e.stopPropagation()}>
        <div className="lightbox-filmstrip" ref={filmstripRef}>
          {items.map((item, i) => (
            <button
              key={item.id}
              type="button"
              className={"lightbox-filmstrip-item" + (i === index ? " lightbox-filmstrip-item--active" : "")}
              onClick={() => setIndex(i)}
              aria-label={`Preview ${item.file_name}`}
            >
              <img src={filmstripThumbnailUrl(item.id)} alt={item.file_name} loading="lazy" />
              {item.file_type === "video" && (
                <span className="lightbox-filmstrip-video-icon">▶</span>
              )}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
