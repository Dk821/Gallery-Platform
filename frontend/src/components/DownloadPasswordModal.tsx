import { FormEvent, useState } from "react";
import Modal from "./Modal";

interface DownloadPasswordModalProps {
  downloadUrl: string;
  verifyPassword: (password: string) => Promise<boolean>;
  onClose: () => void;
}

export default function DownloadPasswordModal({
  downloadUrl,
  verifyPassword,
  onClose,
}: DownloadPasswordModalProps) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!password.trim()) return;

    setVerifying(true);
    setError(null);
    try {
      const verified = await verifyPassword(password.trim());
      if (!verified) {
        setError("Incorrect password.");
        return;
      }
      window.location.assign(downloadUrl);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed.");
    } finally {
      setVerifying(false);
    }
  }

  return (
    <Modal title="Download password" onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <p style={{ color: "var(--text-muted)", fontSize: "0.9rem", marginTop: 0 }}>
          Enter the password provided by your photographer to download this file.
        </p>
        {error && <p className="auth-error">{error}</p>}
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Enter download password"
          autoFocus
          required
          style={{
            width: "100%",
            background: "var(--bg)",
            border: "1px solid var(--hairline)",
            color: "var(--text)",
            padding: "0.55rem 0.75rem",
            borderRadius: "6px",
            fontSize: "0.9rem",
            marginBottom: "1rem",
          }}
        />
        <div className="modal-actions">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Close
          </button>
          <button type="submit" className="btn-primary" disabled={verifying}>
            {verifying ? "Verifying..." : "Verify & Download"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
