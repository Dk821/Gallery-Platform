import { useEffect, useMemo, useState } from "react";
import AdminLayout from "../components/AdminLayout";
import { adminService, StorageOverview } from "../services/admin";
import { formatAllocationBytes, formatBytes } from "../utils/format";

type RangeOption = 7 | 30 | 90;

function gaugeClass(percentUsed: number): string {
  if (percentUsed >= 90) return "storage-gauge__fill storage-gauge__fill--danger";
  if (percentUsed >= 75) return "storage-gauge__fill storage-gauge__fill--warning";
  return "storage-gauge__fill";
}

function formatShortDate(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function Storage() {
  const [data, setData] = useState<StorageOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [range, setRange] = useState<RangeOption>(30);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    adminService
      .getStorageOverview(range)
      .then((res) => {
        if (mounted) setData(res);
      })
      .catch((err) => {
        if (mounted) setError(err instanceof Error ? err.message : "Failed to load storage info.");
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [range]);

  // Only label every Nth bar in the chart so 30/90-day views don't turn
  // into an unreadable wall of overlapping date labels.
  const labelEvery = range <= 7 ? 1 : range <= 30 ? 5 : 10;

  const maxDailyBytes = useMemo(() => {
    if (!data) return 1;
    const values = data.daily_transfer.flatMap((d) => [d.upload_bytes, d.download_bytes]);
    return Math.max(...values, 1);
  }, [data]);

  return (
    <AdminLayout>
      <h1 className="admin-page-title">Storage</h1>
      <p className="admin-page-subtitle">How much of your storage allocation you're using, and how it's moving.</p>

      {error && <p className="auth-error">{error}</p>}
      {loading && !data && <div className="empty-state">Loading storage data…</div>}

      {data && (
        <>
          <div className="stat-strip">
            <div className="stat-strip__item">
              <div className="stat-strip__value">{data.our_metadata.total_files}</div>
              <div className="stat-strip__label">Total files</div>
            </div>
            <div className="stat-strip__item">
              <div className="stat-strip__value">{data.our_metadata.total_photos}</div>
              <div className="stat-strip__label">Photos</div>
            </div>
            <div className="stat-strip__item">
              <div className="stat-strip__value">{data.our_metadata.total_videos}</div>
              <div className="stat-strip__label">Videos</div>
            </div>
            <div className="stat-strip__item">
              <div className="stat-strip__value">{formatBytes(data.our_metadata.total_bytes_tracked)}</div>
              <div className="stat-strip__label">Tracked in our records</div>
            </div>
          </div>

          {/* --- This studio's storage allocation --- */}
          <div className="section-header">
            <h2>Your storage allocation</h2>
          </div>
          {data.studio_quota ? (
            <div className="admin-panel-card">
              {(() => {
                const q = data.studio_quota;
                const percent = q.quota_bytes > 0 ? Math.min(100, Math.round(((q.used_bytes + q.reserved_bytes) / q.quota_bytes) * 100)) : 0;
                return (
                  <>
                    <div className="storage-gauge">
                      <div className="storage-gauge__track">
                        <div className={gaugeClass(percent)} style={{ width: `${percent}%` }} />
                      </div>
                      <div className="storage-gauge__pct">{percent}%</div>
                    </div>
                    <div className="stat-strip">
                      <div className="stat-strip__item">
                        <div className="stat-strip__value">{formatAllocationBytes(q.quota_bytes)}</div>
                        <div className="stat-strip__label">Allocated to your studio</div>
                      </div>
                      <div className="stat-strip__item">
                        <div className="stat-strip__value">{formatAllocationBytes(q.used_bytes)}</div>
                        <div className="stat-strip__label">Used</div>
                      </div>
                      <div className="stat-strip__item">
                        <div className="stat-strip__value">{formatAllocationBytes(q.remaining_bytes)}</div>
                        <div className="stat-strip__label">Remaining</div>
                      </div>
                      <div className="stat-strip__item">
                        <div className="stat-strip__value">{formatAllocationBytes(q.reserved_bytes)}</div>
                        <div className="stat-strip__label">Reserved by uploads in progress</div>
                      </div>
                    </div>
                  </>
                );
              })()}
            </div>
          ) : (
            <div className="empty-state">No storage allocation has been set for this studio yet.</div>
          )}

          {/* --- Daily upload/download volume --- */}
          <div className="section-header">
            <h2>Daily transfer volume</h2>
            <div className="storage-range-toggle">
              {([7, 30, 90] as RangeOption[]).map((opt) => (
                <button
                  key={opt}
                  type="button"
                  className={range === opt ? "is-active" : ""}
                  onClick={() => setRange(opt)}
                >
                  {opt}d
                </button>
              ))}
            </div>
          </div>
          <div className="admin-panel-card">
            <div className="storage-chart-legend">
              <span>
                <span className="storage-chart-legend__dot storage-chart-legend__dot--upload" />
                Uploaded
              </span>
              <span>
                <span className="storage-chart-legend__dot storage-chart-legend__dot--download" />
                Downloaded
              </span>
            </div>
            <div className="storage-chart">
              {data.daily_transfer.map((day, i) => (
                <div className="storage-chart__day" key={day.date}>
                  <div className="storage-chart__bars">
                    <div
                      className="storage-chart__bar storage-chart__bar--upload"
                      style={{ height: `${(day.upload_bytes / maxDailyBytes) * 100}%` }}
                      title={`${formatShortDate(day.date)} · Uploaded ${formatBytes(day.upload_bytes)} (${day.upload_count} files)`}
                    />
                    <div
                      className="storage-chart__bar storage-chart__bar--download"
                      style={{ height: `${(day.download_bytes / maxDailyBytes) * 100}%` }}
                      title={`${formatShortDate(day.date)} · Downloaded ${formatBytes(day.download_bytes)} (${day.download_count} downloads)`}
                    />
                  </div>
                  {i % labelEvery === 0 && <div className="storage-chart__label">{formatShortDate(day.date)}</div>}
                </div>
              ))}
            </div>
          </div>

          {/* --- Upload reliability --- */}
          <div className="section-header">
            <h2>Upload reliability</h2>
          </div>
          <div className="admin-panel-card">
            <div className="stat-strip">
              <div className="stat-strip__item">
                <div className="stat-strip__value">
                  {data.upload_reliability.recent_success_rate_percent === null
                    ? "—"
                    : `${data.upload_reliability.recent_success_rate_percent}%`}
                </div>
                <div className="stat-strip__label">
                  Success rate (last {data.upload_reliability.recent_window_days}d)
                </div>
              </div>
              <div className="stat-strip__item">
                <div className="stat-strip__value">{data.upload_reliability.recent_total}</div>
                <div className="stat-strip__label">Upload attempts (recent)</div>
              </div>
              {Object.entries(data.upload_reliability.by_status).map(([status, count]) => (
                <div className="stat-strip__item" key={status}>
                  <div className="stat-strip__value">{count}</div>
                  <div className="stat-strip__label">{status} (all time)</div>
                </div>
              ))}
            </div>
          </div>

          {/* --- Storage by client / file type --- */}
          <div className="section-header">
            <h2>Storage breakdown</h2>
          </div>
          <div className="storage-breakdown-grid">
            {data.storage_by_file_type.map((row) => (
              <div className="storage-type-card" key={row.file_type}>
                <div className="storage-type-card__label">{row.file_type}s</div>
                <div className="storage-type-card__value">{formatBytes(row.total_bytes)}</div>
                <div className="storage-type-card__sub">{row.file_count} files</div>
              </div>
            ))}
          </div>

          <div className="admin-table-responsive">
            <table className="admin-modern-table">
              <thead>
                <tr>
                  <th>Client</th>
                  <th>Files</th>
                  <th>Storage used</th>
                </tr>
              </thead>
              <tbody>
                {data.storage_by_client.length === 0 && (
                  <tr>
                    <td colSpan={3} className="admin-table-empty">
                      No media uploaded yet.
                    </td>
                  </tr>
                )}
                {data.storage_by_client.map((row) => (
                  <tr key={row.client_id}>
                    <td>{row.client_name}</td>
                    <td>{row.file_count}</td>
                    <td>{formatBytes(row.total_bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* --- Largest files --- */}
          <div className="section-header">
            <h2>Largest files</h2>
          </div>
          <div className="admin-table-responsive">
            <table className="admin-modern-table">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Client</th>
                  <th>Album</th>
                  <th>Size</th>
                </tr>
              </thead>
              <tbody>
                {data.largest_files.length === 0 && (
                  <tr>
                    <td colSpan={4} className="admin-table-empty">
                      No files uploaded yet.
                    </td>
                  </tr>
                )}
                {data.largest_files.map((f) => (
                  <tr key={f.media_id}>
                    <td>{f.file_name}</td>
                    <td>{f.client_name}</td>
                    <td>{f.album_name}</td>
                    <td>{formatBytes(f.file_size)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* --- Orphan files --- */}
          <div
            className={
              data.orphan_candidate_count > 0
                ? "storage-orphan-banner"
                : "storage-orphan-banner storage-orphan-banner--clear"
            }
          >
            {data.orphan_candidate_count > 0 ? (
              <span>
                {data.orphan_candidate_count} orphaned file{data.orphan_candidate_count === 1 ? "" : "s"} found —
                uploaded to storage but never finished saving. Review from the Uploads page before cleaning up.
              </span>
            ) : (
              <span>No orphaned files detected.</span>
            )}
          </div>
        </>
      )}
    </AdminLayout>
  );
}
