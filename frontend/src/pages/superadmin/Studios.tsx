import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Page } from "../../services/api";
import { superAdminService } from "../../services/superAdmin";
import type { Studio, StudioStatus } from "../../types/superAdmin";
import Modal from "../../components/superadmin/Modal";
import Pagination from "../../components/superadmin/Pagination";
import SecretModal from "../../components/superadmin/SecretModal";
import RowActionsMenu from "../../components/superadmin/RowActionsMenu";
import { useStudioLifecycle } from "../../components/superadmin/StudioLifecycleDialogs";
import { StudioLoginMenu } from "../../components/superadmin/StudioLogin";
import StudioProfileForm from "../../components/superadmin/StudioProfileForm";
import StudioQuotaCard from "../../components/superadmin/StudioQuotaCard";
import StatusBadge from "../../components/superadmin/StatusBadge";
import UsageMeter from "../../components/superadmin/UsageMeter";
import { IconSearch } from "../../components/superadmin/Icons";
import { useToast } from "../../components/superadmin/Toast";
import { BYTE_UNITS, ByteUnit, formatDate, formatNumber, toBytes } from "../../utils/superAdminFormat";
import { useDebounced } from "../../utils/useDebounced";
import { phoneError, sanitizePhoneInput } from "../../utils/phone";

const LIMIT = 20;
const LOGO_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
const LOGO_MAX_BYTES = 5 * 1024 * 1024;

export default function Studios() {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StudioStatus | "">("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Page<Studio> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(params.get("new") === "1");
  const toast = useToast();
  // Which studio's "Edit" dialog is open (by id, so the dialog always
  // shows the freshly reloaded row rather than a stale copy).
  const [editingId, setEditingId] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const debouncedSearch = useDebounced(search);
  const lifecycle = useStudioLifecycle(() => setReloadKey((k) => k + 1));

  useEffect(() => setPage(1), [debouncedSearch, status]);

  // The console's top search box sends you here with ?q=<text>.
  const incomingQuery = params.get("q");
  useEffect(() => {
    if (incomingQuery === null) return;
    setSearch(incomingQuery);
    const next = new URLSearchParams(params);
    next.delete("q");
    setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incomingQuery]);

  useEffect(() => {
    let active = true;
    setError(null);
    superAdminService
      .listStudios({ page, limit: LIMIT, search: debouncedSearch, status })
      .then((d) => active && setData(d))
      .catch((err) => active && setError(err instanceof Error ? err.message : "Could not load studios."));
    return () => {
      active = false;
    };
  }, [page, debouncedSearch, status, reloadKey]);

  const editing = data?.items.find((s) => s.id === editingId) ?? null;

  function closeCreate() {
    setCreating(false);
    if (params.has("new")) {
      params.delete("new");
      setParams(params, { replace: true });
    }
  }

  return (
    <>
      <div className="sa-page-head">
        <div>
          <h1>Studios</h1>
          <p className="sa-page-head__sub">Every photography studio on the platform.</p>
        </div>
        <button className="sa-btn sa-btn--dark" onClick={() => setCreating(true)}>
          New studio
        </button>
      </div>

      <div className="sa-toolbar">
        <label className="sa-search">
          <IconSearch />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by name or email" aria-label="Search studios" />
        </label>
        <select value={status} onChange={(e) => setStatus(e.target.value as StudioStatus | "")} aria-label="Filter by status">
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="suspended">Suspended</option>
        </select>
      </div>

      {error && <p className="sa-form-error">{error}</p>}
      {!data && !error && <p className="sa-muted">Loading…</p>}

      {data && (
        <div className="sa-card sa-card--flush">
          {data.items.length === 0 ? (
            <p className="sa-empty">{debouncedSearch || status ? "No studios match these filters." : "No studios yet. Create the first one."}</p>
          ) : (
            <div className="sa-table-wrap">
              <table className="sa-table">
                <thead>
                  <tr>
                    <th>Studio</th>
                    <th>Status</th>
                    <th className="sa-col-usage">Storage</th>
                    <th>Contact</th>
                    <th>Created</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((s) => (
                    <tr key={s.id}>
                      <td>
                        <Link to={`/super-admin/studios/${s.id}`} className="sa-table__title">
                          {s.name}
                        </Link>
                      </td>
                      <td>
                        <StatusBadge status={s.status} />
                      </td>
                      <td className="sa-col-usage">
                        <UsageMeter compact used={s.usage.used_bytes} reserved={s.usage.reserved_bytes} total={s.usage.quota_bytes} />
                      </td>
                      <td className="sa-muted">{s.contact_email ?? "—"}</td>
                      <td className="sa-muted sa-nowrap">{formatDate(s.created_at)}</td>
                      <td className="sa-table__actions">
                        <button className="sa-btn sa-btn--ghost sa-btn--sm" onClick={() => setEditingId(s.id)}>
                          Edit
                        </button>{" "}
                        <StudioLoginMenu studioId={s.id} onChanged={() => setReloadKey((k) => k + 1)} />{" "}
                        <RowActionsMenu
                          label="More"
                          actions={[
                            s.status === "suspended"
                              ? { label: "Reactivate studio", onSelect: () => lifecycle.openReactivate(s) }
                              : { label: "Suspend studio", onSelect: () => lifecycle.openSuspend(s) },
                            {
                              label: "Delete studio",
                              danger: true,
                              separated: true,
                              disabled: s.status !== "suspended",
                              hint: s.status !== "suspended" ? "Suspend the studio first" : undefined,
                              onSelect: () => lifecycle.openDelete(s),
                            },
                          ]}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pagination page={data.page} limit={data.limit} total={data.total} onPage={setPage} />
        </div>
      )}
      {data && <p className="sa-muted sa-small">{formatNumber(data.total)} studio(s)</p>}

      {creating && <CreateStudioModal onClose={closeCreate} />}

      {lifecycle.dialogs}

      {editing && (
        <Modal title={`Edit ${editing.name}`} onClose={() => setEditingId(null)} wide>
          <h4 className="sa-form-section">Studio details</h4>
          <StudioProfileForm
            studio={editing}
            onSaved={() => {
              toast.success("Studio details saved.");
              setReloadKey((k) => k + 1);
            }}
            onLogoChanged={(message) => {
              toast.success(message);
              setReloadKey((k) => k + 1);
            }}
          />
          <h4 className="sa-form-section">Storage quota</h4>
          <StudioQuotaCard
            bare
            studio={editing}
            onSaved={() => {
              toast.success("Storage quota updated.");
              setReloadKey((k) => k + 1);
            }}
          />
          <div className="sa-modal-card__actions">
            <Link to={`/super-admin/studios/${editing.id}`} className="sa-btn sa-btn--ghost">
              Open full page
            </Link>
            <button type="button" className="sa-btn sa-btn--dark" onClick={() => setEditingId(null)}>
              Close
            </button>
          </div>
        </Modal>
      )}

    </>
  );
}

function CreateStudioModal({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [name, setName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [quotaValue, setQuotaValue] = useState("");
  const [quotaUnit, setQuotaUnit] = useState<ByteUnit>("GB");
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [logo, setLogo] = useState<File | null>(null);
  const [logoPreview, setLogoPreview] = useState<string | null>(null);
  const logoInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ studioId: number; email: string; password: string } | null>(null);

  useEffect(() => {
    if (!logo) {
      setLogoPreview(null);
      return;
    }
    const url = URL.createObjectURL(logo);
    setLogoPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [logo]);

  function pickLogo(file: File | undefined) {
    if (!file) return;
    setError(null);
    if (!LOGO_TYPES.includes(file.type)) {
      setError("Choose a PNG, JPG, WebP or GIF image for the logo.");
      return;
    }
    if (file.size > LOGO_MAX_BYTES) {
      setError("The logo must be 5 MB or smaller.");
      return;
    }
    setLogo(file);
  }

  const submit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      setError(null);

      let quotaBytes: number | null = null;
      if (quotaValue.trim()) {
        quotaBytes = toBytes(quotaValue, quotaUnit);
        if (quotaBytes === null) {
          setError("Storage quota must be a positive number.");
          return;
        }
      }
      const phoneProblem = phoneError(contactPhone);
      if (phoneProblem) {
        setError(phoneProblem);
        return;
      }
      if (adminPassword && adminPassword.length < 4) {
        setError("A password you set must be at least 4 characters. Leave it blank to generate one.");
        return;
      }

      setBusy(true);
      try {
        const res = await superAdminService.createStudio({
          name: name.trim(),
          contact_email: contactEmail.trim() || null,
          contact_phone: contactPhone.trim() || null,
          quota_bytes: quotaBytes,
          admin_name: adminName.trim(),
          admin_email: adminEmail.trim(),
          admin_password: adminPassword || null,
        });
        setAdminPassword("");
        if (logo) {
          // The logo is a picture upload, sent right after the studio exists. If it fails the
          // studio and its login are still created; the logo can be added from the studio page.
          try {
            await superAdminService.uploadLogo(res.studio.id, logo);
          } catch {
            toast.error("The studio was created, but its logo could not be uploaded. Add it from the studio page.");
          }
        }
        if (res.temporary_password) {
          setCreated({ studioId: res.studio.id, email: res.admin.email, password: res.temporary_password });
        } else {
          toast.success(`Studio “${res.studio.name}” created.`);
          navigate(`/super-admin/studios/${res.studio.id}`);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not create the studio.");
      } finally {
        setBusy(false);
      }
    },
    [name, contactEmail, contactPhone, quotaValue, quotaUnit, adminName, adminEmail, adminPassword, logo, navigate, toast]
  );

  if (created) {
    return (
      <SecretModal
        title="Studio created"
        subject={created.email}
        password={created.password}
        onClose={() => navigate(`/super-admin/studios/${created.studioId}`)}
      />
    );
  }

  return (
    <Modal title="New studio" description="Creates the studio and its one login account together." onClose={busy ? () => {} : onClose} wide>
      <form onSubmit={submit} className="sa-form-grid">
        {error && (
          <p className="sa-form-error sa-form-grid__full" role="alert">
            {error}
          </p>
        )}

        <h4 className="sa-form-grid__full sa-form-section">Studio</h4>
        <label className="sa-field sa-form-grid__full">
          <span>Studio name *</span>
          <input placeholder="Enter studio name" value={name} onChange={(e) => setName(e.target.value)} maxLength={255} required autoFocus />
        </label>
        <label className="sa-field">
          <span>Contact email</span>
          <input placeholder="Enter email address" type="email" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} />
        </label>
        <label className="sa-field">
          <span>Contact phone</span>
          <input type="tel" inputMode="tel" value={contactPhone} onChange={(e) => setContactPhone(sanitizePhoneInput(e.target.value))} maxLength={20} placeholder="Enter mobile number" autoComplete="tel" />
        </label>
        <div className="sa-field sa-form-grid__full">
          <span>Logo</span>
          <div className="sa-logo-field">
            <div className="sa-logo-field__preview">
              {logoPreview ? <img src={logoPreview} alt="Logo preview" /> : <span>No logo</span>}
            </div>
            <div className="sa-logo-field__body">
              <div className="sa-logo-field__actions">
                <button type="button" className="sa-btn sa-btn--ghost sa-btn--sm" onClick={() => logoInput.current?.click()}>
                  {logo ? "Replace image" : "Upload image"}
                </button>
                {logo && (
                  <button
                    type="button"
                    className="sa-btn sa-btn--danger-outline sa-btn--sm"
                    onClick={() => {
                      setLogo(null);
                      if (logoInput.current) logoInput.current.value = "";
                    }}
                  >
                    Remove
                  </button>
                )}
              </div>
              <small>Optional. PNG, JPG, WebP or GIF, up to 5 MB.</small>
            </div>
            <input
              ref={logoInput}
              type="file"
              accept={LOGO_TYPES.join(",")}
              hidden
              aria-label="Logo image file"
              onChange={(e) => pickLogo(e.target.files?.[0])}
            />
          </div>
        </div>
        <div className="sa-field sa-form-grid__full">
          <span>Storage quota</span>
          <div className="sa-input-group">
            <input
              inputMode="decimal"
              value={quotaValue}
              onChange={(e) => setQuotaValue(e.target.value)}
              placeholder="Leave blank for the platform default"
              aria-label="Storage quota"
            />
            <select value={quotaUnit} onChange={(e) => setQuotaUnit(e.target.value as ByteUnit)} aria-label="Quota unit">
              {BYTE_UNITS.map((u) => (
                <option key={u.label} value={u.label}>
                  {u.label}
                </option>
              ))}
            </select>
          </div>

        </div>

        <h4 className="sa-form-grid__full sa-form-section">Studio login account</h4>
        <label className="sa-field">
          <span>Login name *</span>
          <input placeholder="Enter admin name" value={adminName} onChange={(e) => setAdminName(e.target.value)} maxLength={255} required />
        </label>
        <label className="sa-field">
          <span>Login email *</span>
          <input placeholder="Enter email address" type="email" value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} autoComplete="off" required />
        </label>
        <label className="sa-field sa-form-grid__full">
          <span>Password</span>
          <input
            type="password"
            value={adminPassword}
            onChange={(e) => setAdminPassword(e.target.value)}
            autoComplete="new-password"
            placeholder="Leave blank to generate a temporary password"
          />
          <small>A generated password is shown once, right after creation.</small>
        </label>

        <div className="sa-modal-card__actions sa-form-grid__full">
          <button type="button" className="sa-btn sa-btn--ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="sa-btn sa-btn--dark" disabled={busy}>
            {busy ? "Creating…" : "Create studio"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
