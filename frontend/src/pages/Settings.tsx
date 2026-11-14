import { FormEvent, useEffect, useRef, useState } from "react";
import AdminLayout from "../components/AdminLayout";
import { adminService, SettingsResponse, StudioProfile } from "../services/admin";
import { assetUrl } from "../services/api";
import { refreshBranding } from "../services/studioBranding";
import { phoneError, sanitizePhoneInput } from "../utils/phone";

function ProfileIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
      <path
        d="M4 20c0-3.31 3.58-6 8-6s8 2.69 8 6M12 12a4 4 0 100-8 4 4 0 000 8z"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function AccountIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
      <rect x="5" y="11" width="14" height="9" rx="2" strokeWidth="1.8" />
      <path d="M8 11V7a4 4 0 118 0v4" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  Studio profile                                                     */
/* ------------------------------------------------------------------ */

const LOGO_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
const LOGO_MAX_BYTES = 5 * 1024 * 1024;

function StudioProfileCard({
  initial,
  onSaved,
}: {
  initial: StudioProfile;
  onSaved: (res: { studio: SettingsResponse["studio"] | null; profile: StudioProfile }) => void;
}) {
  const [studioName, setStudioName] = useState(initial.name ?? "");
  const [contactEmail, setContactEmail] = useState(initial.contact_email ?? "");
  const [contactPhone, setContactPhone] = useState(initial.contact_phone ?? "");
  // A logo change is only staged here; nothing is sent until "Save changes".
  const [newLogo, setNewLogo] = useState<File | null>(null);
  const [logoPreview, setLogoPreview] = useState<string | null>(null);
  const [removeLogo, setRemoveLogo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [saving, setSaving] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!newLogo) {
      setLogoPreview(null);
      return;
    }
    const url = URL.createObjectURL(newLogo);
    setLogoPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [newLogo]);

  const currentLogo = removeLogo ? null : logoPreview ?? assetUrl(initial.logo_url);
  const dirty =
    studioName.trim() !== (initial.name ?? "") ||
    contactEmail.trim() !== (initial.contact_email ?? "") ||
    contactPhone.trim() !== (initial.contact_phone ?? "") ||
    newLogo !== null ||
    removeLogo;

  function pickLogo(file: File | undefined) {
    if (!file) return;
    setError(null);
    setSuccess(false);
    if (!LOGO_TYPES.includes(file.type)) {
      setError("Choose a PNG, JPG, WebP or GIF image for the logo.");
      return;
    }
    if (file.size > LOGO_MAX_BYTES) {
      setError("The logo must be 5 MB or smaller.");
      return;
    }
    setNewLogo(file);
    setRemoveLogo(false);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(false);
    if (!studioName.trim()) {
      setError("Enter the studio name.");
      return;
    }
    const phoneProblem = phoneError(contactPhone);
    if (phoneProblem) {
      setError(phoneProblem);
      return;
    }
    setSaving(true);
    try {
      const res = await adminService.updateStudioProfile(studioName, contactEmail, contactPhone);
      const { profile: savedProfile, ...savedSettings } = res;
      let profile = savedProfile;
      if (newLogo) profile = await adminService.uploadStudioLogo(newLogo);
      else if (removeLogo && initial.logo_url) profile = await adminService.removeStudioLogo();
      setNewLogo(null);
      setRemoveLogo(false);
      if (fileRef.current) fileRef.current.value = "";
      void refreshBranding(); // the sidebar shows the new name / logo straight away
      onSaved({ studio: savedSettings, profile });
      setSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save studio details.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="admin-panel-card">
      <div className="admin-panel-card__header">
        <h2 className="admin-panel-card__title">Studio details</h2>
        <div className="admin-job-icon admin-job-icon--profile">
          <ProfileIcon />
        </div>
      </div>
      <form className="settings-form" onSubmit={handleSubmit}>
        {error && <p className="auth-error">{error}</p>}

        <div className="settings-logo">
          <span className="settings-logo__label">Logo</span>
          <div className="settings-logo__row">
            <div className="settings-logo__preview">
              {currentLogo ? <img src={currentLogo} alt="Studio logo" /> : <span>No logo</span>}
            </div>
            <div className="settings-logo__actions">
              <button type="button" className="btn-secondary" onClick={() => fileRef.current?.click()}>
                {currentLogo ? "Replace image" : "Upload image"}
              </button>
              {currentLogo && (
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => {
                    setNewLogo(null);
                    setRemoveLogo(true);
                    setSuccess(false);
                  }}
                >
                  Remove
                </button>
              )}
            </div>
            <input
              ref={fileRef}
              type="file"
              accept={LOGO_TYPES.join(",")}
              hidden
              aria-label="Logo image file"
              onChange={(e) => pickLogo(e.target.files?.[0])}
            />
          </div>
          <small className="settings-form__hint">PNG, JPG, WebP or GIF, up to 5 MB.</small>
        </div>

        <label>
          Studio name
          <input
            value={studioName}
            onChange={(e) => {
              setStudioName(e.target.value);
              setSuccess(false);
            }}
            placeholder="Enter studio name"
            maxLength={255}
            required
          />
        </label>
        <label>
          Contact email
          <input
            type="email"
            value={contactEmail}
            onChange={(e) => {
              setContactEmail(e.target.value);
              setSuccess(false);
            }}
            placeholder="Enter email address"
          />
        </label>
        <label>
          Contact phone
          <input
            type="tel"
            inputMode="tel"
            value={contactPhone}
            onChange={(e) => {
              setContactPhone(sanitizePhoneInput(e.target.value));
              setSuccess(false);
            }}
            placeholder="Enter mobile number"
            maxLength={20}
            autoComplete="tel"
          />
        </label>
        <div className="settings-form-actions">
          <button type="submit" className="btn-primary" disabled={saving || !dirty}>
            {saving ? "Saving…" : "Save changes"}
          </button>
          {success && <span className="settings-form__success">Saved</span>}
        </div>
      </form>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Admin account (change own password)                                */
/* ------------------------------------------------------------------ */

function AdminAccountCard({ adminEmail }: { adminEmail: string }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(false);

    if (newPassword !== confirmPassword) {
      setError("New password and confirmation don't match.");
      return;
    }

    setSaving(true);
    try {
      await adminService.changeAdminPassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to change password.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="admin-panel-card">
      <div className="admin-panel-card__header">
        <h2 className="admin-panel-card__title">Admin account</h2>
        <div className="admin-job-icon admin-job-icon--account">
          <AccountIcon />
        </div>
      </div>
      <form className="settings-form" onSubmit={handleSubmit}>
        {error && <p className="auth-error">{error}</p>}
        <label>
          Signed in as
          <input
            type="email"
            name="username"
            value={adminEmail}
            autoComplete="username"
            readOnly
            disabled
          />
        </label>
        <label>
          Current password
          <input
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            required
            autoComplete="current-password"
          />
        </label>
        <label>
          New password
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            minLength={4}
            required
            autoComplete="new-password"
          />
        </label>
        <label>
          Confirm new password
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            minLength={4}
            required
            autoComplete="new-password"
          />
        </label>
        <p className="settings-form__hint">At least 4 characters.</p>
        <div className="settings-form-actions">
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? "Updating…" : "Update password"}
          </button>
          {success && <span className="settings-form__success">Password updated</span>}
        </div>
      </form>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                                */
/* ------------------------------------------------------------------ */

export default function Settings() {
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    adminService
      .getSettings()
      .then((res) => {
        if (mounted) setData(res);
      })
      .catch((err) => {
        if (mounted) setError(err instanceof Error ? err.message : "Failed to load settings.");
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <AdminLayout>
      <h1 className="admin-page-title">Settings</h1>
      <p className="admin-page-subtitle">Your studio details (logo, name and contact) and admin account.</p>

      {error && <p className="auth-error">{error}</p>}
      {loading && !data && <div className="empty-state">Loading settings…</div>}

      {data && (
        <div className="settings-grid">
          <div className="admin-two-col-grid">
            <StudioProfileCard
              initial={data.profile}
              onSaved={({ studio, profile }) =>
                setData((prev) => (prev ? { ...prev, studio: studio ?? prev.studio, profile } : prev))
              }
            />
            <AdminAccountCard adminEmail={data.admin.email} />
          </div>
        </div>
      )}
    </AdminLayout>
  );
}
