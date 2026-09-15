import { useEffect, useMemo, useState } from "react";
import AdminLayout from "../components/AdminLayout";
import { adminService, DownloadAnalytics, StorageOverview } from "../services/admin";
import { formatBytes } from "../utils/format";

type DownloadTypeFilter = "all" | "all-album" | "selected";

const TYPE_FILTERS: { value: DownloadTypeFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "all-album", label: "Full album" },
  { value: "selected", label: "Selected files" },
];

export default function Downloads() {
  const [analytics, setAnalytics] = useState<DownloadAnalytics | null>(null);
  const [storage, setStorage] = useState<StorageOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<DownloadTypeFilter>("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  useEffect(() => {
    let mounted = true;
    Promise.allSettled([
      adminService.getDownloadAnalytics(),
      adminService.getStorageOverview(),
    ])
      .then(([analyticsRes, storageRes]) => {
        if (!mounted) return;
        if (analyticsRes.status === "fulfilled") {
          setAnalytics(analyticsRes.value);
        } else {
          setError(analyticsRes.reason?.message ?? "Failed to load download data.");
        }
        if (storageRes.status === "fulfilled") {
          setStorage(storageRes.value);
        }
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const filtered = useMemo(() => {
    const history = analytics?.history ?? [];
    const q = search.toLowerCase().trim();
    return history.filter((d) => {
      if (q) {
        const haystack = `${d.client_name} ${d.album_name}`.toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      if (typeFilter !== "all") {
        const isFull = d.download_type === "all";
        if (typeFilter === "all-album" && !isFull) return false;
        if (typeFilter === "selected" && isFull) return false;
      }
      if (dateFrom) {
        const from = new Date(dateFrom + "T00:00:00");
        if (new Date(d.downloaded_at) < from) return false;
      }
      if (dateTo) {
        const to = new Date(dateTo + "T23:59:59");
        if (new Date(d.downloaded_at) > to) return false;
      }
      return true;
    });
  }, [analytics, search, typeFilter, dateFrom, dateTo]);

  const hasActiveFilters =
    search.trim() !== "" || typeFilter !== "all" || dateFrom !== "" || dateTo !== "";

  function clearFilters() {
    setSearch("");
    setTypeFilter("all");
    setDateFrom("");
    setDateTo("");
  }

  function renderDriveCards() {
    if (!storage) return null;
    const meta = storage.our_metadata;
    const quota =
      storage.drive_quota.available === true ? storage.drive_quota : null;

    const usageBytes = quota ? quota.usage_bytes : meta.total_bytes_tracked;
    const limitBytes = quota?.limit_bytes ?? null;
    const freeBytes = limitBytes != null ? Math.max(limitBytes - usageBytes, 0) : null;

    return (
      <div className="stat-strip downloads-stats">
        <div className="stat-strip__item">
          <div className="stat-strip__value">{analytics?.summary.total_downloads ?? 0}</div>
          <div className="stat-strip__label">Downloads</div>
          <div className="stat-strip__meta">
            {analytics?.summary.recent_24h ?? 0} in last 24h ·{" "}
            {formatBytes(analytics?.summary.total_transferred_bytes ?? 0)} transferred
          </div>
        </div>
        <div className="stat-strip__item">
          <div className="stat-strip__value">{meta.total_files}</div>
          <div className="stat-strip__label">Files uploaded</div>
          <div className="stat-strip__meta">
            {meta.total_photos} photos · {meta.total_videos} videos ·{" "}
            {formatBytes(meta.total_bytes_tracked)} tracked
          </div>
        </div>
        <div className="stat-strip__item">
          <div className="stat-strip__value">{formatBytes(usageBytes)}</div>
          <div className="stat-strip__label">Drive used</div>
          <div className="stat-strip__meta">
            {quota ? "on Google Drive" : "tracked in our records"}
          </div>
        </div>
        <div className="stat-strip__item">
          <div className="stat-strip__value">{freeBytes != null ? formatBytes(freeBytes) : "Unlimited"}</div>
          <div className="stat-strip__label">Drive available</div>
          <div className="stat-strip__meta">
            {limitBytes != null
              ? `${formatBytes(usageBytes)} of ${formatBytes(limitBytes)}`
              : "no fixed plan limit"}
          </div>
        </div>
      </div>
    );
  }

  function formatDate(iso: string): string {
    return new Date(iso).toLocaleString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  return (
    <AdminLayout>
      <h1 className="admin-page-title">Downloads</h1>
      <p className="admin-page-subtitle">
        Download activity, upload volume, and Google Drive storage usage.
      </p>

      {error && <p className="auth-error">{error}</p>}
      {!loading && renderDriveCards()}

      <div className="section-header">
        <h2>Recent downloads</h2>
      </div>

      <div className="activity-toolbar downloads-toolbar">
        <div className="clients-search">
          <span className="search-icon">⌕</span>
          <input
            className="search-input"
            type="text"
            placeholder="Search by client or album…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="filter-group">
          {TYPE_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              className={"filter-btn" + (typeFilter === f.value ? " filter-btn--active" : "")}
              onClick={() => setTypeFilter(f.value)}
            >
              {f.label}
            </button>
          ))}
        </div>

        <label className="activity-date-field">
          <span>From</span>
          <input
            type="date"
            value={dateFrom}
            max={dateTo || undefined}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </label>

        <label className="activity-date-field">
          <span>To</span>
          <input
            type="date"
            value={dateTo}
            min={dateFrom || undefined}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </label>

        {hasActiveFilters && (
          <button className="clear-filters-btn" onClick={clearFilters}>
            Clear filters
          </button>
        )}
        <span className="filter-count">
          {loading ? "…" : `${filtered.length} of ${analytics?.history.length ?? 0}`}
        </span>
      </div>

      {!loading && filtered.length === 0 && (
        <div className="empty-state">
          {hasActiveFilters ? "No downloads match the current filters." : "No downloads recorded yet."}
        </div>
      )}

      {filtered.length > 0 && (
        <div className="admin-table-responsive">
          <table className="admin-modern-table downloads-table">
            <thead>
              <tr>
                <th style={{ width: 190 }}>DATE &amp; TIME</th>
                <th>CLIENT</th>
                <th>ALBUM</th>
                <th style={{ width: 130 }}>TYPE</th>
                <th style={{ width: 90 }}>FILES</th>
                <th style={{ width: 120 }}>SIZE</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((d, i) => (
                <tr key={`${d.downloaded_at}-${i}`}>
                  <td>
                    <span className="admin-cell-date">{formatDate(d.downloaded_at)}</span>
                  </td>
                  <td>
                    <span className="admin-cell-admin">{d.client_name}</span>
                  </td>
                  <td>
                    <span className="admin-cell-action">{d.album_name}</span>
                  </td>
                  <td>
                    <span className={"download-type-pill download-type-pill--" + d.download_type}>
                      {d.download_type === "all" ? "Full album" : "Selected files"}
                    </span>
                  </td>
                  <td>
                    <span className="admin-cell-details">{d.file_count}</span>
                  </td>
                  <td>
                    <span className="admin-cell-details">{formatBytes(d.total_bytes)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </AdminLayout>
  );
}