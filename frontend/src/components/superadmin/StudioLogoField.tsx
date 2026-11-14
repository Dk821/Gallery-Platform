import { useRef, useState } from "react";
import { assetUrl } from "../../services/api";
import { superAdminService } from "../../services/superAdmin";
import type { Studio } from "../../types/superAdmin";

const ACCEPT = ["image/png", "image/jpeg", "image/webp", "image/gif"];
const MAX_BYTES = 5 * 1024 * 1024;

// The studio's logo as a picture: preview, upload / replace, remove. It changes
// the logo immediately (separate from the form's Save button) and reports back
// so the page can refresh.
export default function StudioLogoField({
  studio,
  onChanged,
}: {
  studio: Pick<Studio, "id" | "name" | "logo_url">;
  onChanged: (message: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<"upload" | "remove" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  const src = assetUrl(studio.logo_url);
  const showImage = !!src && failedSrc !== src;

  async function pick(file: File | undefined) {
    if (!file) return;
    setError(null);
    if (!ACCEPT.includes(file.type)) {
      setError("Choose a PNG, JPG, WebP or GIF image.");
      return;
    }
    if (file.size > MAX_BYTES) {
      setError("The image must be 5 MB or smaller.");
      return;
    }
    setBusy("upload");
    try {
      await superAdminService.uploadLogo(studio.id, file);
      onChanged("Logo updated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not upload the logo.");
    } finally {
      setBusy(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function remove() {
    setError(null);
    setBusy("remove");
    try {
      await superAdminService.removeLogo(studio.id);
      onChanged("Logo removed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove the logo.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="sa-field sa-form-grid__full">
      <span>Logo</span>
      <div className="sa-logo-field">
        <div className="sa-logo-field__preview">
          {showImage ? (
            <img src={src!} alt={`${studio.name} logo`} onError={() => setFailedSrc(src)} />
          ) : (
            <span>{failedSrc ? "Can't load" : "No logo"}</span>
          )}
        </div>
        <div className="sa-logo-field__body">
          <div className="sa-logo-field__actions">
            <button
              type="button"
              className="sa-btn sa-btn--ghost sa-btn--sm"
              disabled={busy !== null}
              onClick={() => inputRef.current?.click()}
            >
              {busy === "upload" ? "Uploading…" : studio.logo_url ? "Replace image" : "Upload image"}
            </button>
            {studio.logo_url && (
              <button
                type="button"
                className="sa-btn sa-btn--danger-outline sa-btn--sm"
                disabled={busy !== null}
                onClick={remove}
              >
                {busy === "remove" ? "Removing…" : "Remove"}
              </button>
            )}
          </div>
          <small>PNG, JPG, WebP or GIF, up to 5 MB. It is shown in the studio's dashboard.</small>
          {error && (
            <p className="sa-form-error" role="alert">
              {error}
            </p>
          )}
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT.join(",")}
          hidden
          aria-label="Logo image file"
          onChange={(e) => pick(e.target.files?.[0])}
        />
      </div>
    </div>
  );
}
