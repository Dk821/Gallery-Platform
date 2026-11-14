import { FormEvent, useEffect, useState } from "react";
import { useRefreshCurrentUser } from "../../components/superadmin/RequireSuperAdmin";
import PlatformLogoField from "../../components/superadmin/PlatformLogoField";
import { useToast } from "../../components/superadmin/Toast";
import { ApiRequestError } from "../../services/api";
import { superAdminService } from "../../services/superAdmin";
import type { SuperAdminAccount } from "../../types/superAdmin";
import { formatDateTime } from "../../utils/superAdminFormat";
import { phoneError, sanitizePhoneInput } from "../../utils/phone";

const MIN_PASSWORD_LENGTH = 4;

// Choices kept in this browser only (they are read by the Dashboard and the Audit log pages).
function recall(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function remember(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* blocked storage just forgets the choice */
  }
}

export default function Settings() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [account, setAccount] = useState<SuperAdminAccount | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const reloadAccount = () =>
    superAdminService
      .account()
      .then(setAccount)
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Could not load your account."));
  useEffect(() => {
    reloadAccount();
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (next.length < MIN_PASSWORD_LENGTH) {
      setError(`The new password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    if (next !== confirm) {
      setError("The new password and its confirmation do not match.");
      return;
    }
    if (next === current) {
      setError("The new password must be different from the current one.");
      return;
    }
    setBusy(true);
    try {
      await superAdminService.changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      toast.success("Password updated. Other devices have been signed out.");
    } catch (err) {
      setError(
        err instanceof ApiRequestError && err.code === "INVALID_CURRENT_PASSWORD"
          ? "The current password is not correct."
          : err instanceof Error
            ? err.message
            : "Could not update the password."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="sa-page-head">
        <div>
          <h1>Settings</h1>
          <p className="sa-page-head__sub">Your platform administrator account.</p>
        </div>
      </div>

      <AccountCard account={account} loadError={loadError} onSaved={setAccount} />
      <div className="sa-dash-row sa-dash-row--two">
        <PreferencesCard />

        <section className="sa-card">
          <div className="sa-card__head">
            <h2>Change password</h2>
            <span className="sa-muted sa-small">Changing it signs out every other device.</span>
          </div>
          <form onSubmit={submit} className="sa-stack" style={{ maxWidth: 420 }}>
            {error && (
              <p className="sa-form-error" role="alert">
                {error}
              </p>
            )}
            <label className="sa-field">
              <span>Current password</span>
              <input
                type="password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <label className="sa-field">
              <span>New password</span>
              <input
                type="password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                autoComplete="new-password"
                minLength={MIN_PASSWORD_LENGTH}
                required
              />
              <small>At least {MIN_PASSWORD_LENGTH} characters.</small>
            </label>
            <label className="sa-field">
              <span>Confirm new password</span>
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                minLength={MIN_PASSWORD_LENGTH}
                required
              />
            </label>
            <div className="sa-form-actions">
              <button type="submit" className="sa-btn sa-btn--dark" disabled={busy}>
                {busy ? "Updating…" : "Update password"}
              </button>
            </div>
          </form>
        </section>
      </div>
    </>
  );
}

/** Name, sign-in email, company name, logo and contact number. A new email needs the current password. */
function AccountCard({
  account,
  loadError,
  onSaved,
}: {
  account: SuperAdminAccount | null;
  loadError: string | null;
  onSaved: (a: SuperAdminAccount) => void;
}) {
  const toast = useToast();
  const refreshUser = useRefreshCurrentUser();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (account) {
      setName(account.name);
      setEmail(account.email);
      setCompany(account.company_name ?? "");
      setPhone(account.contact_phone ?? "");
    }
  }, [account]);

  const emailChanged = !!account && email.trim().toLowerCase() !== account.email.toLowerCase();
  const companyChanged = !!account && company.trim() !== (account.company_name ?? "");
  const phoneChanged = !!account && phone.trim() !== (account.contact_phone ?? "");
  const dirty = !!account && (name.trim() !== account.name || emailChanged || companyChanged || phoneChanged);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!account) return;
    setError(null);
    if (!name.trim()) {
      setError("Enter your name.");
      return;
    }
    const phoneProblem = phoneError(phone);
    if (phoneProblem) {
      setError(phoneProblem);
      return;
    }
    setBusy(true);
    try {
      const saved = await superAdminService.updateAccount({
        ...(name.trim() !== account.name ? { name: name.trim() } : {}),
        ...(emailChanged ? { email: email.trim(), current_password: password } : {}),
        ...(companyChanged ? { company_name: company.trim() } : {}),
        ...(phoneChanged ? { contact_phone: phone.trim() } : {}),
      });
      setPassword("");
      onSaved(saved);
      refreshUser();
      toast.success("Account updated.");
    } catch (err) {
      setError(
        err instanceof ApiRequestError && err.code === "INVALID_CURRENT_PASSWORD"
          ? "Enter your current password to change your email."
          : err instanceof ApiRequestError && err.code === "ADMIN_EMAIL_EXISTS"
            ? "Another account already uses this email."
            : err instanceof Error
              ? err.message
              : "Could not save."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="sa-card">
      <div className="sa-card__head">
        <h2>Account</h2>
        <span className="sa-muted sa-small">Role: Super admin{account ? ` · since ${formatDateTime(account.created_at)}` : ""}</span>
      </div>
      {loadError && <p className="sa-form-error">{loadError}</p>}
      <form onSubmit={save} className="sa-stack" style={{ maxWidth: 420 }}>
        {error && (
          <p className="sa-form-error" role="alert">
            {error}
          </p>
        )}
        {account && (
          <PlatformLogoField
            logoUrl={account.logo_url}
            alt={`${account.company_name || "Company"} logo`}
            onChanged={(saved, message) => {
              onSaved(saved);
              refreshUser();
              toast.success(message);
            }}
          />
        )}
        <label className="sa-field">
          <span>Company name</span>
          <input value={company} onChange={(e) => setCompany(e.target.value)} maxLength={255} disabled={!account} placeholder="Enter company name" />
        </label>
        <label className="sa-field">
          <span>Contact number</span>
          <input type="tel" value={phone} onChange={(e) => setPhone(sanitizePhoneInput(e.target.value))} maxLength={20} disabled={!account} placeholder="Enter mobile number" autoComplete="tel" />
        </label>
        <label className="sa-field">
          <span>Name</span>
          <input placeholder="Enter your name" value={name} onChange={(e) => setName(e.target.value)} maxLength={255} disabled={!account} required />
        </label>
        <label className="sa-field">
          <span>Sign-in email</span>
          <input placeholder="Enter email address" type="email" value={email} onChange={(e) => setEmail(e.target.value)} disabled={!account} required />
        </label>
        {emailChanged && (
          <label className="sa-field">
            <span>Current password</span>
            <input placeholder="Enter current password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            <small>Needed to change the email you sign in with.</small>
          </label>
        )}
        <div className="sa-form-actions">
          <button type="submit" className="sa-btn sa-btn--dark" disabled={busy || !dirty}>
            {busy ? "Saving…" : "Save changes"}
          </button>
        </div>
      </form>
    </section>
  );
}

const DASH_RANGES = [7, 30, 90];
const AUDIT_RANGES: { key: string; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
  { key: "any", label: "Any time" },
];

/** Defaults for the Dashboard and Audit log. They apply in this browser only. */
function PreferencesCard() {
  const toast = useToast();
  const [dashRange, setDashRange] = useState(() => (DASH_RANGES.includes(Number(recall("sa.dashboard.range"))) ? recall("sa.dashboard.range")! : "30"));
  const [pageSize, setPageSize] = useState(() => (["25", "50", "100"].includes(recall("sa.audit.pageSize") ?? "") ? recall("sa.audit.pageSize")! : "50"));
  const [auditRange, setAuditRange] = useState(() => (AUDIT_RANGES.some((r) => r.key === recall("sa.audit.range")) ? recall("sa.audit.range")! : "today"));

  function pick(key: string, value: string, set: (v: string) => void) {
    set(value);
    remember(key, value);
    toast.success("Preference saved.");
  }

  return (
    <section className="sa-card">
      <div className="sa-card__head">
        <h2>Preferences</h2>
        <span className="sa-muted sa-small">What the Dashboard and Audit log open with. Saved in this browser.</span>
      </div>
      <div className="sa-form-grid">
        <label className="sa-field">
          <span>Dashboard range</span>
          <select value={dashRange} onChange={(e) => pick("sa.dashboard.range", e.target.value, setDashRange)}>
            {DASH_RANGES.map((d) => (
              <option key={d} value={d}>
                Last {d} days
              </option>
            ))}
          </select>
        </label>
        <label className="sa-field">
          <span>Audit log opens on</span>
          <select value={auditRange} onChange={(e) => pick("sa.audit.range", e.target.value, setAuditRange)}>
            {AUDIT_RANGES.map((r) => (
              <option key={r.key} value={r.key}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <label className="sa-field">
          <span>Audit log rows per page</span>
          <select value={pageSize} onChange={(e) => pick("sa.audit.pageSize", e.target.value, setPageSize)}>
            {["25", "50", "100"].map((n) => (
              <option key={n} value={n}>
                {n} per page
              </option>
            ))}
          </select>
        </label>
      </div>
    </section>
  );
}
