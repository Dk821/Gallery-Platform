import { ReactNode, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Page } from "../../services/api";
import { superAdminService } from "../../services/superAdmin";
import type { AuditLogRow, PlatformStats, PlatformTrends, Studio, TrendDay, TrendTotals } from "../../types/superAdmin";
import { AreaChart, CHART_COLORS, Donut } from "../../components/superadmin/Charts";
import {
  IconAlbums,
  IconDownload,
  IconMedia,
  IconRefresh,
  IconStudios,
  IconUpload,
  IconUsers,
  IconWarn,
} from "../../components/superadmin/Icons";
import { formatBytes, formatDateTime, formatNumber, humanizeAction, percent } from "../../utils/superAdminFormat";

// The Recent activity list shows only the latest 10 entries (the full history is on the Audit log page).
const RECENT_ACTIVITY_LIMIT = 10;

const RANGES = [7, 30, 90] as const;
type MetricKey = "uploaded_bytes" | "media" | "clients" | "albums" | "downloads";
const METRICS: { key: MetricKey; label: string; unit: "bytes" | "count" }[] = [
  { key: "uploaded_bytes", label: "Uploaded data", unit: "bytes" },
  { key: "media", label: "New files", unit: "count" },
  { key: "clients", label: "New clients", unit: "count" },
  { key: "albums", label: "New albums", unit: "count" },
  { key: "downloads", label: "Downloads", unit: "count" },
];

function remember(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* a private window or blocked storage just forgets the choice */
  }
}
function recall(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

const dayLabel = (iso: string, long = false) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(long ? { weekday: "short", year: "numeric" } : {}),
    timeZone: "UTC",
  });

function csvCell(v: string | number): string {
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
function downloadCsv(filename: string, rows: (string | number)[][]) {
  const blob = new Blob(["﻿" + rows.map((r) => r.map(csvCell).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Change vs. the previous period of the same length. */
function delta(cur: number, prev: number): { text: string; tone: "up" | "down" | "flat" } {
  if (cur === 0 && prev === 0) return { text: "no change", tone: "flat" };
  if (prev === 0) return { text: "new", tone: "up" };
  const pct = Math.round(((cur - prev) / prev) * 100);
  if (pct === 0) return { text: "no change", tone: "flat" };
  return { text: `${pct > 0 ? "+" : ""}${pct}%`, tone: pct > 0 ? "up" : "down" };
}

export default function Dashboard() {
  const [stats, setStats] = useState<PlatformStats | null>(null);
  const [studios, setStudios] = useState<Page<Studio> | null>(null);
  const [logs, setLogs] = useState<Page<AuditLogRow> | null>(null);
  const [trends, setTrends] = useState<PlatformTrends | null>(null);
  const [trendsFailed, setTrendsFailed] = useState(false);
  const [trendsBusy, setTrendsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const [days, setDays] = useState<number>(() => {
    const saved = Number(recall("sa.dashboard.range"));
    return (RANGES as readonly number[]).includes(saved) ? saved : 30;
  });
  const [metric, setMetric] = useState<MetricKey>(() => {
    const saved = recall("sa.dashboard.metric");
    return METRICS.some((m) => m.key === saved) ? (saved as MetricKey) : "uploaded_bytes";
  });

  const loadTrends = useCallback((range: number) => {
    setTrendsBusy(true);
    return superAdminService
      .trends(range)
      .then((t) => {
        setTrends(t);
        setTrendsFailed(false);
      })
      .catch(() => setTrendsFailed(true))
      .finally(() => setTrendsBusy(false));
  }, []);

  const loadAll = useCallback(
    async (range: number) => {
      const [s, st, l] = await Promise.all([
        superAdminService.stats(),
        superAdminService.listStudios({ limit: 200 }),
        superAdminService.auditLogs({ limit: RECENT_ACTIVITY_LIMIT }),
      ]);
      setStats(s);
      setStudios(st);
      setLogs(l);
      setUpdatedAt(new Date());
      await loadTrends(range);
    },
    [loadTrends]
  );

  useEffect(() => {
    let active = true;
    loadAll(days).catch((err) => active && setError(err instanceof Error ? err.message : "Could not load the dashboard."));
    return () => {
      active = false;
    };
    // The first load only; later range changes reload just the charts (below).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const changeRange = (next: number) => {
    if (next === days) return;
    setDays(next);
    remember("sa.dashboard.range", String(next));
    void loadTrends(next);
  };
  const changeMetric = (next: MetricKey) => {
    setMetric(next);
    remember("sa.dashboard.metric", next);
  };
  const refresh = () => {
    setRefreshing(true);
    loadAll(days)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not refresh the dashboard."))
      .finally(() => setRefreshing(false));
  };

  if (error) return <p className="sa-form-error">{error}</p>;
  if (!stats || !studios || !logs) return <p className="sa-muted">Loading…</p>;

  const names = new Map(studios.items.map((s) => [s.id, s.name]));
  const { storage, unmapped_legacy_rows: legacy } = stats;
  const unmappedTotal = legacy.admins + legacy.clients + legacy.albums + legacy.media;
  const oversold = storage.allocated_quota_bytes > storage.capacity_bytes;
  const capacityPct = percent(storage.used_bytes + storage.reserved_bytes, storage.capacity_bytes);
  const series: TrendDay[] = trends?.series ?? [];
  const totals: TrendTotals | null = trends?.totals ?? null;
  const previous: TrendTotals | null = trends?.previous_totals ?? null;
  const activeMetric = METRICS.find((m) => m.key === metric)!;
  const formatMetric = (v: number) => (activeMetric.unit === "bytes" ? formatBytes(v) : formatNumber(Math.round(v)));
  const metricTotal = totals ? totals[metric] : 0;
  const metricDelta = totals && previous ? delta(totals[metric], previous[metric]) : null;
  const rangeLabel = `last ${days} days`;

  const photos = trends?.media_types.photo ?? { files: 0, bytes: 0 };
  const videos = trends?.media_types.video ?? { files: 0, bytes: 0 };
  const mediaTotal = photos.files + videos.files;

  const exportStudios = () =>
    downloadCsv(`studios-${new Date().toISOString().slice(0, 10)}.csv`, [
      ["Studio", "Status", "Quota (bytes)", "Stored (bytes)", "Reserved (bytes)", "Remaining (bytes)", "Used %", "Created"],
      ...studios.items.map((s) => [
        s.name,
        s.status,
        s.usage.quota_bytes,
        s.usage.used_bytes,
        s.usage.reserved_bytes,
        s.usage.remaining_bytes,
        percent(s.usage.used_bytes + s.usage.reserved_bytes, s.usage.quota_bytes).toFixed(1),
        s.created_at,
      ]),
    ]);
  return (
    <>
      <div className="sa-page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="sa-page-head__sub">
            Platform-wide view across every studio.
            {updatedAt && <span className="sa-dash-updated"> Updated {updatedAt.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}.</span>}
          </p>
        </div>
        <div className="sa-dash-tools">
          <div className="sa-seg" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <button key={r} type="button" className={`sa-seg__btn${r === days ? " is-active" : ""}`} aria-pressed={r === days} onClick={() => changeRange(r)}>
                {r}d
              </button>
            ))}
          </div>
          <button type="button" className="sa-btn sa-btn--ghost sa-btn--sm" onClick={refresh} disabled={refreshing} aria-label="Refresh dashboard">
            <span className={refreshing ? "sa-spin" : undefined}>
              <IconRefresh />
            </span>
            Refresh
          </button>
          <button type="button" className="sa-btn sa-btn--ghost sa-btn--sm" onClick={exportStudios}>
            <IconDownload /> Export studios
          </button>
          <Link to="/super-admin/studios?new=1" className="sa-btn sa-btn--dark">
            New studio
          </Link>
        </div>
      </div>

      {unmappedTotal > 0 && (
        <div className="sa-notice sa-notice--warn sa-notice--icon" role="alert">
          <IconWarn />
          <div>
            <strong>Legacy data is not assigned to a studio yet.</strong> {formatNumber(legacy.admins)} admins,{" "}
            {formatNumber(legacy.clients)} clients, {formatNumber(legacy.albums)} albums and {formatNumber(legacy.media)} media
            files have no studio. Studio admins without a studio cannot sign in until you run{" "}
            <code>python -m app.legacy_to_studio</code> on the server.
          </div>
        </div>
      )}

      <section className="sa-kpi-grid" aria-label="Key numbers">
        <Kpi icon={<IconStudios />} label="Studios" value={formatNumber(stats.studios.total)} />
        <Kpi icon={<IconUsers />} label="Clients" value={formatNumber(stats.totals.clients)} />
        <Kpi icon={<IconAlbums />} label="Albums" value={formatNumber(stats.totals.albums)} />
        <Kpi icon={<IconMedia />} label="Media files" value={formatNumber(stats.totals.media)} />
        <Kpi icon={<IconUpload />} label="Stored" value={formatBytes(storage.used_bytes)} />
        <Kpi icon={<IconDownload />} label="Downloads" value={totals ? formatNumber(totals.downloads) : "—"} />
      </section>

      <div className="sa-dash-row">
        <section className={`sa-card sa-chart-card${trendsBusy ? " is-busy" : ""}`}>
          <div className="sa-card__head">
            <div>
              <h2>Platform activity</h2>
              <span className="sa-muted sa-small">{`Last ${days} days (UTC)`}</span>
            </div>
            {totals && (
              <div className="sa-chart-card__total">
                <strong>{formatMetric(metricTotal)}</strong>
                {metricDelta && (
                  <span className={`sa-delta sa-delta--${metricDelta.tone}`}>
                    {metricDelta.text === "new" ? `none in the previous ${days}d` : metricDelta.text === "no change" ? `same as previous ${days}d` : `${metricDelta.text} vs previous ${days}d`}
                  </span>
                )}
              </div>
            )}
          </div>
          <div className="sa-tabs" role="tablist" aria-label="Chart metric">
            {METRICS.map((m) => (
              <button key={m.key} type="button" role="tab" aria-selected={m.key === metric} className={`sa-tabs__btn${m.key === metric ? " is-active" : ""}`} onClick={() => changeMetric(m.key)}>
                {m.label}
              </button>
            ))}
          </div>
          {trendsFailed && !trends ? (
            <p className="sa-notice sa-notice--warn" role="status">
              Activity data could not be loaded. <button type="button" className="sa-linkbtn" onClick={() => void loadTrends(days)}>Try again</button>
            </p>
          ) : (
            <AreaChart
              points={series.map((d) => ({ label: dayLabel(d.date, true), short: dayLabel(d.date), value: d[metric] }))}
              format={formatMetric}
              color={CHART_COLORS[0]}
              height={310}
              ariaLabel={`${activeMetric.label} per day over the last ${days} days: ${formatMetric(metricTotal)} in total`}
            />
          )}
        </section>
      </div>

      <div className="sa-dash-row sa-dash-row--three">
        <section className="sa-card">
          <div className="sa-card__head">
            <h2>Platform storage</h2>
            <span className="sa-muted sa-small">Capacity is set by the platform</span>
          </div>
          <div className="sa-storage-card">
            <Donut
              ariaLabel={`Platform storage is ${capacityPct.toFixed(0)}% full`}
              slices={[
                { label: "Stored", value: storage.used_bytes, color: CHART_COLORS[0] },
                { label: "Reserved", value: storage.reserved_bytes, color: CHART_COLORS[2] },
              ]}
            >
              <strong>{capacityPct.toFixed(capacityPct >= 10 ? 0 : 1)}%</strong>
              <span>full</span>
            </Donut>
            <ul className="sa-legend">
              <Legend color={CHART_COLORS[0]} label="Stored" value={formatBytes(storage.used_bytes)} />
              <Legend color={CHART_COLORS[2]} label="Reserved by uploads" value={formatBytes(storage.reserved_bytes)} />
              <Legend color="var(--sa-track)" label="Remaining" value={formatBytes(storage.remaining_bytes)} />
            </ul>
          </div>
          <dl className="sa-kv sa-kv--row sa-kv--compact">
            <div>
              <dt>Capacity</dt>
              <dd>{formatBytes(storage.capacity_bytes)}</dd>
            </div>
            <div>
              <dt>Allocated to studios</dt>
              <dd>
                {formatBytes(storage.allocated_quota_bytes)}
                {oversold && <span className="sa-badge sa-badge--warn sa-badge--inline">oversold</span>}
              </dd>
            </div>
          </dl>
          {capacityPct >= 80 && (
            <p className="sa-notice sa-notice--warn" role="status">
              Platform storage is {capacityPct.toFixed(0)}% full. New uploads are rejected once capacity is reached.
            </p>
          )}
          {oversold && (
            <p className="sa-muted sa-small">
              Studio quotas add up to more than the platform capacity. That is allowed, but the platform limit will stop uploads first.
            </p>
          )}
        </section>

        <section className="sa-card">
          <div className="sa-card__head">
            <h2>Library mix</h2>
            <span className="sa-muted sa-small">All studios</span>
          </div>
          <div className="sa-storage-card">
            <Donut
              size={150}
              thickness={18}
              ariaLabel={`${formatNumber(photos.files)} photos and ${formatNumber(videos.files)} videos`}
              slices={[
                { label: "Photos", value: photos.bytes, color: CHART_COLORS[0] },
                { label: "Videos", value: videos.bytes, color: CHART_COLORS[1] },
              ]}
            >
              <strong>{formatNumber(mediaTotal)}</strong>
              <span>files</span>
            </Donut>
            <ul className="sa-legend">
              <Legend color={CHART_COLORS[0]} label="Photos" value={`${formatNumber(photos.files)} · ${formatBytes(photos.bytes)}`} />
              <Legend color={CHART_COLORS[1]} label="Videos" value={`${formatNumber(videos.files)} · ${formatBytes(videos.bytes)}`} />
            </ul>
          </div>
          <h3 className="sa-subhead">Studios</h3>
          <div className="sa-split" aria-label={`${stats.studios.active} active, ${stats.studios.suspended} suspended`}>
            <div className="sa-split__bar">
              <span className="sa-split__seg sa-split__seg--ok" style={{ width: `${percent(stats.studios.active, stats.studios.total)}%` }} />
              <span className="sa-split__seg sa-split__seg--off" style={{ width: `${percent(stats.studios.suspended, stats.studios.total)}%` }} />
            </div>
            <div className="sa-split__legend">
              <span>
                <i className="sa-dot sa-dot--ok" /> {stats.studios.active} active
              </span>
              <span>
                <i className="sa-dot sa-dot--off" /> {stats.studios.suspended} suspended
              </span>
            </div>
          </div>
        </section>

        <section className="sa-card">
          <div className="sa-card__head">
            <h2>Most active studios</h2>
            <span className="sa-muted sa-small">Uploads, {rangeLabel}</span>
          </div>
          {!trends || trends.most_active_studios.length === 0 ? (
            <p className="sa-muted">{trends ? "No uploads in this period." : "No data."}</p>
          ) : (
            <ol className="sa-rank">
              {trends.most_active_studios.map((s, i) => (
                <li key={s.studio_id}>
                  <span className="sa-rank__n">{i + 1}</span>
                  <Link to={`/super-admin/studios/${s.studio_id}`} className="sa-rank__name">
                    {s.name}
                  </Link>
                  <span className="sa-rank__val">
                    <strong>{formatBytes(s.uploaded_bytes)}</strong>
                    <small>{formatNumber(s.files)} files</small>
                  </span>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>

      <div className="sa-dash-row">
        <section className="sa-card">
          <div className="sa-card__head">
            <div>
              <h2>Recent activity</h2>
              <span className="sa-muted sa-small">{`Latest ${RECENT_ACTIVITY_LIMIT} events`}</span>
            </div>
            <Link to="/super-admin/audit-logs">Audit log</Link>
          </div>
          {logs.items.length === 0 ? (
            <p className="sa-muted">Nothing recorded yet.</p>
          ) : (
            <ul className="sa-list">
              {logs.items.slice(0, RECENT_ACTIVITY_LIMIT).map((row) => (
                <li key={row.id} className="sa-list__row sa-list__row--tight">
                  <div className="sa-list__main">
                    <span className="sa-list__title">{humanizeAction(row.action)}</span>
                    <span className="sa-muted sa-small">{formatDateTime(row.created_at)}</span>
                  </div>
                  <span className="sa-muted sa-small">
                    {row.studio_id ? (names.get(row.studio_id) ?? `Studio #${row.studio_id}`) : "Platform"}
                    {row.actor_role ? ` · ${row.actor_role.replace("_", " ")}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}

function Kpi({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="sa-kpi">
      <div className="sa-kpi__top">
        <span className="sa-kpi__icon">{icon}</span>
        <span className="sa-kpi__label">{label}</span>
      </div>
      <span className="sa-kpi__value">{value}</span>
    </div>
  );
}

function Legend({ color, label, value }: { color: string; label: string; value: string }) {
  return (
    <li>
      <i className="sa-legend__swatch" style={{ background: color }} />
      <span className="sa-legend__label">{label}</span>
      <strong>{value}</strong>
    </li>
  );
}
