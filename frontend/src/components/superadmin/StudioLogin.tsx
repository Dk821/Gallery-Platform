import { FormEvent, useCallback, useEffect, useState } from "react";
import { superAdminService } from "../../services/superAdmin";
import type { StudioAdminRow } from "../../types/superAdmin";
import { formatDate } from "../../utils/superAdminFormat";
import ConfirmModal from "./ConfirmModal";
import Modal from "./Modal";
import ResetPasswordModal from "./ResetPasswordModal";
import RowActionsMenu, { RowAction } from "./RowActionsMenu";
import SecretModal from "./SecretModal";
import StatusBadge from "./StatusBadge";
import { useToast } from "./Toast";

/*
 * ONE STUDIO = ONE LOGIN. A studio has exactly one studio-administrator login
 * (created together with the studio). There is no "add user", "manage all users"
 * or "delete user": the login is edited, has its email changed, has its password
 * reset, and is disabled / enabled. This file holds everything that acts on it:
 *   useStudioLoginDialogs  - the dialogs (shared by the detail page and the list menu)
 *   StudioLoginCard        - the "Studio login account" section on the studio page
 *   StudioLoginMenu        - the "Login" button on the studios list
 */

interface Secret {
  title: string;
  subject: string;
  password: string;
}

function loginActions(login: StudioAdminRow, d: ReturnType<typeof useStudioLoginDialogs>): RowAction[] {
  return [
    { label: "Edit login details", onSelect: () => d.openEdit(login) },
    { label: "Change login email", onSelect: () => d.openEmail(login) },
    { label: "Reset password", onSelect: () => d.openReset(login) },
    {
      label: login.status === "active" ? "Disable login" : "Enable login",
      danger: login.status === "active",
      separated: true,
      onSelect: () => d.openStatus(login),
    },
  ];
}

export function useStudioLoginDialogs(studioId: number, changed: () => void) {
  const toast = useToast();
  const [settingUp, setSettingUp] = useState(false);
  const [editTarget, setEditTarget] = useState<StudioAdminRow | null>(null);
  const [emailTarget, setEmailTarget] = useState<StudioAdminRow | null>(null);
  const [resetTarget, setResetTarget] = useState<StudioAdminRow | null>(null);
  const [statusTarget, setStatusTarget] = useState<StudioAdminRow | null>(null);
  const [secret, setSecret] = useState<Secret | null>(null);

  const dialogs = (
    <>
      {settingUp && (
        <SetUpLoginModal
          studioId={studioId}
          onClose={() => setSettingUp(false)}
          onCreated={(email, password) => {
            setSettingUp(false);
            if (password) setSecret({ title: "Studio login created", subject: email, password });
            else toast.success("Studio login created.");
            changed();
          }}
        />
      )}

      {editTarget && (
        <EditDetailsModal
          studioId={studioId}
          login={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={() => {
            setEditTarget(null);
            toast.success("Login details updated.");
            changed();
          }}
        />
      )}

      {emailTarget && (
        <ChangeEmailModal
          studioId={studioId}
          login={emailTarget}
          onClose={() => setEmailTarget(null)}
          onSaved={(email) => {
            setEmailTarget(null);
            toast.success(`Login email changed to ${email}. The studio was signed out and must use the new address.`);
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
            toast.success(`Password updated for ${resetTarget.email}. The studio was signed out everywhere.`);
            setResetTarget(null);
            changed();
          }}
        />
      )}

      {statusTarget && (
        <ConfirmModal
          title={statusTarget.status === "active" ? "Disable this studio login?" : "Enable this studio login?"}
          description={
            statusTarget.status === "active"
              ? `${statusTarget.email} is signed out immediately and cannot sign in until you enable the login again. The studio's clients, albums and photos are not touched, and clients can still open their galleries.`
              : `${statusTarget.email} can sign in again with the current password.`
          }
          confirmLabel={statusTarget.status === "active" ? "Disable login" : "Enable login"}
          danger={statusTarget.status === "active"}
          onClose={() => setStatusTarget(null)}
          onConfirm={async () => {
            const target = statusTarget;
            if (target.status === "active") await superAdminService.disableAdmin(studioId, target.id);
            else await superAdminService.enableAdmin(studioId, target.id);
            setStatusTarget(null);
            toast.success(target.status === "active" ? "Login disabled." : "Login enabled.");
            changed();
          }}
        />
      )}

      {secret && <SecretModal title={secret.title} subject={secret.subject} password={secret.password} onClose={() => setSecret(null)} />}
    </>
  );

  return {
    dialogs,
    openSetUp: () => setSettingUp(true),
    openEdit: setEditTarget,
    openEmail: setEmailTarget,
    openReset: setResetTarget,
    openStatus: setStatusTarget,
  };
}

/** Loads the studio's one login (null = it has none, which only happens for an older studio). */
function useStudioLogin(studioId: number) {
  const [login, setLogin] = useState<StudioAdminRow | null | undefined>(undefined); // undefined = loading
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const rows = await superAdminService.listAdmins(studioId);
      setLogin(rows[0] ?? null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the studio login.");
    }
  }, [studioId]);

  return { login, error, load, reset: () => setLogin(undefined) };
}

/** The "Studio login account" section on the studio page. */
export function StudioLoginCard({ studioId, onChanged }: { studioId: number; onChanged?: () => void }) {
  const { login, error, load } = useStudioLogin(studioId);
  useEffect(() => {
    load();
  }, [load]);

  const d = useStudioLoginDialogs(studioId, () => {
    load();
    onChanged?.();
  });

  return (
    <section className="sa-card">
      <div className="sa-card__head">
        <h2>Studio login account</h2>
      </div>
      <p className="sa-muted sa-small" style={{ marginTop: 0 }}>
        Each studio has exactly one login. It opens this studio's dashboard.
      </p>

      {error && (
        <p className="sa-form-error" role="alert">
          {error}
        </p>
      )}
      {login === undefined && !error && <p className="sa-empty">Loading…</p>}

      {login === null && (
        <div className="sa-empty">
          <p style={{ margin: "0 0 0.75rem" }}>This studio has no login account, so nobody can sign in to it yet.</p>
          <button className="sa-btn sa-btn--dark sa-btn--sm" onClick={d.openSetUp}>
            Set up login
          </button>
        </div>
      )}

      {login && (
        <>
          <dl className="sa-kv sa-kv--row">
            <div>
              <dt>Name</dt>
              <dd data-testid="login-name">{login.name}</dd>
            </div>
            <div>
              <dt>Login email</dt>
              <dd data-testid="login-email">{login.email}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>
                <StatusBadge status={login.status} />
              </dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{formatDate(login.created_at)}</dd>
            </div>
          </dl>
          <div className="sa-logo-field__actions" style={{ marginTop: "0.9rem" }}>
            <button className="sa-btn sa-btn--ghost sa-btn--sm" onClick={() => d.openEdit(login)}>
              Edit login details
            </button>
            <button className="sa-btn sa-btn--ghost sa-btn--sm" onClick={() => d.openEmail(login)}>
              Change login email
            </button>
            <button className="sa-btn sa-btn--ghost sa-btn--sm" onClick={() => d.openReset(login)}>
              Reset password
            </button>
            {login.status === "active" ? (
              <button className="sa-btn sa-btn--danger-outline sa-btn--sm" onClick={() => d.openStatus(login)}>
                Disable login
              </button>
            ) : (
              <button className="sa-btn sa-btn--dark sa-btn--sm" onClick={() => d.openStatus(login)}>
                Enable login
              </button>
            )}
          </div>
        </>
      )}

      {d.dialogs}
    </section>
  );
}

/** The "Login" button on the studios list: the login's identity and its actions, nothing else. */
export function StudioLoginMenu({ studioId, onChanged }: { studioId: number; onChanged: () => void }) {
  const { login, error, load, reset } = useStudioLogin(studioId);
  const d = useStudioLoginDialogs(studioId, () => {
    load();
    onChanged();
  });

  const actions: RowAction[] = [];
  if (login) {
    actions.push({ label: login.name, header: true, hint: `${login.email} · ${login.status === "active" ? "Active" : "Disabled"}` });
    actions.push(...loginActions(login, d));
  } else if (login === null) {
    actions.push({ label: "No login yet", header: true, hint: "Nobody can sign in to this studio." });
    actions.push({ label: "Set up login", onSelect: d.openSetUp });
  }

  return (
    <>
      <RowActionsMenu
        label="Login"
        actions={actions}
        onOpen={() => {
          reset();
          load();
        }}
        emptyText={error ?? "Loading…"}
      />
      {d.dialogs}
    </>
  );
}

function EditDetailsModal({
  studioId,
  login,
  onClose,
  onSaved,
}: {
  studioId: number;
  login: StudioAdminRow;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(login.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await superAdminService.updateAdmin(studioId, login.id, { name: name.trim() });
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the login details.");
      setBusy(false);
    }
  }

  return (
    <Modal title="Edit login details" onClose={busy ? () => {} : onClose}>
      <form onSubmit={submit} className="sa-stack">
        {error && (
          <p className="sa-form-error" role="alert">
            {error}
          </p>
        )}
        <label className="sa-field">
          <span>Login name *</span>
          <input placeholder="Enter login name" value={name} onChange={(e) => setName(e.target.value)} maxLength={255} required autoFocus />
          <small>Changing the name does not sign anyone out. To change the sign-in address use “Change login email”.</small>
        </label>
        <div className="sa-modal-card__actions">
          <button type="button" className="sa-btn sa-btn--ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="sa-btn sa-btn--dark" disabled={busy || !name.trim() || name.trim() === login.name}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ChangeEmailModal({
  studioId,
  login,
  onClose,
  onSaved,
}: {
  studioId: number;
  login: StudioAdminRow;
  onClose: () => void;
  onSaved: (email: string) => void;
}) {
  const [email, setEmail] = useState(login.email);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dirty = email.trim().toLowerCase() !== login.email.toLowerCase();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const row = await superAdminService.updateAdmin(studioId, login.id, { email: email.trim() });
      onSaved(row.email);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change the login email.");
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Change login email"
      description="This is the address the studio signs in with. Anyone currently signed in is signed out at once and must use the new address."
      onClose={busy ? () => {} : onClose}
    >
      <form onSubmit={submit} className="sa-stack">
        {error && (
          <p className="sa-form-error" role="alert">
            {error}
          </p>
        )}
        <label className="sa-field">
          <span>Login email *</span>
          <input placeholder="Enter email address" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" required autoFocus />
        </label>
        <div className="sa-modal-card__actions">
          <button type="button" className="sa-btn sa-btn--ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="sa-btn sa-btn--dark" disabled={busy || !dirty}>
            {busy ? "Changing…" : "Change email"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** Only reachable for a studio that has no login at all (e.g. created before this rule). */
function SetUpLoginModal({
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
      setError(err instanceof Error ? err.message : "Could not create the login.");
      setBusy(false);
    }
  }

  return (
    <Modal title="Set up studio login" description="This studio has no login. Create its one login account." onClose={busy ? () => {} : onClose}>
      <form onSubmit={submit} className="sa-stack">
        {error && (
          <p className="sa-form-error" role="alert">
            {error}
          </p>
        )}
        <label className="sa-field">
          <span>Login name *</span>
          <input placeholder="Enter login name" value={name} onChange={(e) => setName(e.target.value)} maxLength={255} required autoFocus />
        </label>
        <label className="sa-field">
          <span>Login email *</span>
          <input placeholder="Enter email address" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" required />
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
          <small>A generated password is shown once, right after creation.</small>
        </label>
        <div className="sa-modal-card__actions">
          <button type="button" className="sa-btn sa-btn--ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="sa-btn sa-btn--dark" disabled={busy}>
            {busy ? "Creating…" : "Create login"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
