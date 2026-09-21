import {
  FormEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useNavigate, useParams } from "react-router-dom";
import AdminLayout from "../components/AdminLayout";
import Modal from "../components/Modal";
import DownloadJobModal from "../components/DownloadJobModal";
import MediaLightbox from "../components/MediaLightbox";
import { AlbumItem, adminService, MediaItem, WishlistCounts, WishlistFilter } from "../services/admin";
import { formatBytes, getExpiryInfo } from "../utils/format";

const PAGE_SIZE = 40;

type MediaViewMode = "grid" | "gallery" | "list";

const VIEW_MODE_KEY = "admin-media-view-mode";

// The client's wishlist, as a filter over this album (a database query only -
// nothing is copied anywhere).
const WISHLIST_FILTER_TABS: { key: WishlistFilter; label: string }[] = [
  { key: "all", label: "All media" },
  { key: "wishlisted", label: "Wishlist" },
  { key: "not_wishlisted", label: "Not wishlisted" },
];

function WishlistBadge({ inline = false }: { inline?: boolean }) {
  return (
    <span
      className={"wishlist-badge" + (inline ? " wishlist-badge--inline" : "")}
      title="In the client's wishlist"
      aria-label="In the client's wishlist"
      role="img"
    >
      <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor" aria-hidden="true">
        <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
      </svg>
    </span>
  );
}

type ModalState =
  | { kind: "edit"; media: MediaItem }
  | { kind: "move"; media: MediaItem }
  | { kind: "confirm-delete"; media: MediaItem }
  | { kind: "bulk-move" }
  | { kind: "bulk-confirm-delete" }
  | null;

export default function AlbumMedia() {
  const { albumId = "" } = useParams();
  const navigate = useNavigate();
  const albumIdNum = Number(albumId);

  const [album, setAlbum] = useState<AlbumItem | null>(null);
  const [clientName, setClientName] = useState<string>("");
  const [allAlbumsForClient, setAllAlbumsForClient] = useState<AlbumItem[]>([]);
  const [items, setItems] = useState<MediaItem[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const [modal, setModal] = useState<ModalState>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [downloadJobRequest, setDownloadJobRequest] = useState<number[] | "all" | null>(null);
  const [viewMode, setViewMode] = useState<MediaViewMode>(() => {
    const stored = localStorage.getItem(VIEW_MODE_KEY);
    return stored === "gallery" ? "gallery" : stored === "list" ? "list" : "grid";
  });
  const [openMenuId, setOpenMenuId] = useState<number | null>(null);
  const [wishlistFilter, setWishlistFilter] = useState<WishlistFilter>("all");
  const [wishlistCounts, setWishlistCounts] = useState<WishlistCounts | null>(null);
  // Guards rapid tab clicks: only the most recent filter request may apply its result.
  const filterRequestRef = useRef(0);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuAnchorRef = useRef<HTMLButtonElement>(null);

  function showToast(message: string) {
    setToast(message);
    setTimeout(() => setToast(null), 3000);
  }

  async function loadAlbumAndMedia(searchTerm = search, filter: WishlistFilter = wishlistFilter) {
    setLoading(true);
    try {
      const [albumData, mediaPage, clientPage, counts] = await Promise.all([
        adminService.getAlbum(albumIdNum),
        adminService.listAlbumMedia(albumIdNum, 1, PAGE_SIZE, searchTerm || undefined, filter),
        adminService.listClients(1, 200),
        // Counts are decoration: never let them fail the page load.
        adminService.getAlbumWishlistCounts(albumIdNum, searchTerm || undefined).catch(() => null),
      ]);
      setAlbum(albumData);
      setWishlistCounts(counts);
      setItems(mediaPage.items);
      setHasMore(mediaPage.has_more);
      setPage(1);
      setSelectedIds(new Set());

      const owningClient = clientPage.items.find((c) => c.id === albumData.client_id);
      setClientName(owningClient?.client_name ?? "");

      const albumsPage = await adminService.listAlbums(1, 200);
      setAllAlbumsForClient(albumsPage.items.filter((a) => a.client_id === albumData.client_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load album.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // A different album always starts on "All media".
    setWishlistFilter("all");
    loadAlbumAndMedia("", "all");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [albumIdNum]);

  useEffect(() => {
    localStorage.setItem(VIEW_MODE_KEY, viewMode);
  }, [viewMode]);

  useEffect(() => {
    if (openMenuId === null) return;
    function handleClick(e: MouseEvent) {
      const node = e.target as Node;
      if (menuRef.current?.contains(node) || menuAnchorRef.current?.contains(node)) return;
      setOpenMenuId(null);
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpenMenuId(null);
    }
    document.addEventListener("mousedown", handleClick);
    window.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      window.removeEventListener("keydown", handleKey);
    };
  }, [openMenuId]);

  async function loadMore() {
    const nextPage = page + 1;
    const mediaPage = await adminService.listAlbumMedia(
      albumIdNum,
      nextPage,
      PAGE_SIZE,
      search || undefined,
      wishlistFilter
    );
    setItems((prev) => [...prev, ...mediaPage.items]);
    setHasMore(mediaPage.has_more);
    setPage(nextPage);
  }

  function handleSearchSubmit(e: FormEvent) {
    e.preventDefault();
    loadAlbumAndMedia(search);
  }

  // Lightweight on purpose: a tab click re-fetches only page 1 of the media and
  // the counts - not the album, the client list and the album list that a full
  // loadAlbumAndMedia() also pulls.
  async function changeWishlistFilter(next: WishlistFilter) {
    if (next === wishlistFilter) return;
    const previous = wishlistFilter;
    const requestId = ++filterRequestRef.current;
    setWishlistFilter(next);
    try {
      const [mediaPage, counts] = await Promise.all([
        adminService.listAlbumMedia(albumIdNum, 1, PAGE_SIZE, search || undefined, next),
        adminService.getAlbumWishlistCounts(albumIdNum, search || undefined).catch(() => null),
      ]);
      if (requestId !== filterRequestRef.current) return; // a newer click superseded this one
      setItems(mediaPage.items);
      setHasMore(mediaPage.has_more);
      setPage(1);
      // Selection belongs to what was on screen: a different filter is a different set.
      setSelectedIds(new Set());
      setLightboxIndex(null);
      if (counts) setWishlistCounts(counts);
    } catch (err) {
      if (requestId !== filterRequestRef.current) return;
      setWishlistFilter(previous);
      showToast(err instanceof Error ? err.message : "Failed to apply filter.");
    }
  }

  function refreshWishlistCounts() {
    adminService
      .getAlbumWishlistCounts(albumIdNum, search || undefined)
      .then(setWishlistCounts)
      .catch(() => {
        // Counts are decoration; keep the last known numbers.
      });
  }

  function replaceItem(updated: MediaItem) {
    setItems((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
  }

  function removeItemsAndCloseIfNeeded(mediaIds: number[]) {
    const idSet = new Set(mediaIds);
    setItems((prev) => prev.filter((m) => !idSet.has(m.id)));
    setSelectedIds((prev) => {
      const next = new Set(prev);
      mediaIds.forEach((id) => next.delete(id));
      return next;
    });
    setLightboxIndex(null);
    refreshWishlistCounts();
  }

  function toggleSelect(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function selectAllAcrossAlbum() {
    try {
      // Same wishlist filter as the grid: "Select all" feeds bulk delete /
      // move / download, so under the Wishlist tab it selects ONLY those.
      const summary = await adminService.getAlbumMediaSelectionSummary(albumIdNum, search || undefined, wishlistFilter);
      setSelectedIds(new Set(summary.ids));
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Failed to select all.");
    }
  }

  function clearSelection() {
    setSelectedIds(new Set());
  }

  async function handleBulkDelete() {
    setBulkBusy(true);
    try {
      const result = await adminService.bulkDeleteMedia(Array.from<number>(selectedIds));
      removeItemsAndCloseIfNeeded(result.deleted);
      setModal(null);
      if (result.failed.length > 0) {
        showToast(`${result.deleted.length} deleted, ${result.failed.length} failed.`);
      } else {
        showToast(`${result.deleted.length} deleted.`);
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Bulk delete failed.");
    } finally {
      setBulkBusy(false);
    }
  }

  async function handleBulkMove(targetAlbumId: number) {
    setBulkBusy(true);
    try {
      const result = await adminService.bulkMoveMedia(Array.from<number>(selectedIds), targetAlbumId);
      removeItemsAndCloseIfNeeded(result.moved);
      setModal(null);
      if (result.failed.length > 0) {
        showToast(`${result.moved.length} moved, ${result.failed.length} failed.`);
      } else {
        showToast(`${result.moved.length} moved.`);
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Bulk move failed.");
    } finally {
      setBulkBusy(false);
    }
  }

  function handleBulkDownload() {
    setDownloadJobRequest(Array.from<number>(selectedIds));
  }

  const selectedCount = selectedIds.size;

  return (
    <AdminLayout>
      <button className="gallery-header__back" style={{ marginBottom: "0.75rem" }} onClick={() => navigate("/admin/albums")}>
        ← All albums
      </button>
      <h1 className="admin-page-title">{album?.album_name ?? "Album"}</h1>
      <p className="admin-page-subtitle">{clientName ? `${clientName}'s gallery` : "Loading..."}</p>

      {error && <p className="auth-error">{error}</p>}

      {album && (
        <AlbumExpiryControl
          album={album}
          onSaved={(updated) => {
            setAlbum(updated);
            showToast("Expiry updated.");
          }}
        />
      )}

      <div className="view-toggle wishlist-filter" role="group" aria-label="Filter by the client's wishlist">
        {WISHLIST_FILTER_TABS.map((tab) => {
          const active = wishlistFilter === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              className={"view-toggle__btn" + (active ? " view-toggle__btn--active" : "")}
              onClick={() => changeWishlistFilter(tab.key)}
              aria-pressed={active}
            >
              <span>{tab.label}</span>
              <span className="wishlist-filter__count">{wishlistCounts ? wishlistCounts[tab.key] : "–"}</span>
            </button>
          );
        })}
      </div>

      <form
        onSubmit={handleSearchSubmit}
        className="album-media-toolbar"
        style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", marginTop: "1.25rem", flexWrap: "wrap", alignItems: "center" }}
      >
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by filename..."
          style={{
            background: "var(--bg)",
            border: "1px solid var(--hairline)",
            color: "var(--text)",
            padding: "0.55rem 0.75rem",
            borderRadius: "6px",
            fontSize: "0.9rem",
            flex: 1,
            maxWidth: "320px",
          }}
        />
        <button type="submit" className="btn-secondary">
          Search
        </button>
        <button type="button" className="btn-text" onClick={selectAllAcrossAlbum}>
          Select all{search || wishlistFilter !== "all" ? " matching" : ""}
        </button>
        {selectedCount > 0 && (
          <button type="button" className="btn-text" onClick={clearSelection}>
            Clear selection
          </button>
        )}
        {!search && wishlistFilter === "all" && (
          <button type="button" className="btn-secondary" onClick={() => setDownloadJobRequest("all")}>
            Download Album as ZIP
          </button>
        )}

        <div className="view-toggle" role="group" aria-label="Media view">
          <button
            type="button"
            className={"view-toggle__btn" + (viewMode === "grid" ? " view-toggle__btn--active" : "")}
            onClick={() => setViewMode("grid")}
            aria-pressed={viewMode === "grid"}
            title="Compact grid view"
          >
            <svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor" aria-hidden="true">
              <rect x="1" y="1" width="6" height="6" rx="1" />
              <rect x="9" y="1" width="6" height="6" rx="1" />
              <rect x="1" y="9" width="6" height="6" rx="1" />
              <rect x="9" y="9" width="6" height="6" rx="1" />
            </svg>
            Grid
          </button>
          <button
            type="button"
            className={"view-toggle__btn" + (viewMode === "gallery" ? " view-toggle__btn--active" : "")}
            onClick={() => setViewMode("gallery")}
            aria-pressed={viewMode === "gallery"}
            title="Spacious gallery view"
          >
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" aria-hidden="true">
              <rect x="3" y="3" width="18" height="18" rx="2" strokeWidth="2" />
              <circle cx="8.5" cy="8.5" r="1.5" fill="currentColor" stroke="none" />
              <path d="M21 15l-5-5L5 21" strokeWidth="2" />
            </svg>
            Gallery
          </button>
          <button
            type="button"
            className={"view-toggle__btn" + (viewMode === "list" ? " view-toggle__btn--active" : "")}
            onClick={() => setViewMode("list")}
            aria-pressed={viewMode === "list"}
            title="Compact list view"
          >
            <svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor" aria-hidden="true">
              <rect x="1" y="2.25" width="14" height="2.25" rx="1.1" />
              <rect x="1" y="6.875" width="14" height="2.25" rx="1.1" />
              <rect x="1" y="11.5" width="14" height="2.25" rx="1.1" />
            </svg>
            List
          </button>
        </div>
      </form>

      {selectedCount > 0 && (
        <div className="selection-bar">
          <span className="selection-bar__count">
            {selectedCount} selected
          </span>
          <div className="selection-bar__actions">
            <button className="btn-secondary" onClick={handleBulkDownload} disabled={bulkBusy}>
              Download
            </button>
            <button className="btn-secondary" onClick={() => setModal({ kind: "bulk-move" })} disabled={bulkBusy}>
              Move
            </button>
            <button
              className="btn-secondary"
              style={{ color: "var(--danger)" }}
              onClick={() => setModal({ kind: "bulk-confirm-delete" })}
              disabled={bulkBusy}
            >
              Delete
            </button>
          </div>
        </div>
      )}

      {!loading && items.length === 0 && (
        <div className="empty-state">
          {search
            ? "No files match that search."
            : wishlistFilter === "wishlisted"
              ? "The client hasn't added anything from this album to their wishlist yet."
              : wishlistFilter === "not_wishlisted"
                ? "Every item in this album is on the client's wishlist."
                : "No photos or videos in this album yet."}
        </div>
      )}

      <div className={"media-grid media-grid--" + viewMode}>
        {items.map((item, i) => {
          const isSelected = selectedIds.has(item.id);

          if (viewMode === "list") {
            return (
              <div key={item.id} className={"media-row" + (isSelected ? " media-row--selected" : "")}>
                <div className="media-row__thumb">
                  <span
                    className={"media-tile__checkbox" + (isSelected ? " media-tile__checkbox--checked" : "")}
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
                        e.preventDefault();
                        toggleSelect(item.id);
                      }
                    }}
                  >
                    {isSelected ? "✓" : ""}
                  </span>
                  {item.is_wishlisted && <WishlistBadge />}
                  <button
                    className="media-row__open"
                    onClick={() => setLightboxIndex(i)}
                    aria-label={`Open ${item.file_name}`}
                  >
                    {item.has_thumbnail ? (
                      <img
                        src={adminService.adminThumbnailUrl(item.id)}
                        alt={item.file_name}
                        loading="lazy"
                        onLoad={(e) => e.currentTarget.classList.add("is-loaded")}
                      />
                    ) : (
                      <span className="media-tile__fallback">{item.file_type === "video" ? "Video" : "Photo"}</span>
                    )}
                    {item.file_type === "video" && <span className="media-row__video-badge">▶</span>}
                  </button>
                </div>
                <div className="media-row__info">
                  <span className="media-row__name">{item.file_name}</span>
                  <span className="media-row__sub">
                    {item.title ? `${item.title} · ` : ""}
                    {item.file_type === "video" ? "Video" : "Photo"}
                  </span>
                </div>
                <span className="media-row__size">{formatBytes(item.file_size)}</span>
                <span className="row-actions media-row__actions">
                  <button
                    type="button"
                    className="media-row__menu-btn"
                    ref={openMenuId === item.id ? menuAnchorRef : undefined}
                    aria-haspopup="menu"
                    aria-expanded={openMenuId === item.id}
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpenMenuId((curr) => (curr === item.id ? null : item.id));
                    }}
                  >
                    ⋯
                  </button>
                  {openMenuId === item.id && (
                    <RowActionsMenu anchorRef={menuAnchorRef} menuRef={menuRef}>
                      <button
                        className="row-actions__item"
                        role="menuitem"
                        onClick={() => {
                          setOpenMenuId(null);
                          setModal({ kind: "edit", media: item });
                        }}
                      >
                        Edit
                      </button>
                      <button
                        className="row-actions__item"
                        role="menuitem"
                        onClick={() => {
                          setOpenMenuId(null);
                          setModal({ kind: "move", media: item });
                        }}
                      >
                        Move
                      </button>
                      <button
                        className="row-actions__item row-actions__item--danger"
                        role="menuitem"
                        onClick={() => {
                          setOpenMenuId(null);
                          setModal({ kind: "confirm-delete", media: item });
                        }}
                      >
                        Delete
                      </button>
                    </RowActionsMenu>
                  )}
                </span>
              </div>
            );
          }

          return (
            <div key={item.id} className={"media-tile" + (isSelected ? " media-tile--selected" : "")}>
              <span
                className={"media-tile__checkbox" + (isSelected ? " media-tile__checkbox--checked" : "")}
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
                    e.preventDefault();
                    toggleSelect(item.id);
                  }
                }}
              >
                {isSelected ? "✓" : ""}
              </span>
              {item.is_wishlisted && <WishlistBadge />}
              <button
                style={{ all: "unset", cursor: "pointer", display: "block", width: "100%", height: "100%" }}
                onClick={() => setLightboxIndex(i)}
                aria-label={`Open ${item.file_name}`}
              >
                {item.has_thumbnail ? (
                  <img
                    src={adminService.adminThumbnailUrl(item.id)}
                    alt={item.file_name}
                    loading="lazy"
                    onLoad={(e) => e.currentTarget.classList.add("is-loaded")}
                  />
                ) : (
                  <span className="media-tile__fallback">{item.file_type === "video" ? "Video" : "Photo"}</span>
                )}
                {item.file_type === "video" && <span className="media-tile__video-badge">▶</span>}
              </button>
            </div>
          );
        })}
      </div>

      {hasMore && (
        <div className="load-more-row">
          <button className="btn-secondary" onClick={loadMore}>
            Load more
          </button>
        </div>
      )}

      {lightboxIndex !== null && (
        <MediaLightbox
          items={items}
          startIndex={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          viewUrl={adminService.adminViewUrl}
          downloadUrl={adminService.adminDownloadUrl}
          thumbnailUrl={adminService.adminThumbnailUrl}
          renderActions={(item) => (
            <>
              {item.is_wishlisted && (
                <span className="lightbox-icon-btn wishlist-admin-tag" title="The client added this to their wishlist">
                  <WishlistBadge inline /> In wishlist
                </span>
              )}
              <button className="lightbox-icon-btn" onClick={() => setModal({ kind: "edit", media: item })}>
                Edit
              </button>
              <button className="lightbox-icon-btn" onClick={() => setModal({ kind: "move", media: item })}>
                Move
              </button>
              <button className="lightbox-icon-btn" onClick={() => setModal({ kind: "confirm-delete", media: item })}>
                Delete
              </button>
            </>
          )}
        />
      )}

      {modal?.kind === "edit" && (
        <EditMediaModal
          media={modal.media}
          onClose={() => setModal(null)}
          onSaved={(updated) => {
            replaceItem(updated);
            setModal(null);
            showToast("Media updated.");
          }}
        />
      )}

      {modal?.kind === "move" && (
        <MoveMediaModal
          albums={allAlbumsForClient.filter((a) => a.id !== albumIdNum)}
          title={`Move ${modal.media.file_name}`}
          onClose={() => setModal(null)}
          onConfirm={async (targetAlbumId) => {
            await adminService.moveMedia(modal.media.id, targetAlbumId);
            removeItemsAndCloseIfNeeded([modal.media.id]);
            setModal(null);
            showToast("Media moved to the new album.");
          }}
        />
      )}

      {modal?.kind === "bulk-move" && (
        <MoveMediaModal
          albums={allAlbumsForClient.filter((a) => a.id !== albumIdNum)}
          title={`Move ${selectedCount} items`}
          onClose={() => setModal(null)}
          onConfirm={handleBulkMove}
        />
      )}

      {modal?.kind === "confirm-delete" && (
        <Modal
          title={`Delete ${modal.media.file_name}?`}
          description="This permanently removes the original file from storage. This cannot be undone."
          onClose={() => setModal(null)}
        >
          <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginTop: "-0.75rem" }}>
            The thumbnail/poster will also be removed.
          </p>
          <div className="modal-actions">
            <button className="btn-secondary" onClick={() => setModal(null)}>
              Cancel
            </button>
            <DeleteMediaButton
              media={modal.media}
              onDeleted={() => {
                removeItemsAndCloseIfNeeded([modal.media.id]);
                setModal(null);
                showToast("Media deleted.");
              }}
              onError={(msg) => showToast(msg)}
            />
          </div>
        </Modal>
      )}

      {modal?.kind === "bulk-confirm-delete" && (
        <Modal
          title={`Delete ${selectedCount} items?`}
          description="This permanently removes the original files (and their thumbnails/posters) from storage. This cannot be undone."
          onClose={() => setModal(null)}
        >
          <div className="modal-actions">
            <button className="btn-secondary" onClick={() => setModal(null)} disabled={bulkBusy}>
              Cancel
            </button>
            <button
              className="btn-primary"
              style={{ background: "var(--danger)" }}
              onClick={handleBulkDelete}
              disabled={bulkBusy}
            >
              {bulkBusy ? "Deleting..." : `Delete ${selectedCount}`}
            </button>
          </div>
        </Modal>
      )}

      {downloadJobRequest !== null && (
        <DownloadJobModal
          createJob={() =>
            adminService.createAlbumDownloadJob(
              albumIdNum,
              downloadJobRequest === "all" ? undefined : downloadJobRequest
            )
          }
          pollStatus={(jobId) => adminService.getDownloadJobStatus(jobId)}
          cancelJob={(jobId) => adminService.cancelDownloadJob(jobId)}
          fileUrl={adminService.downloadJobFileUrl}
          onClose={() => setDownloadJobRequest(null)}
        />
      )}

      {toast && <div className="toast">{toast}</div>}
    </AdminLayout>
  );
}

function AlbumExpiryControl({ album, onSaved }: { album: AlbumItem; onSaved: (updated: AlbumItem) => void }) {
  const [value, setValue] = useState(album.expires_at ? album.expires_at.slice(0, 10) : "");
  const [submitting, setSubmitting] = useState(false);
  const expiry = getExpiryInfo(album.expires_at);

  async function handleSave() {
    setSubmitting(true);
    try {
      const updated = await adminService.updateAlbum(album.id, {
        expires_at: value ? new Date(value + "T23:59:59").toISOString() : null,
      });
      onSaved(updated);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
      {expiry && (
        <span
          className={
            "expiry-badge " +
            (expiry.isExpired ? "expiry-badge--expired" : expiry.isNearExpiry ? "expiry-badge--warning" : "expiry-badge--normal")
          }
        >
          {expiry.label}
        </span>
      )}
      <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.82rem", color: "var(--text-muted)" }}>
        Expiry date
        <input
          type="date"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          style={{
            background: "var(--bg)",
            border: "1px solid var(--hairline)",
            color: "var(--text)",
            padding: "0.35rem 0.5rem",
            borderRadius: "6px",
            fontSize: "0.82rem",
          }}
        />
      </label>
      <button className="btn-text" onClick={handleSave} disabled={submitting}>
        {submitting ? "Saving..." : "Save"}
      </button>
      {album.expires_at && (
        <button
          className="btn-text"
          onClick={() => {
            setValue("");
            adminService.updateAlbum(album.id, { expires_at: null }).then(onSaved);
          }}
          disabled={submitting}
        >
          Clear
        </button>
      )}
    </div>
  );
}

function EditMediaModal({
  media,
  onClose,
  onSaved,
}: {
  media: MediaItem;
  onClose: () => void;
  onSaved: (updated: MediaItem) => void;
}) {
  const [fileName, setFileName] = useState(media.file_name);
  const [title, setTitle] = useState(media.title ?? "");
  const [description, setDescription] = useState(media.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const updated = await adminService.updateMedia(media.id, {
        file_name: fileName,
        title,
        description,
      });
      onSaved(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save changes.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="Edit media" onClose={onClose}>
      <form onSubmit={handleSubmit}>
        {error && <p className="auth-error">{error}</p>}
        <label>
          Filename
          <input value={fileName} onChange={(e) => setFileName(e.target.value)} required autoFocus />
        </label>
        <label>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Optional" />
        </label>
        <label>
          Description
          <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional" />
        </label>
        <p style={{ color: "var(--text-muted)", fontSize: "0.78rem" }}>
          {media.file_type === "photo" ? "Photo" : "Video"} · {formatBytes(media.file_size)}
        </p>
        <div className="modal-actions">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? "Saving..." : "Save changes"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function MoveMediaModal({
  albums,
  title,
  onClose,
  onConfirm,
}: {
  albums: AlbumItem[];
  title: string;
  onClose: () => void;
  onConfirm: (targetAlbumId: number) => Promise<void>;
}) {
  const [targetAlbumId, setTargetAlbumId] = useState<number | null>(albums[0]?.id ?? null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!targetAlbumId) return;
    setError(null);
    setSubmitting(true);
    try {
      await onConfirm(targetAlbumId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to move media.");
    } finally {
      setSubmitting(false);
    }
  }

  if (albums.length === 0) {
    return (
      <Modal title={title} onClose={onClose}>
        <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
          This client has no other albums to move into.
        </p>
        <div className="modal-actions">
          <button className="btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title={title} description="Media can only be moved to another album belonging to the same client." onClose={onClose}>
      <form onSubmit={handleSubmit}>
        {error && <p className="auth-error">{error}</p>}
        <label>
          Target album
          <select
            value={targetAlbumId ?? ""}
            onChange={(e) => setTargetAlbumId(Number(e.target.value))}
            style={{
              background: "var(--bg)",
              border: "1px solid var(--hairline)",
              color: "var(--text)",
              padding: "0.55rem 0.7rem",
              borderRadius: "6px",
              fontSize: "0.9rem",
            }}
          >
            {albums.map((a) => (
              <option key={a.id} value={a.id}>
                {a.album_name}
              </option>
            ))}
          </select>
        </label>
        <div className="modal-actions">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? "Moving..." : "Move"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function DeleteMediaButton({
  media,
  onDeleted,
  onError,
}: {
  media: MediaItem;
  onDeleted: () => void;
  onError: (message: string) => void;
}) {
  const [submitting, setSubmitting] = useState(false);

  async function handleDelete() {
    setSubmitting(true);
    try {
      await adminService.removeMedia(media.id);
      onDeleted();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Delete failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <button
      className="btn-primary"
      style={{ background: "var(--danger)" }}
      onClick={handleDelete}
      disabled={submitting}
    >
      {submitting ? "Deleting..." : "Delete"}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Row Actions Menu (portal) – mirrors Clients.tsx pattern            */
/* ------------------------------------------------------------------ */

// Rendered into <body> via a portal so the fixed-position menu can never
// be clipped by any parent overflow container, and flipped upward when it
// would run past the bottom of the viewport.
function RowActionsMenu({
  anchorRef,
  menuRef,
  children,
}: {
  anchorRef: { readonly current: HTMLElement | null };
  menuRef: { readonly current: HTMLDivElement | null };
  children: ReactNode;
}) {
  const [pos, setPos] = useState<CSSProperties>({
    position: "fixed",
    top: -9999,
    left: -9999,
  });

  useLayoutEffect(() => {
    function position() {
      const anchor = anchorRef.current;
      const el = menuRef.current;
      if (!anchor || !el) return;
      const rect = anchor.getBoundingClientRect();
      const height = el.offsetHeight;
      const gap = 6;
      const right = window.innerWidth - rect.right;
      const fitsBelow = rect.bottom + gap + height <= window.innerHeight;
      const fitsAbove = rect.top - gap - height >= 8;
      if (!fitsBelow && fitsAbove) {
        setPos({
          position: "fixed",
          right,
          top: "auto",
          bottom: window.innerHeight - rect.top + gap,
        });
      } else {
        setPos({
          position: "fixed",
          right,
          top: rect.bottom + gap,
          bottom: "auto",
        });
      }
    }
    position();
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    return () => {
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
    };
  }, [anchorRef, menuRef]);

  return createPortal(
    <div className="row-actions__menu" role="menu" ref={menuRef} style={pos}>
      {children}
    </div>,
    document.body
  );
}
