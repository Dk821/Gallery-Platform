import { FormEvent, useEffect, useState } from "react";
import AdminLayout from "../components/AdminLayout";
import { adminService, SettingsResponse } from "../services/admin";

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

function SecurityIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
      <path
        d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3z"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M9.5 12l1.8 1.8L14.5 10" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  Studio profile                                                     */
/* ------------------------------------------------------------------ */

function StudioProfileCard({
  initial,
  onSaved,
}: {
  initial: SettingsResponse["studio"];
  onSaved: (studio: SettingsResponse["studio"]) => void;
}) {
  const [studioName, setStudioName] = useState(initial.studio_name ?? "");
  const [contactEmail, setContactEmail] = useState(initial.contact_email ?? "");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(false);
    setSaving(true);
    try {
      const updated = await adminService.updateStudioProfile(studioName, contactEmail);
      onSaved(updated);
      setSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save studio profile.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="admin-panel-card">
      <div className="admin-panel-card__header">
        <h2 className="admin-panel-card__title">Studio profile</h2>
        <div className="admin-job-icon admin-job-icon--profile">
          <ProfileIcon />
        </div>
      </div>
      <form className="settings-form" onSubmit={handleSubmit}>
        {error && <p className="auth-error">{error}</p>}
        <label>
          Studio name
          <input
            value={studioName}
            onChange={(e) => setStudioName(e.target.value)}
            placeholder="e.g. Love Story Photography"
            maxLength={255}
          />
        </label>
        <label>
          Contact email
          <input
            type="email"
            value={contactEmail}
            onChange={(e) => setContactEmail(e.target.value)}
            placeholder="hello@yourstudio.com"
          />
        </label>
        <div className="settings-form-actions">
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? "Saving…" : "Save profile"}
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
            minLength={8}
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
            minLength={8}
            required
            autoComplete="new-password"
          />
        </label>
        <p className="settings-form__hint">At least 8 characters.</p>
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
/*  Security & download policy                                         */
/* ------------------------------------------------------------------ */

function SecurityPolicyCard({
  initial,
  onSaved,
}: {
  initial: SettingsResponse["studio"];
  onSaved: (studio: SettingsResponse["studio"]) => void;
}) {
  const [minPasswordLength, setMinPasswordLength] = useState(initial.min_client_password_length);
  const [ttlHours, setTtlHours] = useState(initial.download_link_ttl_hours);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(false);
    setSaving(true);
    try {
      const updated = await adminService.updateSecurityPolicy(minPasswordLength, ttlHours);
      onSaved(updated);
      setSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save security policy.");
    } finally {
      setSaving(false);
    }
  }

  const ttlDays = (ttlHours / 24).toFixed(1).replace(/\.0$/, "");

  return (
    <div className="admin-panel-card">
      <div className="admin-panel-card__header">
        <h2 className="admin-panel-card__title">Security &amp; download policy</h2>
        <div className="admin-job-icon admin-job-icon--security">
          <SecurityIcon />
        </div>
      </div>
      <form className="settings-form" onSubmit={handleSubmit}>
        {error && <p className="auth-error">{error}</p>}
        <label>
          Minimum client password length
          <input
            type="number"
            value={minPasswordLength}
            onChange={(e) => setMinPasswordLength(Number(e.target.value))}
            min={4}
            max={32}
            required
          />
        </label>
        <p className="settings-form__hint">
          Applies to new and changed gallery/download passwords going forward - existing passwords aren't
          affected.
        </p>
        <label>
          Download link expiry (hours)
          <input
            type="number"
            value={ttlHours}
            onChange={(e) => setTtlHours(Number(e.target.value))}
            min={1}
            max={720}
            required
          />
        </label>
        <p className="settings-form__hint">
          A completed ZIP download stays available for {ttlHours} hour{ttlHours === 1 ? "" : "s"} (~
          {ttlDays} day{ttlDays === "1" ? "" : "s"}) after it finishes, then expires.
        </p>
        <div className="settings-form-actions">
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? "Saving…" : "Save policy"}
          </button>
          {success && <span className="settings-form__success">Saved</span>}
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
      <p className="admin-page-subtitle">Your studio profile, admin account, and download security policy.</p>

      {error && <p className="auth-error">{error}</p>}
      {loading && !data && <div className="empty-state">Loading settings…</div>}

      {data && (
        <div className="settings-grid">
          <div className="admin-two-col-grid">
            <StudioProfileCard
              initial={data.studio}
              onSaved={(studio) => setData((prev) => (prev ? { ...prev, studio } : prev))}
            />
            <AdminAccountCard adminEmail={data.admin.email} />
          </div>
          <SecurityPolicyCard
            initial={data.studio}
            onSaved={(studio) => setData((prev) => (prev ? { ...prev, studio } : prev))}
          />
        </div>
      )}
    </AdminLayout>
  );
}
