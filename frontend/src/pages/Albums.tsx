import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AdminLayout from "../components/AdminLayout";
import Modal from "../components/Modal";
import { adminService, AlbumItem, ClientListItem } from "../services/admin";

export default function Albums() {
  const navigate = useNavigate();
  const [albums, setAlbums] = useState<AlbumItem[]>([]);
  const [clients, setClients] = useState<ClientListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<AlbumItem | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  function showToast(message: string) {
    setToast(message);
    setTimeout(() => setToast(null), 2500);
  }

  async function loadAll() {
    setLoading(true);
    try {
      const [albumPage, clientPage] = await Promise.all([
        adminService.listAlbums(),
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

  function clientName(clientId: number): string {
    return clients.find((c) => c.id === clientId)?.client_name ?? `Client #${clientId}`;
  }

  async function handleDelete(album: AlbumItem) {
    try {
      await adminService.removeAlbum(album.id);
      showToast(`${album.album_name} deleted.`);
      setConfirmDelete(null);
      loadAll();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Delete failed.");
    }
  }

  return (
    <AdminLayout>
      <h1 className="admin-page-title">Albums</h1>
      <p className="admin-page-subtitle">Organize each client's gallery into albums.</p>

      <div className="section-header">
        <h2>All albums</h2>
        <button
          className="btn-primary"
          onClick={() => setShowCreate(true)}
          disabled={clients.length === 0}
          title={clients.length === 0 ? "Create a client first" : undefined}
        >
          New album
        </button>
      </div>

      {error && <p className="auth-error">{error}</p>}

      {!loading && albums.length === 0 && (
        <div className="empty-state">
          {clients.length === 0
            ? "Create a client first, then add albums to their gallery."
            : "No albums yet. Create one above."}
        </div>
      )}

      {albums.length > 0 && (
        <div className="table-scroll">
        <table className="client-table">
          <thead>
            <tr>
              <th>Album</th>
              <th>Client</th>
              <th>Files</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {albums.map((a) => (
              <tr key={a.id}>
                <td>
                  <button
                    className="btn-text"
                    style={{ color: "var(--text)", fontWeight: 500 }}
                    onClick={() => navigate(`/admin/albums/${a.id}`)}
                  >
                    {a.album_name}
                  </button>
                </td>
                <td>{clientName(a.client_id)}</td>
                <td>{a.media_count}</td>
                <td>{new Date(a.created_at).toLocaleDateString()}</td>
                <td>
                  <div className="actions-cell">
                    <button className="btn-text" onClick={() => navigate(`/admin/albums/${a.id}`)}>
                      View media
                    </button>
                    <button className="btn-text btn-text--danger" onClick={() => setConfirmDelete(a)}>
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}

      {showCreate && (
        <CreateAlbumModal
          clients={clients}
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            showToast("Album created.");
            loadAll();
          }}
        />
      )}

      {confirmDelete && (
        <Modal
          title={`Delete ${confirmDelete.album_name}?`}
          description="This removes the album and its media references. This cannot be undone."
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
              Delete
            </button>
          </div>
        </Modal>
      )}

      {toast && <div className="toast">{toast}</div>}
    </AdminLayout>
  );
}

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
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await adminService.createAlbum(clientId, albumName, description || undefined);
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
          <input value={albumName} onChange={(e) => setAlbumName(e.target.value)} required autoFocus />
        </label>
        <label>
          Description (optional)
          <input value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <div className="modal-actions">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? "Creating..." : "Create album"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
