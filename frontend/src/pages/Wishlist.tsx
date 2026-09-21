import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ClientNav from "../components/ClientNav";
import DownloadPasswordModal from "../components/DownloadPasswordModal";
import MediaLightbox from "../components/MediaLightbox";
import WishlistHeart from "../components/WishlistHeart";
import { useWishlist } from "../hooks/useWishlist";
import { ApiRequestError } from "../services/api";
import { GalleryMedia, galleryService } from "../services/gallery";

const PAGE_SIZE = 60;

// /gallery/:galleryId/wishlist - every photo/video the signed-in client has
// hearted, across all of their albums. Reuses the album page's tile grid and
// the shared MediaLightbox; nothing here is a second implementation of either.
//
// The list is fetched once and then kept STABLE while the page is open: if you
// un-heart something here it stays in place (dimmed, with the heart back to
// outline) so a mis-click can be undone with one more tap and the lightbox
// never jumps to a different photo underneath you. It drops off the list the
// next time the page is loaded.
export default function Wishlist() {
  const { galleryId = "" } = useParams();
  const navigate = useNavigate();

  const [items, setItems] = useState<GalleryMedia[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  // Same single-download gate as the album page: if the studio set a download
  // password, downloads go through the password modal (the server enforces it
  // too - without the modal the click would just come back as a 403).
  const [hasDownloadPassword, setHasDownloadPassword] = useState(false);
  const [singleDownloadUrl, setSingleDownloadUrl] = useState<string | null>(null);

  const isDemoGallery = galleryId === "test-uuid" || galleryId === "preview" || galleryId === "demo";

  function showToast(message: string) {
    setToast(message);
    setTimeout(() => setToast(null), 3000);
  }

  const wishlist = useWishlist({ demo: isDemoGallery, onError: showToast });

  useEffect(() => {
    let cancelled = false;
    galleryService
      .getGallery()
      .then((info) => {
        if (!cancelled) setHasDownloadPassword(info.has_download_password);
      })
      .catch(() => {
        // Not fatal here - the wishlist request below handles a lost session.
      });
    galleryService
      .listWishlist(1, PAGE_SIZE)
      .then((result) => {
        if (cancelled) return;
        setItems(result.items);
        wishlist.seed(result.items);
        setTotal(result.total);
        setHasMore(result.has_more);
        setPage(1);
      })
      .catch((err) => {
        if (cancelled) return;
        if (isDemoGallery) {
          // Demo galleries have no backend: just show the empty state.
          setItems([]);
        } else if (err instanceof ApiRequestError && err.status === 401) {
          // Session gone -> back to the password screen, like every other client page.
          navigate(`/gallery/${galleryId}`, { replace: true });
        } else {
          setError("We couldn't load your wishlist. Please try again.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // wishlist.seed is stable (useCallback with no deps); galleryId/navigate are the real inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [galleryId]);

  async function loadMore() {
    if (loadingMore) return;
    setLoadingMore(true);
    try {
      const nextPage = page + 1;
      const result = await galleryService.listWishlist(nextPage, PAGE_SIZE);
      // Skip anything already on screen (e.g. hearted on another tab meanwhile) so keys stay unique.
      setItems((prev) => {
        const seen = new Set(prev.map((i) => i.id));
        return [...prev, ...result.items.filter((i) => !seen.has(i.id))];
      });
      wishlist.seed(result.items); // only the NEW page
      setTotal(result.total);
      setHasMore(result.has_more);
      setPage(nextPage);
    } catch {
      showToast("Couldn't load more. Please try again.");
    } finally {
      setLoadingMore(false);
    }
  }

  // Items un-hearted since the list loaded (still shown, so they can be undone).
  const removedCount = items.filter((i) => !wishlist.isWishlisted(i.id)).length;
  const savedCount = Math.max(0, total - removedCount);

  return (
    <div className="client-shell">
      <ClientNav galleryId={galleryId} />

      <main className="wedding-landing">
        <div className="wedding-landing__content">
          <section className="wedding-landing__header">
            <p className="wedding-landing__kicker">Your favourites</p>
            <h1 className="wedding-landing__title">My Wishlist</h1>
            <div className="wedding-landing__heart-sep" aria-hidden="true">
              ♡
            </div>
            {!loading && !error && (
              <p className="wedding-landing__sub">
                {savedCount} {savedCount === 1 ? "photo" : "photos"} saved
              </p>
            )}
            <button
              type="button"
              className="btn-secondary wishlist-page__back"
              onClick={() => navigate(`/gallery/${galleryId}/view`)}
            >
              ← All albums
            </button>
          </section>

          {error && <p className="auth-error">{error}</p>}

          {!loading && !error && items.length === 0 && (
            <div className="empty-state">
              Your wishlist is empty. Tap the heart on any photo to save it here.
            </div>
          )}

          {items.length > 0 && (
            <div className="wedding-media-grid">
              {items.map((item, i) => {
                const active = wishlist.isWishlisted(item.id);
                const isVideo = item.file_type === "video";
                return (
                  <div
                    key={item.id}
                    className={"wedding-media-tile" + (active ? "" : " wedding-media-tile--unwishlisted")}
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
                    <WishlistHeart active={active} onToggle={() => wishlist.toggle(item.id)} />

                    {item.has_thumbnail ? (
                      <img
                        src={galleryService.thumbnailUrl(item.id)}
                        alt={item.file_name}
                        loading="lazy"
                        onLoad={(e) => e.currentTarget.classList.add("is-loaded")}
                      />
                    ) : (
                      <div className="wishlist-page__no-thumb">{isVideo ? "Video" : "Photo"}</div>
                    )}

                    {isVideo && (
                      <div className="video-play-center" aria-hidden="true">
                        <svg viewBox="0 0 24 24" fill="currentColor">
                          <polygon points="5 3 19 12 5 21 5 3" />
                        </svg>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {hasMore && (
            <div className="load-more-row">
              <button className="btn-secondary" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? "Loading…" : "Load more"}
              </button>
            </div>
          )}
        </div>
      </main>

      {lightboxIndex !== null && (
        <MediaLightbox
          items={items}
          startIndex={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          viewUrl={galleryService.viewUrl}
          downloadUrl={galleryService.downloadUrl}
          thumbnailUrl={galleryService.thumbnailUrl}
          onDownload={
            hasDownloadPassword ? (item) => setSingleDownloadUrl(galleryService.downloadUrl(item.id)) : undefined
          }
          isWishlisted={(item) => wishlist.isWishlisted(item.id)}
          onToggleWishlist={(item) => wishlist.toggle(item.id)}
        />
      )}

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
