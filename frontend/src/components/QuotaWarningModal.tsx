import { useNavigate } from "react-router-dom";
import Modal from "./Modal";

export interface QuotaWarning {
  // "studio" = the studio's own storage quota is used up; "platform" = the whole platform is full.
  kind: "studio" | "platform";
  // The first file that did not fit, and how many files in total were refused.
  filename: string;
  count: number;
  // Bytes, when the server's message carried them.
  needed: number | null;
  remaining: number | null;
}

function size(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exp = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exp;
  return `${value.toFixed(exp === 0 ? 0 : value < 10 ? 1 : 0)} ${units[exp]}`;
}

/** Reads "(63159814 bytes) ... (9969901 bytes remaining)" out of the server's quota message. */
export function parseQuotaMessage(message: string): { needed: number | null; remaining: number | null } {
  const needed = /\((\d+) bytes\)/.exec(message);
  const remaining = /\((\d+) bytes remaining\)/.exec(message);
  return { needed: needed ? Number(needed[1]) : null, remaining: remaining ? Number(remaining[1]) : null };
}

/**
 * The pop-up shown when an upload is refused because the studio has run out of storage. Uploading
 * cannot continue until the platform administrator raises the studio's quota, so it says that plainly.
 */
export default function QuotaWarningModal({ warning, onClose }: { warning: QuotaWarning; onClose: () => void }) {
  const navigate = useNavigate();
  const studio = warning.kind === "studio";
  const many = warning.count > 1;

  return (
    <Modal
      title={studio ? "Storage quota reached" : "Platform storage is full"}
      description={
        studio
          ? "There is not enough storage left in your studio to upload this."
          : "The platform has no room left for new uploads right now."
      }
      onClose={onClose}
    >
      <div className="quota-warning" role="alert">
        <p>
          <strong>{warning.filename}</strong>
          {many ? ` and ${warning.count - 1} more file${warning.count - 1 === 1 ? "" : "s"} could not be uploaded.` : " could not be uploaded."}
        </p>
        {studio && warning.needed !== null && warning.remaining !== null && (
          <p>
            This upload needs <strong>{size(warning.needed)}</strong>, but your studio has only <strong>{size(warning.remaining)}</strong> left.
          </p>
        )}
        <p>
          {studio
            ? "Please ask your administrator to extend your studio's storage. Once the quota is raised, use Retry on the Uploads page and the upload will go through."
            : "Please ask your administrator to add platform storage, then retry the upload."}
        </p>
      </div>
      <div className="modal-actions">
        <button type="button" className="btn-secondary" onClick={() => { onClose(); navigate("/admin/storage"); }}>
          View storage
        </button>
        <button type="button" className="btn-primary" onClick={onClose} autoFocus>
          Got it
        </button>
      </div>
    </Modal>
  );
}
