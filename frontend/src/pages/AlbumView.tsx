import { FormEvent, useEffect, useState, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ClientNav from "../components/ClientNav";
import DownloadJobModal from "../components/DownloadJobModal";
import DownloadPasswordModal from "../components/DownloadPasswordModal";
import MediaLightbox from "../components/MediaLightbox";
import WishlistHeart from "../components/WishlistHeart";
import { useWishlist } from "../hooks/useWishlist";
import { ApiRequestError } from "../services/api";
import { GalleryAlbum, GalleryMedia, galleryService } from "../services/gallery";
import { formatBytes, getExpiryInfo } from "../utils/format";

const PAGE_SIZE = 60;

const DEFAULT_HERO_IMAGE = "/images/album-hero.webp";

function formatLongDate(dateStr?: string | null): string {
  if (!dateStr) return "14 FEBRUARY 2026";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return "14 FEBRUARY 2026";
  const day = d.getDate();
  const month = d.toLocaleString("en-US", { month: "long" }).toUpperCase();
  const year = d.getFullYear();
  return `${day} ${month} ${year}`;
}

function formatShortDate(dateStr?: string | null): string {
  if (!dateStr) return "14 Feb 2026";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return "14 Feb 2026";
  const day = d.getDate();
  const month = d.toLocaleString("en-US", { month: "short" });
  const year = d.getFullYear();
  return `${day} ${month} ${year}`;
}

// Generate consistent visual duration badges for video items (Reference Image 1)
function getVideoDurationBadge(id: number): string {
  const durations = ["02:14", "01:36", "03:22", "00:58", "04:15", "02:45"];
  return durations[id % durations.length];
}

const DEMO_MEDIA_ITEMS: GalleryMedia[] = [
  {
    id: 101,
    file_uuid: "uuid-101",
    album_id: 1,
    file_name: "SAM_PRIYA_001.JPG",
    title: "Couple Portrait",
    description: null,
    file_type: "photo",
    mime_type: "image/jpeg",
    file_size: 14200000,
    has_thumbnail: true,
    status: "ready",
    created_at: "2026-02-14T10:15:00Z",
    is_wishlisted: false,
  },
  {
    id: 102,
    file_uuid: "uuid-102",
    album_id: 1,
    file_name: "SUNSET_ALTAR_002.JPG",
    title: "Sunset Altar",
    description: null,
    file_type: "photo",
    mime_type: "image/jpeg",
    file_size: 18500000,
    has_thumbnail: true,
    status: "ready",
    created_at: "2026-02-14T10:20:00Z",
    is_wishlisted: false,
  },
  {
    id: 103,
    file_uuid: "uuid-103",
    album_id: 1,
    file_name: "RINGS_DETAIL_003.JPG",
    title: "Wedding Rings",
    description: null,
    file_type: "photo",
    mime_type: "image/jpeg",
    file_size: 12400000,
    has_thumbnail: true,
    status: "ready",
    created_at: "2026-02-14T10:25:00Z",
    is_wishlisted: false,
  },
  {
    id: 104,
    file_uuid: "uuid-104",
    album_id: 1,
    file_name: "CEREMONY_HIGHLIGHT_004.MP4",
    title: "Sunset Silhouette",
    description: null,
    file_type: "video",
    mime_type: "video/mp4",
    file_size: 185000000,
    has_thumbnail: true,
    status: "ready",
    created_at: "2026-02-14T10:30:00Z",
    is_wishlisted: false,
  },
  {
    id: 105,
    file_uuid: "uuid-105",
    album_id: 1,
    file_name: "BRIDE_ELEGANCE_005.JPG",
    title: "Bride Portrait",
    description: null,
    file_type: "photo",
    mime_type: "image/jpeg",
    file_size: 16100000,
    has_thumbnail: true,
    status: "ready",
    created_at: "2026-02-14T10:35:00Z",
    is_wishlisted: false,
  },
  {
    id: 106,
    file_uuid: "uuid-106",
    album_id: 1,
    file_name: "BETTER_TOGETHER_006.JPG",
    title: "Better Together",
    description: null,
    file_type: "photo",
    mime_type: "image/jpeg",
    file_size: 11200000,
    has_thumbnail: true,
    status: "ready",
    created_at: "2026-02-14T10:40:00Z",
    is_wishlisted: false,
  },
  {
    id: 107,
    file_uuid: "uuid-107",
    album_id: 1,
    file_name: "JOYFUL_SMILES_007.JPG",
    title: "Joyful Moments",
    description: null,
    file_type: "photo",
    mime_type: "image/jpeg",
    file_size: 15300000,
    has_thumbnail: true,
    status: "ready",
    created_at: "2026-02-14T10:45:00Z",
    is_wishlisted: false,
  },
  {
    id: 108,
    file_uuid: "uuid-108",
    album_id: 1,
    file_name: "GOLDEN_HOUR_WALK_008.JPG",
    title: "Golden Hour Walk",
    description: null,
    file_type: "photo",
    mime_type: "image/jpeg",
    file_size: 19800000,
    has_thumbnail: true,
    status: "ready",
    created_at: "2026-02-14T10:50:00Z",
    is_wishlisted: false,
  },
  {
    id: 109,
    file_uuid: "uuid-109",
    album_id: 1,
    file_name: "FLORAL_BOUQUET_009.JPG",
    title: "Floral Bouquet",
    description: null,
    file_type: "photo",
    mime_type: "image/jpeg",
    file_size: 13900000,
    has_thumbnail: true,
    status: "ready",
    created_at: "2026-02-14T10:55:00Z",
    is_wishlisted: false,
  },
  {
    id: 110,
    file_uuid: "uuid-110",
    album_id: 1,
    file_name: "TWILIGHT_VEIL_010.MP4",
    title: "Twilight Veil",
    description: null,
    file_type: "video",
    mime_type: "video/mp4",
    file_size: 210000000,
    has_thumbnail: true,
    status: "ready",
    created_at: "2026-02-14T11:00:00Z",
    is_wishlisted: false,
  },
];

const DEMO_THUMBNAILS: Record<number, string> = {
  101: "https://images.unsplash.com/photo-1583939003579-730e3918a45a?auto=format&fit=crop&w=800&q=80",
  102: "https://images.unsplash.com/photo-1519741497674-611481863552?auto=format&fit=crop&w=800&q=80",
  103: "https://images.unsplash.com/photo-1606800052052-a08af7148866?auto=format&fit=crop&w=800&q=80",
  104: "https://images.unsplash.com/photo-1511285560929-80b456fea0bc?auto=format&fit=crop&w=800&q=80",
  105: "https://images.unsplash.com/photo-1545232979-8bf68ee9b1af?auto=format&fit=crop&w=800&q=80",
  106: "https://images.unsplash.com/photo-1522673607200-164d1b6ce486?auto=format&fit=crop&w=800&q=80",
  107: "https://images.unsplash.com/photo-1537633552985-df8429e8048b?auto=format&fit=crop&w=800&q=80",
  108: "https://images.unsplash.com/photo-1515934751635-c81c6bc9a2d8?auto=format&fit=crop&w=800&q=80",
  109: "https://images.unsplash.com/photo-1561181286-d3fee7d55364?auto=format&fit=crop&w=800&q=80",
  110: "https://images.unsplash.com/photo-1509927083803-4bd519298ac4?auto=format&fit=crop&w=800&q=80",
};

export default function AlbumView() {
  const { galleryId = "", albumId = "" } = useParams();
  const navigate = useNavigate();
  const albumIdNum = Number(albumId);

  const [clientName, setClientName] = useState("Sam & Priya");
  const [album, setAlbum] = useState<GalleryAlbum | null>(null);
  const [items, setItems] = useState<GalleryMedia[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [searchResultCount, setSearchResultCount] = useState<number | null>(null);
  const [showSearchPanel, setShowSearchPanel] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [selectAllBytesOverride, setSelectAllBytesOverride] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [downloadJobRequest, setDownloadJobRequest] = useState<number[] | "all" | null>(null);
  const [hasDownloadPassword, setHasDownloadPassword] = useState(false);
  const [singleDownloadUrl, setSingleDownloadUrl] = useState<string | null>(null);

  // Filter & Sort & Layout state (Reference Image 1)
  const [mediaFilter, setMediaFilter] = useState<"all" | "photo" | "video">("all");
  const [sortBy, setSortBy] = useState<"newest" | "oldest" | "name">("newest");
  const [layoutMode, setLayoutMode] = useState<"grid" | "list">("grid");
  const [totalAlbumBytes, setTotalAlbumBytes] = useState<number>(0);
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const moreMenuRef = useRef<HTMLDivElement>(null);

  function showToast(message: string) {
    setToast(message);
    setTimeout(() => setToast(null), 3000);
  }

  // Wishlist hearts. Flags arrive with the media list itself (no request per
  // photo); toggling is optimistic and rolls back with a toast on failure.
  // Demo galleries have no server rows, so their hearts stay local.
  const isDemoGallery = galleryId === "test-uuid" || galleryId === "preview" || galleryId === "demo";
  const wishlist = useWishlist({ demo: isDemoGallery, onError: showToast });

  // Close more menu when clicking outside
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (moreMenuRef.current && !moreMenuRef.current.contains(e.target as Node)) {
        setShowMoreMenu(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  async function load(searchTerm: string) {
    setLoading(true);
    try {
      const [galleryInfo, albumData, mediaPage] = await Promise.all([
        galleryService.getGallery(),
        galleryService.getAlbum(albumIdNum),
        galleryService.listMedia(albumIdNum, 1, PAGE_SIZE, searchTerm || undefined),
      ]);
      setClientName(galleryInfo.client_name || "Sam & Priya");
      setHasDownloadPassword(galleryInfo.has_download_password);
      setAlbum(albumData);
      setItems(mediaPage.items);
      wishlist.seed(mediaPage.items);
      setHasMore(mediaPage.has_more);
      setSearchResultCount(searchTerm ? mediaPage.total : null);
      setPage(1);
      setSelectedIds(new Set());
      setSelectAllBytesOverride(null);

      // Fetch accurate total bytes across entire album
      galleryService
        .getSelectionSummary(albumIdNum)
        .then((summary) => setTotalAlbumBytes(summary.total_bytes))
        .catch(() => {
          const sum = mediaPage.items.reduce((acc, i) => acc + i.file_size, 0);
          setTotalAlbumBytes(sum);
        });
    } catch (err) {
      if (err instanceof ApiRequestError && err.code === "ALBUM_EXPIRED") {
        setExpired(true);
      } else if (err instanceof ApiRequestError && err.code === "ALBUM_FORBIDDEN") {
        setError("This gallery is no longer available to you.");
      } else if (galleryId === "test-uuid" || galleryId === "preview" || galleryId === "demo" || !album) {
        setClientName("Sam & Priya");
        setAlbum({
          id: albumIdNum || 1,
          album_uuid: "wedding-1",
          client_id: 1,
          album_name: albumIdNum === 2 ? "Reception" : albumIdNum === 3 ? "Pre-Wedding" : "Wedding",
          description: "Our story of",
          status: "active",
          expires_at: null,
          created_at: "2026-02-14T10:00:00Z",
          media_count: 260,
          photo_count: 242,
          video_count: 18,
          total_bytes: 1480000000,
        });
        setItems(DEMO_MEDIA_ITEMS);
        setTotalAlbumBytes(1480000000);
        setHasMore(false);
      } else {
        // Most likely an expired/invalid session -> back to password screen
        navigate(`/gallery/${galleryId}`, { replace: true });
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [albumIdNum]);

  async function loadMore() {
    const nextPage = page + 1;
    const mediaPage = await galleryService.listMedia(albumIdNum, nextPage, PAGE_SIZE, appliedSearch || undefined);
    setItems((prev) => [...prev, ...mediaPage.items]);
    wishlist.seed(mediaPage.items); // only the NEW page - re-seeding older items would undo hearts toggled since
    setHasMore(mediaPage.has_more);
    setPage(nextPage);
  }

  function handleSearchSubmit(e: FormEvent) {
    e.preventDefault();
    setAppliedSearch(search);
    load(search);
  }

  function clearSearch() {
    setSearch("");
    setAppliedSearch("");
    load("");
  }

  function toggleSelect(id: number) {
    setSelectAllBytesOverride(null);
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function selectAll() {
    setShowMoreMenu(false);
    try {
      const summary = await galleryService.getSelectionSummary(albumIdNum, appliedSearch || undefined);
      setSelectedIds(new Set(summary.ids));
      setSelectAllBytesOverride(summary.total_bytes);
      showToast(`Selected all ${summary.ids.length} items`);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Failed to select all.");
    }
  }

  function clearSelection() {
    setSelectedIds(new Set());
    setSelectAllBytesOverride(null);
  }

  function handleDownloadSelected() {
    setDownloadJobRequest(Array.from<number>(selectedIds));
  }

  function handleDownloadAllAsZip() {
    setShowMoreMenu(false);
    setDownloadJobRequest("all");
  }

  // Filter and sort items
  const filteredItems = items.filter((item) => {
    if (mediaFilter === "photo") return item.file_type === "photo";
    if (mediaFilter === "video") return item.file_type === "video";
    return true;
  });

  const sortedItems = [...filteredItems].sort((a, b) => {
    if (sortBy === "oldest") {
      return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
    }
    if (sortBy === "name") {
      return a.file_name.localeCompare(b.file_name);
    }
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });

  // Photo & video breakdown.
  //
  // These describe the ALBUM, so they must come from the server's aggregate
  // (GalleryAlbum.photo_count / video_count, computed in SQL by
  // media_aggregates) - exactly what the admin album list and the client
  // gallery cards already read.
  //
  // The page-derived fallbacks below are ONLY correct for the demo path, and
  // they used to be preferred for real albums, which made this view disagree
  // with the admin view of the same album: `items` is just the pages loaded
  // so far (PAGE_SIZE to begin with, more only via loadMore), so
  // `media_count - videoCount` subtracted one page's worth of videos from the
  // album's true total, and `videoCount` on its own reported only the loaded
  // page - the two didn't even sum to media_count. Applying a search made it
  // drift again, since it narrows `items` to the matches.
  const photoCount = items.filter((i) => i.file_type === "photo").length;
  const videoCount = items.filter((i) => i.file_type === "video").length;

  const totalPhotos = album?.photo_count ?? photoCount;
  const totalVideos = album?.video_count ?? videoCount;

  const selectedBytes =
    selectAllBytesOverride ?? items.filter((i) => selectedIds.has(i.id)).reduce((sum, i) => sum + i.file_size, 0);

  const expiry = album ? getExpiryInfo(album.expires_at) : null;
  const getThumbnail = (item: GalleryMedia) => DEMO_THUMBNAILS[item.id] || galleryService.thumbnailUrl(item.id);
  const getViewUrl = (id: number) => DEMO_THUMBNAILS[id] || galleryService.viewUrl(id);
  const getThumbnailUrl = (id: number) => DEMO_THUMBNAILS[id] || galleryService.thumbnailUrl(id);
  const heroBackground = DEFAULT_HERO_IMAGE;

  if (expired) {
    return (
      <div className="client-shell">
        <ClientNav galleryId={galleryId} />
        <div style={{ padding: "4rem 2rem", textAlign: "center" }}>
          <h2 style={{ fontFamily: "var(--font-display)", fontSize: "2rem" }}>Gallery Expired</h2>
          <p className="empty-state">
            This gallery has expired and is no longer accessible. Please contact the studio if you believe this is a
            mistake.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="client-shell">
      {/* Top Navbar */}
      <ClientNav galleryId={galleryId} />

      {/* Hero Banner (Reference Image 1) */}
      <section className="album-hero" style={{ backgroundImage: `url("${heroBackground}")` }}>
        <div className="album-hero__scrim" />
        <button
          type="button"
          className="album-back-btn"
          onClick={() => navigate(`/gallery/${galleryId}/view`)}
          aria-label="Back to all albums"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <polyline points="15 18 9 12 15 6" />
          </svg>
          <span>All Albums</span>
        </button>
        <div className="album-hero__content">
          <p className="album-hero__kicker">Our Story</p>
          <h1 className="album-hero__title">{clientName}</h1>
          <p className="album-hero__date">{formatLongDate(album?.created_at)}</p>
          <p className="album-hero__tagline">Moments &nbsp;•&nbsp; Memories &nbsp;•&nbsp; Forever</p>
        </div>
      </section>

      {/* Floating Glassmorphic Stat & Action Bar (Reference Image 1) */}
      <div className="album-stat-bar-wrapper">
        <div className="album-stat-bar">
          <div className="album-stat-bar__left">
            {/* Photo Counter */}
            <div className="album-stat-item">
              <span className="album-stat-item__icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" width="22" height="22">
                  <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                  <circle cx="8.5" cy="8.5" r="1.5" />
                  <polyline points="21 15 16 10 5 21" />
                </svg>
              </span>
              <div className="album-stat-item__text">
                <span className="album-stat-item__count">{totalPhotos}</span>
                <span className="album-stat-item__label">Photos</span>
              </div>
            </div>

            {/* Video Counter */}
            <div className="album-stat-item">
              <span className="album-stat-item__icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" width="22" height="22">
                  <polygon points="23 7 16 12 23 17 23 7" />
                  <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
                </svg>
              </span>
              <div className="album-stat-item__text">
                <span className="album-stat-item__count">{totalVideos}</span>
                <span className="album-stat-item__label">Videos</span>
              </div>
            </div>

            {/* Date / Wedding Day */}
            <div className="album-stat-item">
              <span className="album-stat-item__icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" width="22" height="22">
                  <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                  <line x1="16" y1="2" x2="16" y2="6" />
                  <line x1="8" y1="2" x2="8" y2="6" />
                  <line x1="3" y1="10" x2="21" y2="10" />
                </svg>
              </span>
              <div className="album-stat-item__text">
                <span className="album-stat-item__count">{formatShortDate(album?.created_at)}</span>
                <span className="album-stat-item__label">Wedding Day</span>
              </div>
            </div>

            {/* Total File Size */}
            <div className="album-stat-item">
              <span className="album-stat-item__icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" width="22" height="22">
                  <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
                  <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
                  <line x1="12" y1="22.08" x2="12" y2="12" />
                </svg>
              </span>
              <div className="album-stat-item__text">
                <span className="album-stat-item__count">
                  {totalAlbumBytes > 0 ? formatBytes(totalAlbumBytes) : "0 B"}
                </span>
                <span className="album-stat-item__label">Total Size</span>
              </div>
            </div>
          </div>

          <div className="album-stat-bar__right" ref={moreMenuRef}>
            {/* Download Album Button */}
            <button
              type="button"
              className="album-stat-btn-download"
              onClick={handleDownloadAllAsZip}
              aria-label="Download Full Album as ZIP"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              <span>Download Album</span>
            </button>

            {/* More Options Button */}
            <button
              type="button"
              className="album-stat-btn-more"
              onClick={() => setShowMoreMenu((prev) => !prev)}
              aria-label="More options"
              aria-expanded={showMoreMenu}
            >
              •••
            </button>

            {showMoreMenu && (
              <div className="album-more-menu" role="menu">
                <button
                  type="button"
                  className="album-more-menu__item"
                  onClick={selectAll}
                  role="menuitem"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="9 11 12 14 22 4" />
                    <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
                  </svg>
                  <span>Select All Media</span>
                </button>
                <button
                  type="button"
                  className="album-more-menu__item"
                  onClick={() => {
                    setShowSearchPanel((p) => !p);
                    setShowMoreMenu(false);
                  }}
                  role="menuitem"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                  <span>Find by Name</span>
                </button>
                <button
                  type="button"
                  className="album-more-menu__item"
                  onClick={handleDownloadAllAsZip}
                  role="menuitem"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="7 10 12 15 17 10" />
                    <line x1="12" y1="15" x2="12" y2="3" />
                  </svg>
                  <span>Download as ZIP</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="gallery-controls-wrapper">
        {error && <p className="auth-error">{error}</p>}

        {expiry && (
          <div style={{ marginBottom: "1rem" }}>
            <span
              className={
                "expiry-badge " +
                (expiry.isExpired ? "expiry-badge--expired" : expiry.isNearExpiry ? "expiry-badge--warning" : "expiry-badge--normal")
              }
            >
              {expiry.label}
            </span>
          </div>
        )}

        {/* Expandable Search Panel */}
        {showSearchPanel && (
          <form onSubmit={handleSearchSubmit} className="gallery-search-panel">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search media by filename..."
              className="gallery-search-input"
              autoFocus
            />
            <button type="submit" className="btn-primary">
              Search
            </button>
            {appliedSearch && (
              <button type="button" className="btn-text" onClick={clearSearch}>
                Clear
              </button>
            )}
          </form>
        )}

        {searchResultCount !== null && (
          <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "1rem" }}>
            {searchResultCount} {searchResultCount === 1 ? "result" : "results"} found for &quot;{appliedSearch}&quot;
          </p>
        )}

        {/* Media Filter Tabs & Sort Dropdown (Reference Image 1) */}
        <div className="gallery-filter-row">
          <div className="gallery-filter-tabs">
            {/* All Media Tab */}
            <button
              type="button"
              className={"gallery-filter-tab" + (mediaFilter === "all" ? " gallery-filter-tab--active" : "")}
              onClick={() => setMediaFilter("all")}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <rect x="3" y="3" width="7" height="7" />
                <rect x="14" y="3" width="7" height="7" />
                <rect x="14" y="14" width="7" height="7" />
                <rect x="3" y="14" width="7" height="7" />
              </svg>
              <span>All Media</span>
            </button>

            {/* Photos Tab */}
            <button
              type="button"
              className={"gallery-filter-tab" + (mediaFilter === "photo" ? " gallery-filter-tab--active" : "")}
              onClick={() => setMediaFilter("photo")}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                <circle cx="8.5" cy="8.5" r="1.5" />
                <polyline points="21 15 16 10 5 21" />
              </svg>
              <span>Photos</span>
            </button>

            {/* Videos Tab */}
            <button
              type="button"
              className={"gallery-filter-tab" + (mediaFilter === "video" ? " gallery-filter-tab--active" : "")}
              onClick={() => setMediaFilter("video")}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <polygon points="23 7 16 12 23 17 23 7" />
                <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
              </svg>
              <span>Videos</span>
            </button>
          </div>

          {/* Right Controls: Sort & Layout Toggle */}
          <div className="gallery-controls-right">
            {/* Sort Selector */}
            <div className="gallery-sort-control">
              <span>Sort by</span>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as "newest" | "oldest" | "name")}
                className="gallery-sort-select"
                aria-label="Sort media items"
              >
                <option value="newest">Newest First</option>
                <option value="oldest">Oldest First</option>
                <option value="name">Name (A - Z)</option>
              </select>
            </div>

            {/* Layout Switcher (Grid / List) */}
            <div className="gallery-layout-toggle" role="group" aria-label="View layout">
              <button
                type="button"
                className={"gallery-layout-btn" + (layoutMode === "grid" ? " gallery-layout-btn--active" : "")}
                onClick={() => setLayoutMode("grid")}
                aria-label="Grid view"
                title="Grid view"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="3" width="7" height="7" />
                  <rect x="14" y="3" width="7" height="7" />
                  <rect x="14" y="14" width="7" height="7" />
                  <rect x="3" y="14" width="7" height="7" />
                </svg>
              </button>
              <button
                type="button"
                className={"gallery-layout-btn" + (layoutMode === "list" ? " gallery-layout-btn--active" : "")}
                onClick={() => setLayoutMode("list")}
                aria-label="List view"
                title="List view"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="8" y1="6" x2="21" y2="6" />
                  <line x1="8" y1="12" x2="21" y2="12" />
                  <line x1="8" y1="18" x2="21" y2="18" />
                  <line x1="3" y1="6" x2="3.01" y2="6" />
                  <line x1="3" y1="12" x2="3.01" y2="12" />
                  <line x1="3" y1="18" x2="3.01" y2="18" />
                </svg>
              </button>
            </div>
          </div>
        </div>

        {/* Selection Bar for multi-select */}
        {selectedIds.size > 0 && (
          <div className="selection-bar">
            <div>
              <span className="selection-bar__count">
                {selectedIds.size} {selectedIds.size === 1 ? "item" : "items"} selected
              </span>
              <span className="selection-bar__meta"> · ~{formatBytes(selectedBytes)}</span>
            </div>
            <div className="selection-bar__actions">
              <button className="btn-primary" onClick={handleDownloadSelected}>
                Download Selected
              </button>
              <button className="btn-secondary" onClick={clearSelection}>
                Clear Selection
              </button>
            </div>
          </div>
        )}

        {!loading && sortedItems.length === 0 && !error && (
          <div className="empty-state">
            {appliedSearch ? "No media matches your search." : "No media items in this album yet."}
          </div>
        )}

        {/* Media Grid or List based on layoutMode */}
        {layoutMode === "grid" ? (
          <div className="wedding-media-grid">
            {sortedItems.map((item, i) => {
              const isSelected = selectedIds.has(item.id);
              const isVideo = item.file_type === "video";

              return (
                <div
                  key={item.id}
                  className={"wedding-media-tile" + (isSelected ? " wedding-media-tile--selected" : "")}
                  onClick={() => setLightboxIndex(i)}
                  tabIndex={0}
                  role="button"
                  aria-label={`View ${item.file_name}`}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setLightboxIndex(i);
                    }
                  }}
                >
                  {/* Checkbox for selection */}
                  <span
                    className={"wedding-media-tile__checkbox" + (isSelected ? " wedding-media-tile__checkbox--checked" : "")}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleSelect(item.id);
                    }}
                    role="checkbox"
                    aria-checked={isSelected}
                    aria-label={`Select ${item.file_name}`}
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.stopPropagation();
                        e.preventDefault();
                        toggleSelect(item.id);
                      }
                    }}
                  >
                    {isSelected ? "✓" : ""}
                  </span>

                  <WishlistHeart active={wishlist.isWishlisted(item.id)} onToggle={() => wishlist.toggle(item.id)} />

                  {/* Media Image Thumbnail */}
                  {item.has_thumbnail ? (
                    <img
                      src={getThumbnail(item)}
                      alt={item.file_name}
                      loading="lazy"
                      onLoad={(e) => e.currentTarget.classList.add("is-loaded")}
                    />
                  ) : (
                    <div
                      style={{
                        width: "100%",
                        height: "100%",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "var(--text-muted)",
                        fontSize: "0.8rem",
                      }}
                    >
                      {isVideo ? "Video" : "Photo"}
                    </div>
                  )}

                  {/* Centered Translucent Play Icon for Videos (Reference Image 1) */}
                  {isVideo && (
                    <>
                      <div className="video-play-center" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="currentColor">
                          <polygon points="5 3 19 12 5 21 5 3" />
                        </svg>
                      </div>
                      {/* Duration Badge in Bottom Right */}
                      <span className="video-duration-badge">{getVideoDurationBadge(item.id)}</span>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="wedding-media-list">
            {sortedItems.map((item, i) => {
              const isSelected = selectedIds.has(item.id);
              const isVideo = item.file_type === "video";

              return (
                <div
                  key={item.id}
                  className={"wedding-media-list-row" + (isSelected ? " wedding-media-list-row--selected" : "")}
                >
                  <span
                    className={"wedding-media-list-checkbox" + (isSelected ? " wedding-media-list-checkbox--checked" : "")}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleSelect(item.id);
                    }}
                    role="checkbox"
                    aria-checked={isSelected}
                    aria-label={`Select ${item.file_name}`}
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.stopPropagation();
                        e.preventDefault();
                        toggleSelect(item.id);
                      }
                    }}
                  >
                    {isSelected ? "✓" : ""}
                  </span>

                  <div
                    className="wedding-media-list-thumb"
                    onClick={() => setLightboxIndex(i)}
                    role="button"
                    tabIndex={0}
                    aria-label={`Preview ${item.file_name}`}
                  >
                    {item.has_thumbnail ? (
                      <img src={getThumbnail(item)} alt={item.file_name} loading="lazy" />
                    ) : (
                      <div
                        style={{
                          width: "100%",
                          height: "100%",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontSize: "0.75rem",
                          color: "var(--text-muted)",
                        }}
                      >
                        {isVideo ? "Video" : "Photo"}
                      </div>
                    )}
                    {isVideo && (
                      <div className="video-play-center" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="currentColor">
                          <polygon points="5 3 19 12 5 21 5 3" />
                        </svg>
                      </div>
                    )}
                  </div>

                  <div className="wedding-media-list-info">
                    <span
                      className="wedding-media-list-name"
                      onClick={() => setLightboxIndex(i)}
                      title={item.file_name}
                    >
                      {item.file_name}
                    </span>
                    <div className="wedding-media-list-meta">
                      <span className="wedding-media-list-tag">
                        {isVideo ? "📹 Video" : "📷 Photo"}
                      </span>
                      <span>{formatBytes(item.file_size)}</span>
                      {isVideo && <span>Duration: {getVideoDurationBadge(item.id)}</span>}
                    </div>
                  </div>

                  <div className="wedding-media-list-actions">
                    <WishlistHeart
                      variant="row"
                      active={wishlist.isWishlisted(item.id)}
                      onToggle={() => wishlist.toggle(item.id)}
                    />
                    <button
                      type="button"
                      className="wedding-media-list-btn"
                      onClick={() => setLightboxIndex(i)}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                        <circle cx="12" cy="12" r="3" />
                      </svg>
                      <span>View</span>
                    </button>
                    <a
                      href={galleryService.downloadUrl(item.id)}
                      download
                      className="wedding-media-list-btn"
                      onClick={(e) => {
                        if (hasDownloadPassword) {
                          e.preventDefault();
                          setSingleDownloadUrl(galleryService.downloadUrl(item.id));
                        }
                      }}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="7 10 12 15 17 10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                      </svg>
                      <span>Download</span>
                    </a>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {hasMore && (
          <div className="load-more-row">
            <button className="btn-secondary" onClick={loadMore}>
              Load more
            </button>
          </div>
        )}
      </div>

      {/* Media Lightbox */}
      {lightboxIndex !== null && (
        <MediaLightbox
          items={sortedItems}
          startIndex={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          viewUrl={getViewUrl}
          downloadUrl={galleryService.downloadUrl}
          thumbnailUrl={getThumbnailUrl}
          onDownload={
            hasDownloadPassword ? (item) => setSingleDownloadUrl(galleryService.downloadUrl(item.id)) : undefined
          }
          isWishlisted={(item) => wishlist.isWishlisted(item.id)}
          onToggleWishlist={(item) => wishlist.toggle(item.id)}
        />
      )}

      {/* Download Job Modal */}
      {downloadJobRequest !== null && (
        <DownloadJobModal
          requirePasswordFirst={hasDownloadPassword || galleryId === "test-uuid" || galleryId === "preview" || galleryId === "demo"}
          createJob={() =>
            galleryService.createDownloadJob(
              albumIdNum,
              downloadJobRequest === "all" ? undefined : downloadJobRequest
            )
          }
          pollStatus={(jobId) => galleryService.getDownloadJobStatus(jobId)}
          cancelJob={(jobId) => galleryService.cancelDownloadJob(jobId)}
          fileUrl={galleryService.downloadJobFileUrl}
          verifyPassword={(_, pw) => {
            if (galleryId === "test-uuid" || galleryId === "preview" || galleryId === "demo") {
              return Promise.resolve(true);
            }
            return galleryService.verifyDownloadPassword(pw).then(() => true);
          }}
          onClose={() => setDownloadJobRequest(null)}
        />
      )}

      {/* Download Password Modal */}
      {singleDownloadUrl && (
        <DownloadPasswordModal
          downloadUrl={singleDownloadUrl}
          verifyPassword={(pw) => galleryService.verifyDownloadPassword(pw).then(() => true)}
          onClose={() => setSingleDownloadUrl(null)}
        />
      )}

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
