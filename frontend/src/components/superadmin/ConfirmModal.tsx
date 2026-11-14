import { ReactNode, useState } from "react";
import Modal from "./Modal";

interface ConfirmModalProps {
  title: string;
  description: string;
  confirmLabel: string;
  danger?: boolean;
  /** Keeps the confirm button disabled (e.g. until a name has been typed). */
  confirmDisabled?: boolean;
  /** Adds an optional free-text reason field; its value is passed to onConfirm. */
  askReason?: boolean;
  children?: ReactNode;
  onConfirm: (reason: string) => Promise<void>;
  onClose: () => void;
}

export default function ConfirmModal({
  title,
  description,
  confirmLabel,
  danger,
  confirmDisabled,
  askReason,
  children,
  onConfirm,
  onClose,
}: ConfirmModalProps) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await onConfirm(reason);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <Modal title={title} description={description} onClose={busy ? () => {} : onClose}>
      {children}
      {askReason && (
        <label className="sa-field">
          <span>Reason (optional, saved in the audit log)</span>
          <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} placeholder="Enter reason" />
        </label>
      )}
      {error && (
        <p className="sa-form-error" role="alert">
          {error}
        </p>
      )}
      <div className="sa-modal-card__actions">
        <button type="button" className="sa-btn sa-btn--ghost" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button type="button" className={"sa-btn " + (danger ? "sa-btn--danger" : "sa-btn--dark")} onClick={submit} disabled={busy || confirmDisabled}>
          {busy ? "Working…" : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
