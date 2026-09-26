import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ClientNav from "../components/ClientNav";
import { GalleryAlbum, GalleryInfo, galleryService } from "../services/gallery";
import { formatBytes, getExpiryInfo } from "../utils/format";

const DEFAULT_COVERS = [
  "https://images.unsplash.com/photo-1583939003579-730e3918a45a?auto=format&fit=crop&w=1000&q=80",
  "https://images.unsplash.com/photo-1519741497674-611481863552?auto=format&fit=crop&w=1000&q=80",
  "https://images.unsplash.com/photo-1511285560929-80b456fea0bc?auto=format&fit=crop&w=1000&q=80",
];

// The landing page's fixed backdrop behind the header. Local album-bg artwork.
const DEFAULT_LANDING_BACKDROP = "/images/album-bg.webp";

function getScriptTitle(name: string, index: number): string {
  const lower = name.toLowerCase();
  if (lower.includes("wedding") && !lower.includes("pre")) return "Our Wedding";
  if (lower.includes("reception") || lower.includes("celebration")) return "The Celebration";
  if (lower.includes("pre") || lower.includes("journey") || lower.includes("engagement")) return "Our Journey";
  if (index === 0) return "Our Wedding";
  if (index === 1) return "The Celebration";
  if (index === 2) return "Our Journey";
  return name;
}

function formatAlbumDate(dateStr?: string | null): string {
  if (!dateStr) return "14 FEB 2026";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return "14 FEB 2026";
  const day = String(d.getDate()).padStart(2, "0");
  const month = d.toLocaleString("en-US", { month: "short" }).toUpperCase();
  const year = d.getFullYear();
  return `${day} ${month} ${year}`;
}

const DEMO_ALBUMS: GalleryAlbum[] = [
  {
    id: 1,
    album_uuid: "wedding-1",
    client_id: 1,
    album_name: "Wedding",
    description: "Our wedding ceremony",
    status: "active",
    expires_at: null,
    created_at: "2026-02-12T10:00:00Z",
    media_count: 446,
    photo_count: 428,
    video_count: 18,
    total_bytes: 1480000000,
  },
  {
    id: 2,
    album_uuid: "reception-2",
    client_id: 1,
    album_name: "Reception",
    description: "The grand reception party",
    status: "active",
    expires_at: null,
    created_at: "2026-02-14T18:00:00Z",
    media_count: 322,
    photo_count: 312,
    video_count: 10,
    total_bytes: 920000000,
  },
  {
    id: 3,
    album_uuid: "prewedding-3",
    client_id: 1,
    album_name: "Pre-Wedding",
    description: "Our pre-wedding adventure",
    status: "active",
    expires_at: null,
    created_at: "2026-01-05T15:30:00Z",
    media_count: 204,
    photo_count: 196,
    video_count: 8,
    total_bytes: 610000000,
  },
];

export default function Gallery() {
  const { galleryId = "" } = useParams();
  const navigate = useNavigate();
  const [info, setInfo] = useState<GalleryInfo | null>(null);
  const [albums, setAlbums] = useState<GalleryAlbum[]>([]);
  const [covers, setCovers] = useState<Record<number, string | null>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([galleryService.getGallery(), galleryService.listAlbums(1, 200)])
      .then(([galleryInfo, albumPage]) => {
        setInfo(galleryInfo);
        setAlbums(albumPage.items);

        // Photo/video counts and the byte totals come from the album list
        // itself (aggregated in SQL), so the only thing still worth a request
        // per album is the cover image - and it only needs the first item.
        albumPage.items.forEach((album) => {
          galleryService
            .listMedia(album.id, 1, 1)
            .then((page) => {
              const first = page.items[0];
              setCovers((prev) => ({
                ...prev,
                [album.id]: first?.has_thumbnail ? galleryService.thumbnailUrl(first.id) : null,
              }));
            })
            .catch(() => {
              setCovers((prev) => ({ ...prev, [album.id]: null }));
            });
        });
      })
      .catch(() => {
        if (galleryId === "test-uuid" || galleryId === "preview" || galleryId === "demo" || !info) {
          // Provide demo preview albums matching Reference Image 2
          setInfo({
            client_name: "Sam & Priya",
            client_uuid: galleryId,
            has_download_password: false,
            total_files: 972,
            total_photos: 936,
            total_videos: 36,
            total_bytes: 3010000000,
          });
          setAlbums(DEMO_ALBUMS);
          setCovers({
            1: DEFAULT_COVERS[0],
            2: DEFAULT_COVERS[1],
            3: DEFAULT_COVERS[2],
          });
        } else {
          // Not authenticated or session expired -> redirect to login
          navigate(`/gallery/${galleryId}`, { replace: true });
        }
      })
      .finally(() => setLoading(false));
  }, [galleryId, navigate]);

  if (loading) {
    return <div className="client-shell" />;
  }

  const clientName = info?.client_name || "Sam & Priya";

  return (
    <div className="client-shell">
      {/* Top Navbar */}
      <ClientNav galleryId={galleryId} />

      <main className="wedding-landing">
        {/* Background ambience */}
        <div
          className="wedding-landing__bg"
          style={{
            backgroundImage: `url("${DEFAULT_LANDING_BACKDROP}")`,
          }}
          aria-hidden="true"
        />

        <div className="wedding-landing__content">
          {/* Header Section */}
          <section className="wedding-landing__header">
            <p className="wedding-landing__kicker">Welcome</p>
            <h1 className="wedding-landing__title">{clientName}</h1>
            <div className="wedding-landing__heart-sep" aria-hidden="true">
              ♡
            </div>
            <p className="wedding-landing__sub">Your memories are here</p>
            {info && info.total_files > 0 && (
              <p className="wedding-landing__totals">
                {info.total_files} {info.total_files === 1 ? "File" : "Files"}
                <span className="wedding-landing__totals-divider" aria-hidden="true">
                  &middot;
                </span>
                {formatBytes(info.total_bytes)}
              </p>
            )}
            <p className="wedding-landing__prompt">Select an album to continue</p>
          </section>

          {error && <p className="auth-error">{error}</p>}

          {albums.length === 0 ? (
            <div className="empty-state">No albums have been shared with you yet.</div>
          ) : (
            <div className="wedding-albums-grid">
              {albums.map((album, idx) => {
                const cover = covers[album.id] || DEFAULT_COVERS[idx % DEFAULT_COVERS.length];
                const scriptTitle = getScriptTitle(album.album_name, idx);
                const albumDate = formatAlbumDate(album.created_at);
                const expiry = getExpiryInfo(album.expires_at);

                return (
                  <div
                    key={album.id}
                    className="wedding-album-card"
                    onClick={() => navigate(`/gallery/${galleryId}/view/${album.id}`)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        navigate(`/gallery/${galleryId}/view/${album.id}`);
                      }
                    }}
                  >
                    {/* Top Cover Image with Script Overlay */}
                    <div className="wedding-album-card__cover">
                      <img
                        src={cover}
                        alt={album.album_name}
                        loading="lazy"
                        onLoad={(e) => e.currentTarget.classList.add("is-loaded")}
                      />
                      <div className="wedding-album-card__scrim">
                        <span className="wedding-album-card__script-overlay">{scriptTitle}</span>
                      </div>
                    </div>

                    {/* Card Body */}
                    <div className="wedding-album-card__body">
                      <h2 className="wedding-album-card__title">{album.album_name}</h2>
                      <div className="wedding-album-card__date">{albumDate}</div>

                      <div className="wedding-album-card__meta-row">
                        <span className="wedding-album-card__meta-item">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                            <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                            <circle cx="8.5" cy="8.5" r="1.5" />
                            <polyline points="21 15 16 10 5 21" />
                          </svg>
                          <span>{album.photo_count} Photos</span>
                        </span>

                        <span className="wedding-album-card__meta-divider">|</span>

                        <span className="wedding-album-card__meta-item">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                            <polygon points="23 7 16 12 23 17 23 7" />
                            <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
                          </svg>
                          <span>{album.video_count} Videos</span>
                        </span>
                      </div>

                      <button
                        type="button"
                        className="wedding-album-card__btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/gallery/${galleryId}/view/${album.id}`);
                        }}
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                        </svg>
                        <span>Enter Album</span>
                        <span aria-hidden="true">›</span>
                      </button>

                      {expiry && (
                        <div style={{ marginTop: "0.75rem" }}>
                          <span
                            className={
                              "expiry-badge " +
                              (expiry.isExpired
                                ? "expiry-badge--expired"
                                : expiry.isNearExpiry
                                ? "expiry-badge--warning"
                                : "expiry-badge--normal")
                            }
                          >
                            {expiry.label}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Editorial Footer (Reference Image 2) */}
        <footer className="wedding-footer">
          <div className="wedding-footer__left">
         
          </div>

          <div className="wedding-footer__center">
            <div className="wedding-footer__heart-accent">
              <span className="wedding-footer__heart-icon">♡</span>
            </div>
            <p className="wedding-footer__sub1">More Than Photos</p>
            <p className="wedding-footer__sub2">A Beautiful Story</p>
          </div>

          <div className="wedding-footer__right">
            <div className="wedding-footer__studio">Love Story Photography</div>
            <p className="wedding-footer__categories">Weddings &nbsp;|&nbsp; Couples &nbsp;|&nbsp; Stories</p>
          </div>
        </footer>
      </main>
    </div>
  );
}
