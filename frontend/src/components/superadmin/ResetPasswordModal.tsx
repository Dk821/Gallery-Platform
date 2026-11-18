import { FormEvent, useState } from "react";
import { superAdminService } from "../../services/superAdmin";
import type { StudioAdminRow } from "../../types/superAdmin";
import { IconCopy } from "./Icons";
import Modal from "./Modal";

const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"; // no look-alike characters

// Only produced when the operator presses "Generate".
function suggestPassword(): string {
  const bytes = new Uint32Array(12);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (n) => ALPHABET[n % ALPHABET.length]).join("");
}

// Reset a studio user's password. The current password cannot be shown (the
// server only keeps a one-way hash of it), so the operator types the NEW one -
// or presses Generate - and it replaces the old password at once. The form
// starts empty and "Update password" stays disabled until something is entered.
export default function ResetPasswordModal({
  studioId,
  admin,
  onClose,
  onDone,
}: {
  studioId: number;
  admin: StudioAdminRow;
  onClose: () => void;
  onDone: () => void;
}) {
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(true);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function copy() {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard can be blocked; the field is selectable, so it can be copied by hand.
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 4) {
      setError("The new password must be at least 4 characters.");
      return;
    }
    setBusy(true);
    try {
      await superAdminService.resetAdminPassword(studioId, admin.id, password);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset the password.");
      setBusy(false);
    }
  }

  return (
    <Modal
      title={`Reset password for ${admin.name}`}
      description={`${admin.email} is signed out everywhere and the old password stops working at once. For security the current password is stored scrambled and cannot be shown. Choose a new one below.`}
      onClose={() => !busy && onClose()}
    >
      <form onSubmit={submit}>
        <label className="sa-field">
          <span>New password</span>
          <div className="sa-input-group">
            <input
              type={visible ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              placeholder="Type a new password, or press Generate"
              spellCheck={false}
              maxLength={128}
              autoFocus
            />
            <button type="button" className="sa-btn sa-btn--ghost sa-btn--sm" onClick={() => setVisible((v) => !v)}>
              {visible ? "Hide" : "Show"}
            </button>
          </div>
        </label>
        <div className="sa-logo-field__actions" style={{ marginTop: "0.6rem" }}>
          <button type="button" className="sa-btn sa-btn--ghost sa-btn--sm" onClick={() => setPassword(suggestPassword())}>
            Generate
          </button>
          <button
            type="button"
            className={"sa-btn sa-btn--ghost sa-btn--sm" + (copied ? " sa-btn--success" : "")}
            onClick={copy}
            disabled={!password}
          >
            <IconCopy /> {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <p className="sa-muted sa-small" style={{ margin: "0.6rem 0 0" }}>
          At least 4 characters. Share it with the user through a secure channel; they can change it in Settings after signing in.
        </p>
        {error && (
          <p className="sa-form-error" role="alert">
            {error}
          </p>
        )}
        <div className="sa-modal-card__actions">
          <button type="button" className="sa-btn sa-btn--ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="sa-btn sa-btn--dark" disabled={busy || password.length === 0}>
            {busy ? "Updating…" : "Update password"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
