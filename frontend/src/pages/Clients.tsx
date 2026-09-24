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
import AdminLayout from "../components/AdminLayout";
import MenuIcon from "../components/MenuIcon";
import Modal from "../components/Modal";
import { adminService, ClientDetail, ClientListItem } from "../services/admin";

type ModalState =
  | { kind: "create" }
  | { kind: "manage-passwords"; client: ClientListItem }
  | { kind: "confirm-delete"; client: ClientListItem }
  | { kind: "view-client"; client: ClientListItem }
  | { kind: "edit-client"; client: ClientListItem }
  | null;

type SortKey = "name" | "created";

export default function Clients() {
  const [clients, setClients] = useState<ClientListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [openMenuId, setOpenMenuId] = useState<number | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuAnchorRef = useRef<HTMLButtonElement>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "active" | "disabled">("all");
  const [sortBy, setSortBy] = useState<SortKey>("created");

  // Admin-configurable minimum (Settings > Security & download policy).
  // Defaults to 4 - the floor the policy itself enforces - so the forms
  // below render with a sane constraint even before this loads.
  const [minPasswordLength, setMinPasswordLength] = useState(4);

  function showToast(message: string) {
    setToast(message);
    setTimeout(() => setToast(null), 2500);
  }

  async function loadClients() {
    setLoading(true);
    try {
      const page = await adminService.listClients();
      setClients(page.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load clients.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadClients();
    adminService
      .getSettings()
      .then((res) => setMinPasswordLength(res.studio.min_client_password_length))
      .catch(() => {
        // Non-critical - the forms just fall back to the default floor of 4.
      });
  }, []);

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

  const filtered = useMemo(() => {
    let list = clients;
    const q = search.toLowerCase().trim();
    if (q) {
      list = list.filter(
        (c) =>
          c.client_name.toLowerCase().includes(q) ||
          c.client_uuid.toLowerCase().includes(q)
      );
    }
    if (statusFilter !== "all") {
      list = list.filter((c) => c.status === statusFilter);
    }
    return [...list].sort((a, b) => {
      if (sortBy === "name") return a.client_name.localeCompare(b.client_name);
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
  }, [clients, search, statusFilter, sortBy]);

  const hasActiveFilters = search !== "" || statusFilter !== "all";

  function clearFilters() {
    setSearch("");
    setStatusFilter("all");
  }

  async function handleCopyUrl(clientUuid: string) {
    const url = `${window.location.origin}/gallery/${clientUuid}`;
    try {
      await navigator.clipboard.writeText(url);
      showToast("Gallery link copied.");
    } catch {
      showToast(url);
    }
    setOpenMenuId(null);
  }

  async function handleToggleStatus(c: ClientListItem) {
    setOpenMenuId(null);
    try {
      if (c.status === "active") {
        await adminService.disableClient(c.id);
        showToast(`${c.client_name} disabled.`);
      } else {
        await adminService.enableClient(c.id);
        showToast(`${c.client_name} enabled.`);
      }
      loadClients();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Action failed.");
    }
  }

  async function handleDelete(c: ClientListItem) {
    try {
      await adminService.removeClient(c.id);
      showToast(`${c.client_name} deleted.`);
      setModal(null);
      loadClients();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Delete failed.");
    }
  }

  function formatDate(iso: string) {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }

  function closeMenu() {
    setOpenMenuId(null);
  }

  const openMenu = useCallback(
    (id: number) => {
      setOpenMenuId((cur) => (cur === id ? null : id));
    },
    []
  );

  return (
    <AdminLayout>
      <h1 className="admin-page-title">Clients</h1>
      <p className="admin-page-subtitle">
        Create private galleries and manage access.
      </p>

      <div className="section-header">
        <h2>All clients</h2>
        <button
          className="btn-primary"
          onClick={() => setModal({ kind: "create" })}
        >
          New client
        </button>
      </div>

      {error && <p className="auth-error">{error}</p>}

      {!loading && clients.length === 0 && (
        <div className="empty-state">
          No clients yet. Create your first client above.
        </div>
      )}

      {clients.length > 0 && (
        <>
          <div className="clients-toolbar">
            <div className="clients-search">
              <span className="search-icon">⌕</span>
              <input
                className="search-input"
                type="text"
                placeholder="Search clients…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="filter-group">
              {(["all", "active", "disabled"] as const).map((f) => (
                <button
                  key={f}
                  className={"filter-btn" + (statusFilter === f ? " filter-btn--active" : "")}
                  onClick={() => setStatusFilter(f)}
                >
                  {f.charAt(0).toUpperCase() + f.slice(1)}
                </button>
              ))}
            </div>
            <select
              className="sort-select"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as SortKey)}
            >
              <option value="created">Newest first</option>
              <option value="name">Name A–Z</option>
            </select>
            {hasActiveFilters && (
              <button className="clear-filters-btn" onClick={clearFilters}>
                Clear filters
              </button>
            )}
            <span className="filter-count">
              {filtered.length} of {clients.length}
            </span>
          </div>

          {filtered.length === 0 && (
            <div className="empty-state">
              No clients match the current filters.
            </div>
          )}

          {filtered.length > 0 && (
            <div className="table-scroll">
              <table className="client-table">
                <thead>
                  <tr>
                    <th>Client</th>
                    <th>Status</th>
                    <th>Albums</th>
                    <th>Media</th>
                    <th>Download Password</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((c) => (
                    <tr key={c.id}>
                      <td className="client-name-cell">
                        <div className="client-name-text">{c.client_name}</div>
                        <div className="client-uuid">{c.client_uuid}</div>
                      </td>
                      <td>
                        <span className="status-pill">
                          <span
                            className={
                              "status-dot" +
                              (c.status !== "active" ? " status-dot--disabled" : "")
                            }
                          />
                          {c.status === "active" ? "Active" : "Disabled"}
                        </span>
                      </td>
                      <td>{c.album_count}</td>
                      <td>{c.media_count}</td>
                      <td>
                        <span className="status-pill">
                          <span
                            className={
                              "status-dot" +
                              (c.has_download_password ? "" : " status-dot--disabled")
                            }
                          />
                          {c.has_download_password ? "Enabled" : "Not set"}
                        </span>
                      </td>
                      <td>{formatDate(c.created_at)}</td>
                      <td>
                        <div className="row-actions">
                          <button
                            className="copy-link-btn"
                            title="Copy gallery link"
                            onClick={() => handleCopyUrl(c.client_uuid)}
                          >
                            Copy link
                          </button>
                          <button
                            className="row-actions__trigger"
                            ref={openMenuId === c.id ? menuAnchorRef : undefined}
                            aria-haspopup="menu"
                            aria-expanded={openMenuId === c.id}
                            aria-label="More actions"
                            onClick={(e) => {
                              e.stopPropagation();
                              openMenu(c.id);
                            }}
                          >
                            <MenuIcon name="more" size={18} />
                          </button>
                          {openMenuId === c.id && (
                            <RowActionsMenu anchorRef={menuAnchorRef} menuRef={menuRef}>
                              <button
                                className="row-actions__item"
                                role="menuitem"
                                onClick={() => {
                                  closeMenu();
                                  setModal({ kind: "view-client", client: c });
                                }}
                              >
                                <MenuIcon name="eye" />
                                View client
                              </button>
                              <button
                                className="row-actions__item"
                                role="menuitem"
                                onClick={() => {
                                  closeMenu();
                                  window.open(
                                    `/gallery/${c.client_uuid}`,
                                    "_blank"
                                  );
                                }}
                              >
                                <MenuIcon name="external" />
                                View gallery
                              </button>
                              <button
                                className="row-actions__item"
                                role="menuitem"
                                onClick={() => {
                                  closeMenu();
                                  setModal({
                                    kind: "manage-passwords",
                                    client: c,
                                  });
                                }}
                              >
                                <MenuIcon name="key" />
                                Manage passwords
                              </button>
                              <button
                                className="row-actions__item"
                                role="menuitem"
                                onClick={() => {
                                  closeMenu();
                                  setModal({ kind: "edit-client", client: c });
                                }}
                              >
                                <MenuIcon name="pencil" />
                                Edit client
                              </button>
                              <button
                                className="row-actions__item"
                                role="menuitem"
                                onClick={() => handleToggleStatus(c)}
                              >
                                <MenuIcon
                                  name={
                                    c.status === "active" ? "user-x" : "user-check"
                                  }
                                />
                                {c.status === "active"
                                  ? "Disable client"
                                  : "Enable client"}
                              </button>
                              <button
                                className="row-actions__item row-actions__item--danger"
                                role="menuitem"
                                onClick={() => {
                                  closeMenu();
                                  setModal({
                                    kind: "confirm-delete",
                                    client: c,
                                  });
                                }}
                              >
                                <MenuIcon name="trash" />
                                Delete client
                              </button>
                            </RowActionsMenu>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {modal?.kind === "create" && (
        <CreateClientModal
          minPasswordLength={minPasswordLength}
          onClose={() => setModal(null)}
          onCreated={() => {
            setModal(null);
            showToast("Client created.");
            loadClients();
          }}
        />
      )}

      {modal?.kind === "manage-passwords" && (
        <PasswordManagementModal
          client={modal.client}
          minPasswordLength={minPasswordLength}
          onClose={() => setModal(null)}
          onChanged={() => {
            setModal(null);
            showToast("Passwords updated.");
            loadClients();
          }}
        />
      )}

      {modal?.kind === "view-client" && (
        <ClientDetailsModal
          client={modal.client}
          onClose={() => setModal(null)}
          onManagePasswords={(c) => setModal({ kind: "manage-passwords", client: c })}
          onEdit={(c) => setModal({ kind: "edit-client", client: c })}
        />
      )}

      {modal?.kind === "edit-client" && (
        <EditClientModal
          client={modal.client}
          onClose={() => setModal(null)}
          onSaved={() => {
            setModal(null);
            showToast("Client updated.");
            loadClients();
          }}
        />
      )}

      {modal?.kind === "confirm-delete" && (
        <Modal
          title={`Delete ${modal.client.client_name}?`}
          onClose={() => setModal(null)}
        >
          <p className="delete-modal-desc">
            This will permanently remove <strong>{modal.client.client_name}</strong> and
            all associated gallery relationships. The client will no longer be
            able to access their gallery. This action cannot be undone.
          </p>
          <div className="modal-actions">
            <button className="btn-secondary" onClick={() => setModal(null)}>
              Cancel
            </button>
            <button
              className="btn-danger"
              onClick={() => handleDelete(modal.client)}
            >
              Delete client
            </button>
          </div>
        </Modal>
      )}

      {toast && <div className="toast">{toast}</div>}
    </AdminLayout>
  );
}

/* ------------------------------------------------------------------ */
/*  Row Actions Menu (portal)                                          */
/* ------------------------------------------------------------------ */

// Rendered into <body> via a portal so the fixed-position menu can never
// be clipped by the table's overflow-x scroll container, and flipped
// upward when it would run past the bottom of the viewport.
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

/* ------------------------------------------------------------------ */
/*  Create Client Modal                                                */
/* ------------------------------------------------------------------ */

function CreateClientModal({
  minPasswordLength,
  onClose,
  onCreated,
}: {
  minPasswordLength: number;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [downloadPassword, setDownloadPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await adminService.createClient(
        name,
        password ? password.trim() : undefined,
        downloadPassword.trim() ? downloadPassword : undefined
      );
      onCreated();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to create client."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title="New client"
      description="Create a private gallery link for them."
      onClose={onClose}
    >
      <form onSubmit={handleSubmit}>
        {error && <p className="auth-error">{error}</p>}
        <label>
          Client name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            autoFocus
          />
        </label>
        <label>
          Gallery password (optional)
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={minPasswordLength}
            maxLength={64}
            placeholder={`Enter Gallery password  `}
          />
        </label>
        <label>
          Download password (optional)
          <input
            type="password"
            value={downloadPassword}
            onChange={(e) => setDownloadPassword(e.target.value)}
            minLength={minPasswordLength}
            maxLength={64}
            placeholder={`Required before they can download files`}
          />
        </label>
        <div className="modal-actions">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn-primary"
            disabled={submitting}
          >
            {submitting ? "Creating…" : "Create client"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/*  Client Details Modal                                               */
/* ------------------------------------------------------------------ */

function ClientDetailsModal({
  client,
  onClose,
  onManagePasswords,
  onEdit,
}: {
  client: ClientListItem;
  onClose: () => void;
  onManagePasswords: (c: ClientListItem) => void;
  onEdit: (c: ClientListItem) => void;
}) {
  const [detail, setDetail] = useState<ClientDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    adminService
      .getClientDetail(client.id)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error ? err.message : "Failed to load client details."
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client.id]);

  const galleryUrl = `${window.location.origin}/gallery/${client.client_uuid}`;

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(galleryUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  }

  function handleOpenGallery() {
    window.open(`/gallery/${client.client_uuid}`, "_blank");
  }

  function formatDate(iso: string) {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  }

  function formatDateTime(iso: string) {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  return (
    <Modal
      title={client.client_name}
      onClose={onClose}
    >
      <div style={{ marginBottom: "1rem" }}>
        <span className="status-pill">
          <span
            className={
              "status-dot" +
              (client.status !== "active" ? " status-dot--disabled" : "")
            }
          />
          {client.status === "active" ? "Active" : "Disabled"}
        </span>
      </div>

      <div className="detail-section">
        <h4 className="detail-section-title">Gallery</h4>
        <div className="detail-gallery-url">
          <code>{galleryUrl}</code>
        </div>
        <div className="detail-gallery-actions">
          <button
            className="btn-secondary"
            onClick={handleCopy}
            style={{ fontSize: "0.82rem" }}
          >
            {copied ? "Copied" : "Copy link"}
          </button>
          <button
            className="btn-secondary"
            onClick={handleOpenGallery}
            style={{ fontSize: "0.82rem" }}
          >
            Open gallery
          </button>
        </div>
      </div>

      <div className="detail-section">
        <h4 className="detail-section-title">Overview</h4>
        {loading && (
          <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
            Loading…
          </p>
        )}
        {error && (
          <p className="auth-error" style={{ fontSize: "0.85rem" }}>
            {error}
          </p>
        )}
        {!loading && (
          <div className="detail-grid">
            <div>
              <div className="detail-label">Albums</div>
              <div className="detail-value">{client.album_count}</div>
            </div>
            <div>
              <div className="detail-label">Media files</div>
              <div className="detail-value">{client.media_count}</div>
            </div>
            <div>
              <div className="detail-label">Created</div>
              <div className="detail-value">
                {formatDate(client.created_at)}
              </div>
            </div>
            <div>
              <div className="detail-label">Last login</div>
              <div className="detail-value">
                {detail?.last_login_at
                  ? formatDateTime(detail.last_login_at)
                  : "Never"}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="detail-section">
        <h4 className="detail-section-title">Security</h4>
        <div className="detail-grid">
          <div>
            <div className="detail-label">Gallery password</div>
            <div className="detail-value">Set</div>
          </div>
          <div>
            <div className="detail-label">Download password</div>
            <div className="detail-value">
              {client.has_download_password ? "Set" : "Not set"}
            </div>
          </div>
        </div>
      </div>

      <div className="detail-actions">
        <button
          className="btn-secondary"
          onClick={() => onManagePasswords(client)}
        >
          Manage passwords
        </button>
        <button className="btn-secondary" onClick={() => onEdit(client)}>
          Edit client
        </button>
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/*  Edit Client Modal                                                  */
/* ------------------------------------------------------------------ */

function EditClientModal({
  client,
  onClose,
  onSaved,
}: {
  client: ClientListItem;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(client.client_name);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await adminService.updateClient(client.id, { client_name: name.trim() });
      onSaved();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update client."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="Edit client" onClose={onClose}>
      <form onSubmit={handleSubmit}>
        {error && <p className="auth-error">{error}</p>}
        <label>
          Client name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            autoFocus
          />
        </label>
        <div className="modal-actions">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn-primary"
            disabled={submitting || name.trim() === client.client_name}
          >
            {submitting ? "Saving…" : "Save changes"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/*  Password Management Modal                                          */
/* ------------------------------------------------------------------ */

function PasswordManagementModal({
  client,
  minPasswordLength,
  onClose,
  onChanged,
}: {
  client: ClientListItem;
  minPasswordLength: number;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [current, setCurrent] = useState<{
    gallery_password: string | null;
    download_password: string | null;
  } | null>(null);
  const [showGallery, setShowGallery] = useState(false);
  const [showDownload, setShowDownload] = useState(false);
  const [galleryPassword, setGalleryPassword] = useState("");
  const [downloadPassword, setDownloadPassword] = useState("");
  const [removeGallery, setRemoveGallery] = useState(false);
  const [removeDownload, setRemoveDownload] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    adminService
      .getClientPasswords(client.id)
      .then((data) => {
        if (!cancelled) setCurrent(data);
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error
              ? err.message
              : "Failed to load current passwords."
          );
      });
    return () => {
      cancelled = true;
    };
  }, [client.id]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (removeGallery) {
        await adminService.changePassword(client.id, null);
      } else if (galleryPassword.trim()) {
        await adminService.changePassword(client.id, galleryPassword.trim());
      }
      if (removeDownload) {
        await adminService.changeDownloadPassword(client.id, null);
      } else if (downloadPassword.trim()) {
        await adminService.changeDownloadPassword(
          client.id,
          downloadPassword.trim()
        );
      }
      onChanged();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to update passwords."
      );
    } finally {
      setSubmitting(false);
    }
  }

return (
    <Modal title={`Passwords for ${client.client_name}`} onClose={onClose}>
      <form onSubmit={handleSubmit}>
        {error && <p className="auth-error">{error}</p>}

        <div className="pw-section">
          <div className="pw-section-title">Gallery Password</div>
          <div className="password-status-row">
            <span className="password-status-row__label">Status</span>
            {current === null ? (
              <span className="status-pill">
                <span className="status-dot status-dot--disabled" />
                Loading…
              </span>
            ) : !client.has_password ? (
              <span className="status-pill">
                <span className="status-dot status-dot--disabled" />
                Not set
              </span>
            ) : current.gallery_password != null ? (
              <span className="status-pill">
                <span className="status-dot" />
                Set
              </span>
            ) : (
              <span className="status-pill">
                <span className="status-dot status-dot--disabled" />
                Not available
              </span>
            )}
          </div>
          <label className="with-reveal">
            <span className="label-row">
              Current password
              <button
                type="button"
                className="btn-text"
                onClick={() => setShowGallery((s) => !s)}
                disabled={current?.gallery_password == null}
              >
                {showGallery ? "Hide" : "Show"}
              </button>
            </span>
            <input
              type={showGallery ? "text" : "password"}
              readOnly
              value={current?.gallery_password ?? ""}
              placeholder={
                current?.gallery_password != null
                  ? "Current gallery password"
                  : client.has_password
                    ? "No viewable copy on file"
                    : "Not set"
              }
            />
          </label>
          {current != null &&
            current.gallery_password == null &&
            client.has_password && (
              <p className="pw-hint">
                This client was created before password viewing was available,
                so the old password can't be recovered. Enter a new password
                below to enable viewing it again.
              </p>
            )}
          <label>
            New gallery password
            <input
              type="password"
              value={galleryPassword}
              onChange={(e) => {
                setGalleryPassword(e.target.value);
                if (e.target.value) setRemoveGallery(false);
              }}
              minLength={minPasswordLength}
              maxLength={64}
              disabled={removeGallery}
              placeholder={
                client.has_password
                  ? "Leave blank to keep current"
                  : `Required before entrance is protected (at least ${minPasswordLength} characters)`
              }
            />
          </label>
          {client.has_password && !removeGallery && (
            <button
              type="button"
              className="btn-text btn-text--danger"
              onClick={() => setRemoveGallery(true)}
              style={{ marginTop: "0.25rem" }}
            >
              Remove gallery password
            </button>
          )}
          {removeGallery && (
            <button
              type="button"
              className="btn-text"
              onClick={() => setRemoveGallery(false)}
              style={{ marginTop: "0.25rem" }}
            >
              Cancel removal
            </button>
          )}
        </div>

        <div className="pw-section">
          <div className="pw-section-title">Download Password</div>
          <div className="password-status-row">
            <span className="password-status-row__label">Status</span>
            {current === null ? (
              <span className="status-pill">
                <span className="status-dot status-dot--disabled" />
                Loading…
              </span>
            ) : !client.has_download_password ? (
              <span className="status-pill">
                <span className="status-dot status-dot--disabled" />
                Not set
              </span>
            ) : current.download_password != null ? (
              <span className="status-pill">
                <span className="status-dot" />
                Set
              </span>
            ) : (
              <span className="status-pill">
                <span className="status-dot status-dot--disabled" />
                Not available
              </span>
            )}
          </div>
          <label className="with-reveal">
            <span className="label-row">
              Current password
              <button
                type="button"
                className="btn-text"
                onClick={() => setShowDownload((s) => !s)}
                disabled={current?.download_password == null}
              >
                {showDownload ? "Hide" : "Show"}
              </button>
            </span>
            <input
              type={showDownload ? "text" : "password"}
              readOnly
              value={current?.download_password ?? ""}
              placeholder={
                current?.download_password != null
                  ? "Current download password"
                  : client.has_download_password
                    ? "No viewable copy on file"
                    : "Not set"
              }
            />
          </label>
          {current != null &&
            current.download_password == null &&
            client.has_download_password && (
              <p className="pw-hint">
                This client was created before password viewing was available,
                so the old password can't be recovered. Enter a new password
                below to enable viewing it again.
              </p>
            )}
          <label>
            New download password
            <input
              type="password"
              value={downloadPassword}
              onChange={(e) => {
                setDownloadPassword(e.target.value);
                if (e.target.value) setRemoveDownload(false);
              }}
              minLength={minPasswordLength}
              maxLength={64}
              disabled={removeDownload}
              placeholder={
                client.has_download_password
                  ? "Leave blank to keep current"
                  : `Required before they can download files (at least ${minPasswordLength} characters)`
              }
            />
          </label>
          {client.has_download_password && !removeDownload && (
            <button
              type="button"
              className="btn-text btn-text--danger"
              onClick={() => setRemoveDownload(true)}
              style={{ marginTop: "0.25rem" }}
            >
              Remove download password
            </button>
          )}
          {removeDownload && (
            <button
              type="button"
              className="btn-text"
              onClick={() => setRemoveDownload(false)}
              style={{ marginTop: "0.25rem" }}
            >
              Cancel removal
            </button>
          )}
        </div>

        <div className="modal-actions">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? "Saving…" : "Save passwords"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
