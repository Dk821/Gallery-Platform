import { useEffect, useState } from "react";
import AdminLayout from "../components/AdminLayout";
import { ActivityItem, ActivityType, adminService } from "../services/admin";
import { formatBytes } from "../utils/format";

const TYPE_FILTERS: { value: ActivityType | "all"; label: string }[] = [
  { value: "all", label: "All activities" },
  { value: "upload", label: "Uploads" },
  { value: "download", label: "Downloads" },
  { value: "client", label: "Client created" },
  { value: "album", label: "Album added" },
];

const TYPE_LABELS: Record<ActivityType, string> = {
  upload: "Upload",
  download: "Download",
  client: "Client created",
  album: "Album added",
};

export default function Activity() {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<ActivityType | "all">("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const hasActiveFilters =
    search.trim() !== "" || typeFilter !== "all" || dateFrom !== "" || dateTo !== "";

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      setLoading(true);
      setError(null);
      adminService
        .getActivity({
          search: search.trim() || undefined,
          type: typeFilter,
          from: dateFrom || undefined,
          to: dateTo || undefined,
          limit: 500,
        })
        .then((data) => {
          if (cancelled) return;
          setItems(data.items);
          setTotal(data.total);
        })
        .catch((err) => {
          if (cancelled) return;
          setError(err instanceof Error ? err.message : "Failed to load activity.");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, search.trim() ? 350 : 0);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [search, typeFilter, dateFrom, dateTo]);

  function clearFilters() {
    setSearch("");
    setTypeFilter("all");
    setDateFrom("");
    setDateTo("");
  }

  function renderDetails(item: ActivityItem): string {
    const meta = item.meta;
    if (item.type === "download" && meta.file_count != null) {
      const size = meta.total_bytes != null ? ` · ${formatBytes(meta.total_bytes)}` : "";
      return `${meta.file_count} ${meta.file_count === 1 ? "file" : "files"}${size}`;
    }
    if (item.type === "upload") {
      return meta.total_bytes != null ? formatBytes(meta.total_bytes) : "—";
    }
    if (item.type === "client") return "Gallery portal initialized";
    return meta.client_name ?? "—";
  }

  function renderDate(iso: string): string {
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
      <h1 className="admin-page-title">Activity</h1>
      <p className="admin-page-subtitle">
        Uploads, downloads, and created clients &amp; albums across the studio.
      </p>

      <div className="activity-toolbar">
        <div className="clients-search">
          <span className="search-icon">⌕</span>
          <input
            className="search-input"
            type="text"
            placeholder="Search activity…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <select
          className="sort-select"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as ActivityType | "all")}
        >
          {TYPE_FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>

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
          {loading ? "…" : `${items.length} of ${total}`}
        </span>
      </div>

      {error && <p className="auth-error">{error}</p>}

      {!loading && items.length === 0 && (
        <div className="empty-state">
          {hasActiveFilters
            ? "No activity matches the current filters."
            : "No activity recorded yet."}
        </div>
      )}

      {items.length > 0 && (
        <div className="admin-table-responsive">
          <table className="admin-modern-table activity-table">
            <thead>
              <tr>
                <th style={{ width: 160 }}>TYPE</th>
                <th>ACTIVITY</th>
                <th style={{ width: 200 }}>CLIENT / ACTOR</th>
                <th style={{ width: 190 }}>DETAILS</th>
                <th style={{ width: 190 }}>DATE &amp; TIME</th>
              </tr>
            </thead>
            <tbody>
              {loading
                ? null
                : items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <span className="activity-type-cell">
                          <span className={`admin-act-icon admin-act-icon--${item.type}`}>
                            <ActivityIcon type={item.type} />
                          </span>
                          <span className="activity-type-label">{TYPE_LABELS[item.type]}</span>
                        </span>
                      </td>
                      <td>
                        <span className="admin-cell-action">{item.title}</span>
                        <span className="admin-cell-details activity-description">
                          {item.description}
                        </span>
                      </td>
                      <td>
                        <span className="admin-cell-admin">{item.meta.client_name ?? item.actor}</span>
                      </td>
                      <td>
                        <span className="admin-cell-details">{renderDetails(item)}</span>
                      </td>
                      <td>
                        <span className="admin-cell-date">{renderDate(item.occurred_at)}</span>
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

function ActivityIcon({ type }: { type: ActivityType }) {
  if (type === "upload") {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M12 12v9M8 16l4-4 4 4" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (type === "download") {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path d="M12 4v12m0 0l-4-4m4 4l4-4" strokeWidth="2" strokeLinecap="round" />
        <path d="M4 20h16" strokeWidth="2" strokeLinecap="round" />
      </svg>
    );
  }
  if (type === "client") {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path d="M12 5v14m-7-7h14" strokeWidth="2" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
      <rect x="3" y="3" width="18" height="18" rx="2" strokeWidth="2" />
      <circle cx="8" cy="8" r="1.5" fill="currentColor" />
      <path d="M21 15l-5-5L5 21" strokeWidth="2" />
    </svg>
  );
}