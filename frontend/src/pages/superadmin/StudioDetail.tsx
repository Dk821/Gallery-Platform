import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiRequestError, assetUrl, Page } from "../../services/api";
import { superAdminService } from "../../services/superAdmin";
import type { AuditLogRow, StudioDetail as StudioDetailT } from "../../types/superAdmin";
import { useStudioLifecycle } from "../../components/superadmin/StudioLifecycleDialogs";
import StatusBadge from "../../components/superadmin/StatusBadge";
import { StudioLoginCard } from "../../components/superadmin/StudioLogin";
import StudioProfileForm from "../../components/superadmin/StudioProfileForm";
import StudioQuotaCard from "../../components/superadmin/StudioQuotaCard";
import { useToast } from "../../components/superadmin/Toast";
import { formatDate, formatDateTime, formatNumber, humanizeAction } from "../../utils/superAdminFormat";

export default function StudioDetail() {
  const { studioId } = useParams();
  const id = Number(studioId);
  const toast = useToast();

  const [studio, setStudio] = useState<StudioDetailT | null>(null);
  const [logs, setLogs] = useState<Page<AuditLogRow> | null>(null);
  const [error, setError] = useState<{ message: string; notFound: boolean } | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([
        superAdminService.getStudio(id),
        superAdminService.auditLogs({ studio_id: id, limit: 10 }),
      ]);
      setStudio(s);
      setLogs(l);
      setError(null);
    } catch (err) {
      setError({
        message: err instanceof Error ? err.message : "Could not load this studio.",
        notFound: err instanceof ApiRequestError && err.status === 404,
      });
    }
  }, [id]);

  useEffect(() => {
    if (!Number.isInteger(id) || id < 1) {
      setError({ message: "Studio not found.", notFound: true });
      return;
    }
    load();
  }, [id, load]);

  const navigate = useNavigate();
  const lifecycle = useStudioLifecycle(load, () => navigate("/super-admin/studios", { replace: true }));

  if (error) {
    return (
      <>
        <p className="sa-form-error">{error.message}</p>
        <Link to="/super-admin/studios">← Back to studios</Link>
      </>
    );
  }
  if (!studio) return <p className="sa-muted">Loading…</p>;

  const suspended = studio.status === "suspended";

  return (
    <>
      <p className="sa-crumbs">
        <Link to="/super-admin/studios">Studios</Link> / <span>{studio.name}</span>
      </p>
      <div className="sa-page-head">
        <div className="sa-page-head__title">
          {studio.logo_url && <img className="sa-studio-logo" src={assetUrl(studio.logo_url) ?? ""} alt="" referrerPolicy="no-referrer" />}
          <div>
            <h1>
              {studio.name} <StatusBadge status={studio.status} />
            </h1>
            <p className="sa-page-head__sub">
              Created {formatDate(studio.created_at)}
              {studio.contact_email ? ` · ${studio.contact_email}` : ""}
            </p>
          </div>
        </div>
        {suspended ? (
          <div className="sa-page-head__actions">
            <button className="sa-btn sa-btn--danger-outline" onClick={() => lifecycle.openDelete(studio)}>
              Delete studio
            </button>{" "}
            <button className="sa-btn sa-btn--dark" onClick={() => lifecycle.openReactivate(studio)}>
              Reactivate studio
            </button>
          </div>
        ) : (
          <button className="sa-btn sa-btn--danger-outline" onClick={() => lifecycle.openSuspend(studio)}>
            Suspend studio
          </button>
        )}
      </div>

      {suspended && (
        <p className="sa-notice sa-notice--danger" role="status">
          This studio is suspended. Its admins can view data but cannot upload, delete or edit, and its clients cannot open their galleries.
        </p>
      )}

      <section className="sa-stat-grid">
        <div className="sa-stat">
          <span className="sa-stat__label">Studio logins</span>
          <span className="sa-stat__value">{formatNumber(studio.counts.admins)}</span>
        </div>
        <div className="sa-stat">
          <span className="sa-stat__label">Clients</span>
          <span className="sa-stat__value">{formatNumber(studio.counts.clients)}</span>
        </div>
        <div className="sa-stat">
          <span className="sa-stat__label">Albums</span>
          <span className="sa-stat__value">{formatNumber(studio.counts.albums)}</span>
        </div>
        <div className="sa-stat">
          <span className="sa-stat__label">Media files</span>
          <span className="sa-stat__value">{formatNumber(studio.counts.media)}</span>
        </div>
      </section>

      <StudioQuotaCard
        studio={studio}
        onSaved={() => {
          toast.success("Storage quota updated.");
          load();
        }}
      />

      <section className="sa-card">
        <div className="sa-card__head">
          <h2>Studio details</h2>
        </div>
        <StudioProfileForm
          studio={studio}
          onSaved={() => {
            toast.success("Studio details saved.");
            load();
          }}
          onLogoChanged={(message) => {
            toast.success(message);
            load();
          }}
        />
      </section>

      <StudioLoginCard studioId={studio.id} onChanged={load} />

      <section className="sa-card">
        <div className="sa-card__head">
          <h2>Recent activity</h2>
          <Link to={`/super-admin/audit-logs?studio=${studio.id}`}>Full audit log</Link>
        </div>
        {!logs || logs.items.length === 0 ? (
          <p className="sa-muted">No activity recorded for this studio yet.</p>
        ) : (
          <ul className="sa-list">
            {logs.items.map((row) => (
              <li key={row.id} className="sa-list__row sa-list__row--tight">
                <span className="sa-list__title">{humanizeAction(row.action)}</span>
                <span className="sa-muted sa-small">
                  {formatDateTime(row.created_at)}
                  {row.actor_role ? ` · ${row.actor_role.replace("_", " ")}` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {lifecycle.dialogs}

    </>
  );
}
