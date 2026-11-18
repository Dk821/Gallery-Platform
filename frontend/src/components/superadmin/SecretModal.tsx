import { useState } from "react";
import Modal from "./Modal";
import { IconCopy } from "./Icons";

interface SecretModalProps {
  title: string;
  /** Who the password is for, e.g. an email address. */
  subject: string;
  password: string;
  onClose: () => void;
}

// One-time credentials. The password exists ONLY in this component's props
// (React state of the opener) - it is never written to storage, the URL or the
// console, and is gone the moment the dialog is dismissed. The server does not
// keep it either, so it cannot be shown again.
export default function SecretModal({ title, subject, password, onClose }: SecretModalProps) {
  const [copied, setCopied] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard can be blocked (insecure origin / permissions). The value is
      // selectable below, so the user can still copy it by hand.
    }
  }

  return (
    <Modal
      title={title}
      description={`Temporary password for ${subject}. It is shown only once - the server stores a hash and cannot show it again. Share it through a secure channel; the admin should change it after signing in.`}
      onClose={() => confirmed && onClose()}
      closeOnBackdrop={false}
    >
      <div className="sa-secret">
        <code className="sa-secret__value" data-testid="temp-password">
          {password}
        </code>
        <button
          type="button"
          className={"sa-btn sa-btn--ghost sa-btn--sm" + (copied ? " sa-btn--success" : "")}
          onClick={copy}
        >
          <IconCopy /> {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <label className="sa-check">
        <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
        <span>I have saved this password somewhere safe.</span>
      </label>
      <div className="sa-modal-card__actions">
        <button type="button" className="sa-btn sa-btn--dark" disabled={!confirmed} onClick={onClose}>
          Done
        </button>
      </div>
    </Modal>
  );
}
