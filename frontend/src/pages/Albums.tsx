import {
  FormEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import AdminLayout from "../components/AdminLayout";
import DownloadJobModal from "../components/DownloadJobModal";
import MenuIcon from "../components/MenuIcon";
import Modal from "../components/Modal";
import { adminService, AlbumItem, ClientListItem } from "../services/admin";
import { getExpiryInfo } from "../utils/format";

type StatusFilter = "all" | "active" | "expiring_soon" | "expired" | "with_media";
type SortOption =
  | "created_desc"
  | "created_asc"
  | "name_asc"
  | "name_desc"
  | "media_desc"
  | "media_asc"
  | "expiry_asc";

export default function Albums() {
  const navigate = useNavigate();
  const [albums, setAlbums] = useState<AlbumItem[]>([]);
  const [clients, setClients] = useState<ClientListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modals state
  const [showCreate, setShowCreate] = useState(false);
  const [editingAlbum, setEditingAlbum] = useState<AlbumItem | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<AlbumItem | null>(null);
  const [downloadJobAlbum, setDownloadJobAlbum] = useState<AlbumItem | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // Filters & View state
  const [search, setSearch] = useState("");
  const [clientFilter, setClientFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sortBy, setSortBy] = useState<SortOption>("created_desc");
  const [viewMode, setViewMode] = useState<"table" | "grid">("table");

  // More Options Menu state
  const [openMenuId, setOpenMenuId] = useState<number | null>(null);
  const menuAnchorRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  function showToast(message: string) {
    setToast(message);
    setTimeout(() => setToast(null), 2800);
  }

  async function loadAll() {
    setLoading(true);
    try {
      const [albumPage, clientPage] = await Promise.all([
        adminService.listAlbums(1, 200),
        adminService.listClients(1, 200),
      ]);
      setAlbums(albumPage.items);
      setClients(clientPage.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load albums.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  // Close menu on click outside or Escape
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

  const closeMenu = useCallback(() => {
    setOpenMenuId(null);
  }, []);

  const openMenu = useCallback((id: number) => {
    setOpenMenuId((cur) => (cur === id ? null : id));
  }, []);

  function clientForAlbum(clientId: number): ClientListItem | undefined {
    return clients.find((c) => c.id === clientId);
  }

  function clientName(clientId: number): string {
    return clientForAlbum(clientId)?.client_name ?? `Client #${clientId}`;
  }

  async function handleDelete(album: AlbumItem) {
    try {
      await adminService.removeAlbum(album.id);
      showToast(`Album "${album.album_name}" deleted.`);
      setConfirmDelete(null);
      loadAll();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Delete failed.");
    }
  }

  async function handleCopyGalleryLink(album: AlbumItem) {
    closeMenu();
    const client = clientForAlbum(album.client_id);
    if (!client) {
      showToast("Client not found for this album.");
      return;
    }
    // Direct album gallery link
    const url = `${window.location.origin}/gallery/${client.client_uuid}/view/${album.id}`;
    try {
      await navigator.clipboard.writeText(url);
      showToast("Gallery link copied to clipboard.");
    } catch {
      showToast(url);
    }
  }

  // Summary Metrics
  const stats = useMemo(() => {
    const totalAlbums = albums.length;
    const totalMedia = albums.reduce((acc, a) => acc + (a.media_count || 0), 0);
    // Each album arrives with its own photo/video split (aggregated in SQL by
    // the album list endpoint), so the media card can show the breakdown
    // without a second request - and without guessing from media_count.
    const totalPhotos = albums.reduce((acc, a) => acc + (a.photo_count || 0), 0);
    const totalVideos = albums.reduce((acc, a) => acc + (a.video_count || 0), 0);
    const uniqueClientIds = new Set(albums.map((a) => a.client_id));
    const expiringOrExpired = albums.filter((a) => {
      const expiry = getExpiryInfo(a.expires_at);
      return expiry && (expiry.isExpired || expiry.isNearExpiry);
    }).length;

    return {
      totalAlbums,
      totalMedia,
      totalPhotos,
      totalVideos,
      activeClients: uniqueClientIds.size,
      expiringOrExpired,
    };
  }, [albums]);

  // Filtered and Sorted Albums
  const filteredAlbums = useMemo(() => {
    let result = [...albums];
    const q = search.toLowerCase().trim();

    // Text search
    if (q) {
      result = result.filter((a) => {
        const nameMatch = a.album_name.toLowerCase().includes(q);
        const descMatch = a.description ? a.description.toLowerCase().includes(q) : false;
        const client = clientName(a.client_id).toLowerCase();
        return nameMatch || descMatch || client.includes(q);
      });
    }

    // Client filter
    if (clientFilter !== "all") {
      const targetClientId = Number(clientFilter);
      result = result.filter((a) => a.client_id === targetClientId);
    }

    // Status filter
    if (statusFilter !== "all") {
      result = result.filter((a) => {
        const expiry = getExpiryInfo(a.expires_at);
        if (statusFilter === "active") {
          return !expiry || !expiry.isExpired;
        }
        if (statusFilter === "expiring_soon") {
          return expiry !== null && expiry.isNearExpiry;
        }
        if (statusFilter === "expired") {
          return expiry !== null && expiry.isExpired;
        }
        if (statusFilter === "with_media") {
          return (a.media_count || 0) > 0;
        }
        return true;
      });
    }

    // Sorting
    result.sort((a, b) => {
      if (sortBy === "name_asc") return a.album_name.localeCompare(b.album_name);
      if (sortBy === "name_desc") return b.album_name.localeCompare(a.album_name);
      if (sortBy === "created_asc") return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      if (sortBy === "created_desc") return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      if (sortBy === "media_desc") return (b.media_count || 0) - (a.media_count || 0);
      if (sortBy === "media_asc") return (a.media_count || 0) - (b.media_count || 0);
      if (sortBy === "expiry_asc") {
        if (!a.expires_at) return 1;
        if (!b.expires_at) return -1;
        return new Date(a.expires_at).getTime() - new Date(b.expires_at).getTime();
      }
      return 0;
    });

    return result;
  }, [albums, clients, search, clientFilter, statusFilter, sortBy]);

  const hasActiveFilters = search !== "" || clientFilter !== "all" || statusFilter !== "all";

  function clearFilters() {
    setSearch("");
    setClientFilter("all");
    setStatusFilter("all");
    setSortBy("created_desc");
  }

  function renderStatusPill(expiresAt: string | null) {
    const expiry = getExpiryInfo(expiresAt);
    if (!expiry) {
      return <span className="album-status-pill album-status-pill--neutral">No expiry</span>;
    }
    if (expiry.isExpired) {
      return (
        <span className="album-status-pill album-status-pill--danger" title={expiry.label}>
          ● Expired
        </span>
      );
    }
    if (expiry.isNearExpiry) {
      return (
        <span className="album-status-pill album-status-pill--warning" title={expiry.label}>
          ⚠ {expiry.daysUntil}d left
        </span>
      );
    }
    return (
      <span className="album-status-pill album-status-pill--active" title={expiry.label}>
        ● Active ({expiry.daysUntil}d)
      </span>
    );
  }

  return (
    <AdminLayout>
      <div className="section-header">
        <div>
          <h1 className="admin-page-title" style={{ margin: 0 }}>
            Albums
          </h1>
          <p className="admin-page-subtitle" style={{ margin: "0.25rem 0 0" }}>
            Organize each client's gallery into albums, manage media, and set expiry policies.
          </p>
        </div>

        <div className="albums-header-actions">
          <button
            className="btn-primary"
            onClick={() => setShowCreate(true)}
            disabled={clients.length === 0}
            title={clients.length === 0 ? "Create a client first" : undefined}
          >
            + New album
          </button>
        </div>
      </div>

      {error && <p className="auth-error">{error}</p>}

      {/* KPI Metric Cards */}
      <div className="admin-kpi-grid admin-kpi-grid--4col">
        <div className="admin-kpi-card">
          <div className="admin-kpi-card__top">
            <div className="admin-kpi-icon-box admin-kpi-icon-box--amber">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" strokeWidth="1.8" />
              </svg>
            </div>
            <div className="admin-kpi-content">
              <div className="admin-kpi-value">{loading ? "…" : stats.totalAlbums}</div>
              <div className="admin-kpi-label">Total Albums</div>
              <div className="admin-kpi-subtext">Across all client galleries</div>
            </div>
          </div>
        </div>

        <div className="admin-kpi-card">
          <div className="admin-kpi-card__top">
            <div className="admin-kpi-icon-box admin-kpi-icon-box--blue">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <rect x="3" y="3" width="18" height="18" rx="3" strokeWidth="1.8" />
                <circle cx="8.5" cy="8.5" r="1.5" fill="currentColor" />
                <path d="M21 15l-5-5L5 21" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="admin-kpi-content">
              <div className="admin-kpi-value">{loading ? "…" : stats.totalMedia.toLocaleString()}</div>
              <div className="admin-kpi-label">Total Media Files</div>
              <div className="admin-kpi-subtext">
                {loading
                  ? "Photos & video assets"
                  : `${stats.totalPhotos.toLocaleString()} photos · ${stats.totalVideos.toLocaleString()} videos`}
              </div>
            </div>
          </div>
        </div>

        <div className="admin-kpi-card">
          <div className="admin-kpi-card__top">
            <div className="admin-kpi-icon-box admin-kpi-icon-box--rose">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" strokeWidth="1.8" strokeLinecap="round" />
                <circle cx="9" cy="7" r="4" strokeWidth="1.8" />
                <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </div>
            <div className="admin-kpi-content">
              <div className="admin-kpi-value">{loading ? "…" : stats.activeClients}</div>
              <div className="admin-kpi-label">Active Clients</div>
              <div className="admin-kpi-subtext">With provisioned albums</div>
            </div>
          </div>
        </div>

        <div className="admin-kpi-card">
          <div className="admin-kpi-card__top">
            <div
              className={
                "admin-kpi-icon-box " +
                (stats.expiringOrExpired > 0 ? "admin-kpi-icon-box--coral" : "admin-kpi-icon-box--green")
              }
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <circle cx="12" cy="12" r="10" strokeWidth="1.8" />
                <polyline points="12 6 12 12 16 14" strokeWidth="1.8" />
              </svg>
            </div>
            <div className="admin-kpi-content">
              <div className="admin-kpi-value">{loading ? "…" : stats.expiringOrExpired}</div>
              <div className="admin-kpi-label">Expiring / Expired</div>
              <div className="admin-kpi-subtext">
                {stats.expiringOrExpired > 0 ? "Requires review" : "All albums healthy"}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Filter and Search Toolbar */}
      {albums.length > 0 && (
        <div className="albums-toolbar">
          {/* Row 1: Search + Client filter */}
          <div className="albums-toolbar__row albums-toolbar__row--search">
            {/* Search box */}
            <div className="albums-search">
              <span className="search-icon">⌕</span>
              <input
                className="search-input"
                type="text"
                placeholder="Search albums, clients…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            {/* Client Filter Dropdown */}
            <select
              className="albums-client-select"
              value={clientFilter}
              onChange={(e) => setClientFilter(e.target.value)}
              title="Filter by client"
            >
              <option value="all">All Clients ({clients.length})</option>
              {clients.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.client_name}
                </option>
              ))}
            </select>
          </div>

          {/* Row 2: Status filters + Sort + View toggle + Count */}
          <div className="albums-toolbar__row albums-toolbar__row--filters">
            {/* Status Segmented Buttons */}
            <div className="filter-group">
              {[
                { id: "all", label: "All" },
                { id: "active", label: "Active" },
                { id: "expiring_soon", label: "Expiring" },
                { id: "expired", label: "Expired" },
                { id: "with_media", label: "Has Media" },
              ].map((tab) => (
                <button
                  key={tab.id}
                  className={"filter-btn" + (statusFilter === tab.id ? " filter-btn--active" : "")}
                  onClick={() => setStatusFilter(tab.id as StatusFilter)}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <div className="albums-toolbar__controls">
              {/* Sort Dropdown */}
              <select
                className="sort-select"
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as SortOption)}
                title="Sort order"
              >
                <option value="created_desc">Newest</option>
                <option value="created_asc">Oldest</option>
                <option value="name_asc">Name A–Z</option>
                <option value="name_desc">Name Z–A</option>
                <option value="media_desc">Most files</option>
                <option value="media_asc">Fewest files</option>
                <option value="expiry_asc">Soonest expiring</option>
              </select>

              {/* View Mode Switcher */}
              <div className="view-mode-toggle" title="Switch layout">
                <button
                  type="button"
                  className={"view-mode-btn" + (viewMode === "table" ? " view-mode-btn--active" : "")}
                  onClick={() => setViewMode("table")}
                  title="Table view"
                  aria-label="Table view"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="3" y1="6" x2="21" y2="6" />
                    <line x1="3" y1="12" x2="21" y2="12" />
                    <line x1="3" y1="18" x2="21" y2="18" />
                  </svg>
                </button>
                <button
                  type="button"
                  className={"view-mode-btn" + (viewMode === "grid" ? " view-mode-btn--active" : "")}
                  onClick={() => setViewMode("grid")}
                  title="Grid card view"
                  aria-label="Grid card view"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="3" y="3" width="7" height="7" />
                    <rect x="14" y="3" width="7" height="7" />
                    <rect x="14" y="14" width="7" height="7" />
                    <rect x="3" y="14" width="7" height="7" />
                  </svg>
                </button>
              </div>

              {/* Clear Filters */}
              {hasActiveFilters && (
                <button className="clear-filters-btn" onClick={clearFilters}>
                  Clear
                </button>
              )}

              {/* Count Badge */}
              <span className="filter-count">
                {filteredAlbums.length} / {albums.length}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Initial Empty State */}
      {!loading && albums.length === 0 && (
        <div className="empty-state">
          {clients.length === 0
            ? "Create a client first, then create albums to hold their photos and videos."
            : "No albums yet. Click '+ New album' above to get started."}
        </div>
      )}

      {/* Filtered Empty State */}
      {!loading && albums.length > 0 && filteredAlbums.length === 0 && (
        <div className="empty-state">
          <p style={{ margin: "0 0 0.5rem" }}>No albums match your search or selected filters.</p>
          <button className="btn-secondary" onClick={clearFilters} style={{ fontSize: "0.85rem" }}>
            Reset all filters
          </button>
        </div>
      )}

      {/* TABLE VIEW */}
      {filteredAlbums.length > 0 && viewMode === "table" && (
        <div className="table-scroll">
          <table className="client-table">
            <thead>
              <tr>
                <th>Album</th>
                <th>Client</th>
                <th>Files</th>
                <th>Expiry Status</th>
                <th>Created</th>
                <th style={{ textAlign: "right" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredAlbums.map((a) => (
                <tr key={a.id}>
                  <td>
                    <div style={{ display: "flex", flexDirection: "column", gap: "0.2rem" }}>
                      <button
                        className="btn-text"
                        style={{
                          color: "var(--text)",
                          fontWeight: 600,
                          fontSize: "0.92rem",
                          textAlign: "left",
                          padding: 0,
                        }}
                        onClick={() => navigate(`/admin/albums/${a.id}`)}
                      >
                        {a.album_name}
                      </button>
                      {a.description && (
                        <span
                          style={{
                            fontSize: "0.78rem",
                            color: "var(--text-muted)",
                            maxWidth: "280px",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {a.description}
                        </span>
                      )}
                    </div>
                  </td>
                  <td>
                    <span className="album-client-tag">{clientName(a.client_id)}</span>
                  </td>
                  <td>
                    <span className="album-media-badge">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                        <rect x="3" y="3" width="18" height="18" rx="2" strokeWidth="2" />
                        <circle cx="8.5" cy="8.5" r="1.5" fill="currentColor" />
                        <path d="M21 15l-5-5L5 21" strokeWidth="2" />
                      </svg>
                      {a.media_count}
                    </span>
                  </td>
                  <td>{renderStatusPill(a.expires_at)}</td>
                  <td>{new Date(a.created_at).toLocaleDateString()}</td>
                  <td>
                    <div className="row-actions" style={{ justifyContent: "flex-end" }}>
                      <button
                        className="btn-text"
                        style={{ fontSize: "0.82rem", color: "var(--accent)" }}
                        onClick={() => navigate(`/admin/albums/${a.id}`)}
                      >
                        View media
                      </button>

                      {/* More Options (⋯) Button */}
                      <button
                        className="row-actions__trigger"
                        ref={openMenuId === a.id ? menuAnchorRef : undefined}
                        aria-haspopup="menu"
                        aria-expanded={openMenuId === a.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          openMenu(a.id);
                        }}
                        title="More options"
                        aria-label="More options"
                      >
                        <MenuIcon name="more" size={18} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* GRID / CARD VIEW */}
      {filteredAlbums.length > 0 && viewMode === "grid" && (
        <div className="albums-grid">
          {filteredAlbums.map((a) => (
            <div key={a.id} className="album-card">
              <div className="album-card__top">
                <div className="album-card__icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" strokeWidth="1.8" />
                  </svg>
                </div>

                <div className="album-card__header-badges">
                  <span className="album-client-tag">{clientName(a.client_id)}</span>
                  {renderStatusPill(a.expires_at)}
                </div>

                {/* More Options Button */}
                <button
                  className="row-actions__trigger"
                  style={{ marginLeft: "auto" }}
                  ref={openMenuId === a.id ? menuAnchorRef : undefined}
                  aria-haspopup="menu"
                  aria-expanded={openMenuId === a.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    openMenu(a.id);
                  }}
                  title="More options"
                  aria-label="More options"
                >
                  <MenuIcon name="more" size={18} />
                </button>
              </div>

              <button
                className="album-card__title"
                onClick={() => navigate(`/admin/albums/${a.id}`)}
                title={`Open ${a.album_name}`}
              >
                {a.album_name}
              </button>

              <div className="album-card__desc">
                {a.description || "No description provided."}
              </div>

              <div className="album-card__footer">
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <span className="album-media-badge">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                      <rect x="3" y="3" width="18" height="18" rx="2" strokeWidth="2" />
                      <circle cx="8.5" cy="8.5" r="1.5" fill="currentColor" />
                      <path d="M21 15l-5-5L5 21" strokeWidth="2" />
                    </svg>
                    {a.media_count} files
                  </span>
                  <span>{new Date(a.created_at).toLocaleDateString()}</span>
                </div>

                <button
                  className="btn-text"
                  style={{ fontSize: "0.82rem", color: "var(--accent)" }}
                  onClick={() => navigate(`/admin/albums/${a.id}`)}
                >
                  View media →
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* PORTAL ROW ACTIONS MENU */}
      {openMenuId !== null && (
        (() => {
          const activeAlbum = albums.find((a) => a.id === openMenuId);
          if (!activeAlbum) return null;

          return (
            <RowActionsMenu anchorRef={menuAnchorRef} menuRef={menuRef}>
              <button
                className="row-actions__item"
                role="menuitem"
                onClick={() => {
                  closeMenu();
                  navigate(`/admin/albums/${activeAlbum.id}`);
                }}
              >
                <MenuIcon name="image" />
                View media files
              </button>

              <button
                className="row-actions__item"
                role="menuitem"
                onClick={() => {
                  closeMenu();
                  setEditingAlbum(activeAlbum);
                }}
              >
                <MenuIcon name="pencil" />
                Edit album details
              </button>

              <button
                className="row-actions__item"
                role="menuitem"
                onClick={() => handleCopyGalleryLink(activeAlbum)}
              >
                <MenuIcon name="link" />
                Copy gallery link
              </button>

              <button
                className="row-actions__item"
                role="menuitem"
                onClick={() => {
                  closeMenu();
                  setDownloadJobAlbum(activeAlbum);
                }}
              >
                <MenuIcon name="download" />
                Download album as ZIP
              </button>

              <div className="row-actions__separator" role="separator" />

              <button
                className="row-actions__item row-actions__item--danger"
                role="menuitem"
                onClick={() => {
                  closeMenu();
                  setConfirmDelete(activeAlbum);
                }}
              >
                <MenuIcon name="trash" />
                Delete album
              </button>
            </RowActionsMenu>
          );
        })()
      )}

      {/* CREATE ALBUM MODAL */}
      {showCreate && (
        <CreateAlbumModal
          clients={clients}
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            showToast("Album created successfully.");
            loadAll();
          }}
        />
      )}

      {/* EDIT ALBUM MODAL */}
      {editingAlbum && (
        <EditAlbumModal
          album={editingAlbum}
          clientName={clientName(editingAlbum.client_id)}
          onClose={() => setEditingAlbum(null)}
          onUpdated={() => {
            setEditingAlbum(null);
            showToast("Album updated.");
            loadAll();
          }}
        />
      )}

      {/* DELETE CONFIRMATION MODAL */}
      {confirmDelete && (
        <Modal
          title={`Delete ${confirmDelete.album_name}?`}
          description={`This permanently removes the album and its media references for ${clientName(
            confirmDelete.client_id
          )}. This action cannot be undone.`}
          onClose={() => setConfirmDelete(null)}
        >
          <div className="modal-actions">
            <button className="btn-secondary" onClick={() => setConfirmDelete(null)}>
              Cancel
            </button>
            <button
              className="btn-primary"
              style={{ background: "var(--danger)" }}
              onClick={() => handleDelete(confirmDelete)}
            >
              Delete Album
            </button>
          </div>
        </Modal>
      )}

      {/* DOWNLOAD ALBUM ZIP MODAL */}
      {downloadJobAlbum && (
        <DownloadJobModal
          createJob={() => adminService.createAlbumDownloadJob(downloadJobAlbum.id)}
          pollStatus={(jobId) => adminService.getDownloadJobStatus(jobId)}
          cancelJob={(jobId) => adminService.cancelDownloadJob(jobId)}
          fileUrl={adminService.downloadJobFileUrl}
          onClose={() => setDownloadJobAlbum(null)}
        />
      )}

      {toast && <div className="toast">{toast}</div>}
    </AdminLayout>
  );
}

// ---------------------------------------------------------------------------
// RowActionsMenu Portal
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// Create Album Modal
// ---------------------------------------------------------------------------
function CreateAlbumModal({
  clients,
  onClose,
  onCreated,
}: {
  clients: ClientListItem[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [clientId, setClientId] = useState<number>(clients[0]?.id ?? 0);
  const [albumName, setAlbumName] = useState("");
  const [description, setDescription] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function applyPresetDays(days: number) {
    const d = new Date();
    d.setDate(d.getDate() + days);
    setExpiresAt(d.toISOString().slice(0, 10));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const expiryIso = expiresAt ? new Date(expiresAt + "T23:59:59Z").toISOString() : null;
      await adminService.createAlbum(
        clientId,
        albumName,
        description.trim() || undefined,
        expiryIso
      );
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create album.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="New album" onClose={onClose}>
      <form onSubmit={handleSubmit}>
        {error && <p className="auth-error">{error}</p>}
        <label>
          Client
          <select
            value={clientId}
            onChange={(e) => setClientId(Number(e.target.value))}
            style={{
              background: "var(--bg)",
              border: "1px solid var(--hairline)",
              color: "var(--text)",
              padding: "0.55rem 0.7rem",
              borderRadius: "6px",
              fontSize: "0.9rem",
            }}
          >
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.client_name}
              </option>
            ))}
          </select>
        </label>

        <label>
          Album name
          <input
            value={albumName}
            onChange={(e) => setAlbumName(e.target.value)}
            required
            autoFocus
            placeholder="e.g. Wedding Ceremony, Reception, Portraits"
          />
        </label>

        <label>
          Description (optional)
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Brief notes about this album"
          />
        </label>

        <label>
          Gallery Expiry Date (optional)
          <input
            type="date"
            value={expiresAt}
            onChange={(e) => setExpiresAt(e.target.value)}
          />
        </label>

        <div className="expiry-presets">
          <button type="button" className="expiry-preset-btn" onClick={() => applyPresetDays(30)}>
            +30 Days
          </button>
          <button type="button" className="expiry-preset-btn" onClick={() => applyPresetDays(90)}>
            +90 Days
          </button>
          <button type="button" className="expiry-preset-btn" onClick={() => applyPresetDays(365)}>
            +1 Year
          </button>
          {expiresAt && (
            <button
              type="button"
              className="expiry-preset-btn"
              style={{ color: "var(--danger)" }}
              onClick={() => setExpiresAt("")}
            >
              Clear Expiry
            </button>
          )}
        </div>

        <div className="modal-actions">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? "Creating…" : "Create album"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Edit Album Modal
// ---------------------------------------------------------------------------
function EditAlbumModal({
  album,
  clientName,
  onClose,
  onUpdated,
}: {
  album: AlbumItem;
  clientName: string;
  onClose: () => void;
  onUpdated: () => void;
}) {
  const [albumName, setAlbumName] = useState(album.album_name);
  const [description, setDescription] = useState(album.description ?? "");
  const [expiresAt, setExpiresAt] = useState(album.expires_at ? album.expires_at.slice(0, 10) : "");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function applyPresetDays(days: number) {
    const d = new Date();
    d.setDate(d.getDate() + days);
    setExpiresAt(d.toISOString().slice(0, 10));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const expiryIso = expiresAt ? new Date(expiresAt + "T23:59:59Z").toISOString() : null;
      await adminService.updateAlbum(album.id, {
        album_name: albumName.trim(),
        description: description.trim() || undefined,
        expires_at: expiryIso,
      });
      onUpdated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update album.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title={`Edit ${album.album_name}`} onClose={onClose}>
      <form onSubmit={handleSubmit}>
        {error && <p className="auth-error">{error}</p>}

        <p style={{ margin: "0 0 1rem", fontSize: "0.85rem", color: "var(--text-muted)" }}>
          Client: <strong style={{ color: "var(--text)" }}>{clientName}</strong>
        </p>

        <label>
          Album name
          <input
            value={albumName}
            onChange={(e) => setAlbumName(e.target.value)}
            required
            autoFocus
          />
        </label>

        <label>
          Description (optional)
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Brief notes about this album"
          />
        </label>

        <label>
          Gallery Expiry Date
          <input
            type="date"
            value={expiresAt}
            onChange={(e) => setExpiresAt(e.target.value)}
          />
        </label>

        <div className="expiry-presets">
          <button type="button" className="expiry-preset-btn" onClick={() => applyPresetDays(30)}>
            +30 Days
          </button>
          <button type="button" className="expiry-preset-btn" onClick={() => applyPresetDays(90)}>
            +90 Days
          </button>
          <button type="button" className="expiry-preset-btn" onClick={() => applyPresetDays(365)}>
            +1 Year
          </button>
          {expiresAt && (
            <button
              type="button"
              className="expiry-preset-btn"
              style={{ color: "var(--danger)" }}
              onClick={() => setExpiresAt("")}
            >
              Never expires (Clear)
            </button>
          )}
        </div>

        <div className="modal-actions">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? "Saving…" : "Save changes"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
