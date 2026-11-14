import { FormEvent, useCallback, useEffect, useState } from "react";
import { superAdminService } from "../../services/superAdmin";
import type { StudioAdminRow } from "../../types/superAdmin";
import { formatDate } from "../../utils/superAdminFormat";
import ConfirmModal from "./ConfirmModal";
import Modal from "./Modal";
import RowActionsMenu from "./RowActionsMenu";
import ResetPasswordModal from "./ResetPasswordModal";
import SecretModal from "./SecretModal";
import StatusBadge from "./StatusBadge";
import { useToast } from "./Toast";

interface Secret {
  title: string;
  subject: string;
  password: string;
}

/**
 * Every dialog a studio user can be acted on with (add, edit, reset password,
 * enable/disable, delete, and the one-time password). Shared by the Users dialog
 * and the quick "Users" menu on the studios list, so both behave identically.
 * Render `dialogs` once in the host component and call the `open…` functions.
 */
export function useAdminDialogs(studioId: number, changed: () => void) {
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [editTarget, setEditTarget] = useState<StudioAdminRow | null>(null);
  const [resetTarget, setResetTarget] = useState<StudioAdminRow | null>(null);
  const [statusTarget, setStatusTarget] = useState<StudioAdminRow | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<StudioAdminRow | null>(null);
  const [secret, setSecret] = useState<Secret | null>(null);

  const dialogs = (
    <>
      {adding && (
        <AddAdminModal
          studioId={studioId}
          onClose={() => setAdding(false)}
          onCreated={(email, password) => {
            setAdding(false);
            if (password) setSecret({ title: "User created", subject: email, password });
            else toast.success("User created.");
            changed();
          }}
        />
      )}

      {editTarget && (
        <EditAdminModal
          studioId={studioId}
          admin={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={() => {
            setEditTarget(null);
            toast.success("User updated.");
            changed();
          }}
        />
      )}

      {resetTarget && (
        <ResetPasswordModal
          studioId={studioId}
          admin={resetTarget}
          onClose={() => setResetTarget(null)}
          onDone={() => {
            toast.success(`Password updated for ${resetTarget.email}. They have been signed out everywhere.`);
            setResetTarget(null);
            changed();
          }}
        />
      )}

      {statusTarget && (
        <ConfirmModal
          title={statusTarget.status === "active" ? `Disable ${statusTarget.name}?` : `Enable ${statusTarget.name}?`}
          description={
            statusTarget.status === "active"
              ? `${statusTarget.email} is signed out immediately and cannot sign in until you enable them again. Nothing is deleted.`
              : `${statusTarget.email} can sign in again with their current password.`
          }
          confirmLabel={statusTarget.status === "active" ? "Disable user" : "Enable user"}
          danger={statusTarget.status === "active"}
          onClose={() => setStatusTarget(null)}
          onConfirm={async () => {
            const target = statusTarget;
            if (target.status === "active") await superAdminService.disableAdmin(studioId, target.id);
            else await superAdminService.enableAdmin(studioId, target.id);
            setStatusTarget(null);
            toast.success(target.status === "active" ? "User disabled." : "User enabled.");
            changed();
          }}
        />
      )}

      {deleteTarget && (
        <ConfirmModal
          title={`Delete ${deleteTarget.name}?`}
          description={`${deleteTarget.email} will be permanently removed and can no longer be re-enabled. Their galleries, clients and photos stay with the studio. This cannot be undone.`}
          confirmLabel="Delete user"
          danger
          onClose={() => setDeleteTarget(null)}
          onConfirm={async () => {
            const target = deleteTarget;
            await superAdminService.deleteAdmin(studioId, target.id);
            setDeleteTarget(null);
            toast.success("User deleted.");
            changed();
          }}
        />
      )}

      {secret && <SecretModal title={secret.title} subject={secret.subject} password={secret.password} onClose={() => setSecret(null)} />}
    </>
  );

  return {
    dialogs,
    openAdd: () => setAdding(true),
    openEdit: setEditTarget,
    openReset: setResetTarget,
    openStatus: setStatusTarget,
    openDelete: setDeleteTarget,
  };
}

/**
 * The people who can sign in to one studio: list, add, edit (name / email),
 * reset password, disable / re-enable, and delete (only once disabled). Used on the studio detail page and in
 * the "Users" dialog on the studios list.
 */
export default function StudioAdminsPanel({
  studioId,
  onChanged,
  inDialog = false,
}: {
  studioId: number;
  /** Called after any change, so the host page can refresh its own data. */
  onChanged?: () => void;
  inDialog?: boolean;
}) {
  const [admins, setAdmins] = useState<StudioAdminRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setAdmins(await superAdminService.listAdmins(studioId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the studio's users.");
    }
  }, [studioId]);

  useEffect(() => {
    load();
  }, [load]);

  function changed() {
    load();
    onChanged?.();
  }

  const d = useAdminDialogs(studioId, changed);

  return (
    <>
      <div className={"sa-card__head" + (inDialog ? "" : " sa-card__head--pad")}>
        <h2>Studio users</h2>
        {/* A studio has one login: adding is only offered while it has none. */}
        {admins !== null && admins.length === 0 && (
          <button className="sa-btn sa-btn--ghost sa-btn--sm" onClick={d.openAdd}>
            Add user
          </button>
        )}
      </div>

      {error && (
        <p className="sa-form-error" role="alert">
          {error}
        </p>
      )}
      {!admins && !error && <p className="sa-empty">Loading…</p>}
      {admins && admins.length === 0 && <p className="sa-empty">This studio has no users.</p>}
      {admins && admins.length > 0 && (
        <div className="sa-table-wrap">
          <table className="sa-table sa-table--stack">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Status</th>
                <th>Added</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {admins.map((a) => (
                <tr key={a.id}>
                  <td className="sa-table__title">{a.name}</td>
                  <td className="sa-muted">{a.email}</td>
                  <td>
                    <StatusBadge status={a.status} />
                  </td>
                  <td className="sa-muted sa-nowrap">{formatDate(a.created_at)}</td>
                  <td className="sa-table__actions">
                    <RowActionsMenu
                      actions={[
                        { label: "Edit user", onSelect: () => d.openEdit(a) },
                        { label: "Reset password", onSelect: () => d.openReset(a) },
                        { label: a.status === "active" ? "Disable user" : "Enable user", onSelect: () => d.openStatus(a) },
                        {
                          label: "Delete user",
                          danger: true,
                          separated: true,
                          disabled: a.status !== "disabled",
                          hint: a.status !== "disabled" ? "Disable the user first" : undefined,
                          onSelect: () => d.openDelete(a),
                        },
                      ]}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {d.dialogs}
    </>
  );
}

function EditAdminModal({
  studioId,
  admin,
  onClose,
  onSaved,
}: {
  studioId: number;
  admin: StudioAdminRow;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(admin.name);
  const [email, setEmail] = useState(admin.email);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const emailChanged = email.trim().toLowerCase() !== admin.email.toLowerCase();
  const dirty = name.trim() !== admin.name || emailChanged;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await superAdminService.updateAdmin(studioId, admin.id, {
        name: name.trim(),
        email: email.trim(),
      });
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the user.");
      setBusy(false);
    }
  }

  return (
    <Modal title="Edit user" onClose={busy ? () => {} : onClose}>
      <form onSubmit={submit} className="sa-stack">
        {error && (
          <p className="sa-form-error" role="alert">
            {error}
          </p>
        )}
        <label className="sa-field">
          <span>Name *</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={255} required autoFocus />
        </label>
        <label className="sa-field">
          <span>Email (their sign-in) *</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" required />
          {emailChanged && <small>Changing the email signs this user out everywhere; they sign in with the new address.</small>}
        </label>
        <div className="sa-modal-card__actions">
          <button type="button" className="sa-btn sa-btn--ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="sa-btn sa-btn--dark" disabled={busy || !dirty}>
            {busy ? "Saving…" : "Save user"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function AddAdminModal({
  studioId,
  onClose,
  onCreated,
}: {
  studioId: number;
  onClose: () => void;
  onCreated: (email: string, tempPassword: string | null) => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password && password.length < 4) {
      setError("A password you set must be at least 4 characters. Leave it blank to generate one.");
      return;
    }
    setBusy(true);
    try {
      const res = await superAdminService.createAdmin(studioId, {
        name: name.trim(),
        email: email.trim(),
        password: password || null,
      });
      onCreated(res.admin.email, res.temporary_password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the user.");
      setBusy(false);
    }
  }

  return (
    <Modal title="Add studio user" onClose={busy ? () => {} : onClose}>
      <form onSubmit={submit} className="sa-stack">
        {error && (
          <p className="sa-form-error" role="alert">
            {error}
          </p>
        )}
        <label className="sa-field">
          <span>Name *</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={255} required autoFocus />
        </label>
        <label className="sa-field">
          <span>Email *</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" required />
        </label>
        <label className="sa-field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            placeholder="Leave blank to generate a temporary password"
          />
        </label>
        <div className="sa-modal-card__actions">
          <button type="button" className="sa-btn sa-btn--ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="sa-btn sa-btn--dark" disabled={busy}>
            {busy ? "Creating…" : "Create user"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
