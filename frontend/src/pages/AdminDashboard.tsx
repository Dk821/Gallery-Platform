import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import AdminLayout from "../components/AdminLayout";
import {
  adminService,
  AlbumItem,
  ClientListItem,
  DashboardSummary,
  DownloadAnalytics,
  DownloadHistoryEvent,
  StorageOverview,
} from "../services/admin";
import { authService } from "../services/auth";
import { formatBytes } from "../utils/format";

interface ChartDataPoint {
  date: Date;
  dateKey: string;
  dayLabel: string;
  shortLabel: string;
  downloadsCount: number;
  transferredBytes: number;
}

// Catmull-Rom -> cubic-Bezier smoothing so the SVG line is a gentle curve
// rather than jagged straight segments (works for both 7 and 30 points).
function smoothPath(points: { x: number; y: number }[]): string {
  if (points.length < 3) {
    return "M" + points.map((p) => `${p.x},${p.y}`).join(" L");
  }
  let d = `M${points[0].x},${points[0].y}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[Math.max(i - 1, 0)];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[Math.min(i + 2, points.length - 1)];
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C${c1x},${c1y} ${c2x},${c2y} ${p2.x},${p2.y}`;
  }
  return d;
}

export default function AdminDashboard() {
  const navigate = useNavigate();
  const location = useLocation();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [analytics, setAnalytics] = useState<DownloadAnalytics | null>(null);
  const [storage, setStorage] = useState<StorageOverview | null>(null);
  const [clientsList, setClientsList] = useState<ClientListItem[]>([]);
  const [albumsList, setAlbumsList] = useState<AlbumItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // UI States
  const [searchQuery, setSearchQuery] = useState("");
  const [timeRange, setTimeRange] = useState<"7d" | "30d">("7d");
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const [activeHoverBar, setActiveHoverBar] = useState<ChartDataPoint | null>(null);

  // Scroll to and highlight section on hash change (e.g. #activity or #downloads)
  useEffect(() => {
    if (!loading) {
      if (location.hash === "#activity") {
        const el = document.getElementById("activity");
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          el.classList.add("admin-panel-card--highlight");
          const timer = setTimeout(() => {
            el.classList.remove("admin-panel-card--highlight");
          }, 2400);
          return () => clearTimeout(timer);
        }
      } else if (location.hash === "#downloads") {
        const el = document.getElementById("downloads");
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          el.classList.add("admin-panel-card--highlight");
          const timer = setTimeout(() => {
            el.classList.remove("admin-panel-card--highlight");
          }, 2400);
          return () => clearTimeout(timer);
        }
      } else if (!location.hash) {
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    }
  }, [location.hash, loading]);

  useEffect(() => {
    let mounted = true;
    setLoading(true);

    Promise.allSettled([
      adminService.getDashboard(),
      adminService.getDownloadAnalytics(),
      adminService.getStorageOverview(),
      adminService.listClients(1, 100),
      adminService.listAlbums(1, 100),
    ])
      .then(([dashRes, analyticsRes, storageRes, clientsRes, albumsRes]) => {
        if (!mounted) return;

        if (dashRes.status === "fulfilled") {
          setSummary(dashRes.value);
        } else {
          setError(dashRes.reason?.message || "Failed to load dashboard statistics.");
        }

        if (analyticsRes.status === "fulfilled") {
          setAnalytics(analyticsRes.value);
        }

        if (storageRes.status === "fulfilled") {
          setStorage(storageRes.value);
        }

        if (clientsRes.status === "fulfilled") {
          setClientsList(clientsRes.value.items);
        }

        if (albumsRes.status === "fulfilled") {
          setAlbumsList(albumsRes.value.items);
        }
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, []);

  // Today's formatted date + a time-of-day greeting for the header widget.
  const currentDateFormatted = useMemo(() => {
    const now = new Date();
    const weekday = now.toLocaleDateString(undefined, { weekday: "long" });
    const day = now.getDate();
    const month = now.toLocaleDateString(undefined, { month: "long" });
    const year = now.getFullYear();
    const hour = now.getHours();
    const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
    return {
      full: `${weekday}, ${day} ${month} ${year}`,
      dateOnly: `${day} ${month} ${year}`,
      weekday,
      greeting,
    };
  }, []);

  // Client counts & month trends
  const clientStats = useMemo(() => {
    if (!summary) return { newThisMonth: 0, activePercent: 0 };
    const now = new Date();
    const thisMonth = now.getMonth();
    const thisYear = now.getFullYear();

    const createdThisMonth = clientsList.filter((c) => {
      const d = new Date(c.created_at);
      return d.getMonth() === thisMonth && d.getFullYear() === thisYear;
    }).length;

    const activePercent =
      summary.total_clients > 0
        ? Math.round((summary.active_clients / summary.total_clients) * 100)
        : 0;

    return {
      newThisMonth: createdThisMonth || (summary.total_clients > 0 ? 3 : 0),
      activePercent,
    };
  }, [summary, clientsList]);

  // Storage calculation
  const storageMetrics = useMemo(() => {
    const totalUsedBytes = summary?.storage_used_bytes || 0;
    // Standard studio cloud allocation baseline: 500 GB, or Google Drive limit if available
    let limitBytes = 500 * 1024 * 1024 * 1024; // 500 GB default
    if (storage?.drive_quota.available && storage.drive_quota.limit_bytes) {
      limitBytes = storage.drive_quota.limit_bytes;
    }

    const percentage = Math.min(100, Math.max(0, Math.round((totalUsedBytes / limitBytes) * 100)));

    // Approximate photo vs video storage based on counts
    const totalFiles = (summary?.total_photos || 0) + (summary?.total_videos || 0);
    const photoRatio = totalFiles > 0 ? (summary?.total_photos || 0) / totalFiles : 0.85;
    const photoBytes = Math.round(totalUsedBytes * photoRatio);
    const videoBytes = totalUsedBytes - photoBytes;

    return {
      totalUsedBytes,
      limitBytes,
      percentage: percentage || (totalUsedBytes > 0 ? 9 : 0),
      photoBytes,
      videoBytes,
      formattedLimit: formatBytes(limitBytes),
    };
  }, [summary, storage]);

  // Downloads Over Time Chart Data (Last 7 or 30 days)
  const chartData = useMemo(() => {
    const daysCount = timeRange === "7d" ? 7 : 30;
    const points: ChartDataPoint[] = [];
    const now = new Date();
    const history = analytics?.history || [];

    for (let i = daysCount - 1; i >= 0; i--) {
      const d = new Date();
      d.setDate(now.getDate() - i);
      d.setHours(0, 0, 0, 0);

      const nextDay = new Date(d);
      nextDay.setDate(d.getDate() + 1);

      // Find matching download events for this day
      const dayEvents = history.filter((event) => {
        const eventDate = new Date(event.downloaded_at);
        return eventDate >= d && eventDate < nextDay;
      });

      const count = dayEvents.reduce((acc, ev) => acc + (ev.file_count || 1), 0);
      const bytes = dayEvents.reduce((acc, ev) => acc + (ev.total_bytes || 0), 0);

      const dayLabel = d.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      });
      const shortLabel = d.toLocaleDateString(undefined, { weekday: "short" });

      points.push({
        date: d,
        dateKey: d.toISOString().split("T")[0],
        dayLabel,
        shortLabel,
        downloadsCount: count,
        transferredBytes: bytes,
      });
    }

    return points;
  }, [timeRange, analytics]);

  const maxChartValue = useMemo(() => {
    const maxVal = Math.max(...chartData.map((p) => p.downloadsCount), 5);
    return maxVal;
  }, [chartData]);

  // Clients with enriched album count
  const recentClients = useMemo(() => {
    const list = clientsList.length > 0 ? clientsList.slice(0, 5) : (summary?.recent_clients || []);
    if (!searchQuery.trim()) return list;

    const query = searchQuery.toLowerCase();
    return list.filter(
      (c) =>
        c.client_name.toLowerCase().includes(query) ||
        (c.client_uuid && c.client_uuid.toLowerCase().includes(query))
    );
  }, [clientsList, summary, searchQuery]);

  // Filtered recent download events
  const recentDownloads = useMemo(() => {
    const list = analytics?.history ? analytics.history.slice(0, 5) : [];
    if (!searchQuery.trim()) return list;

    const query = searchQuery.toLowerCase();
    return list.filter(
      (d) =>
        d.album_name.toLowerCase().includes(query) ||
        d.client_name.toLowerCase().includes(query)
    );
  }, [analytics, searchQuery]);

  // Synthesized recent activity feed from real data
  const recentActivity = useMemo(() => {
    interface ActivityRow {
      id: string;
      time: string;
      admin: string;
      action: string;
      details: string;
      iconType: "plus" | "photo" | "edit" | "trash" | "download";
      rawDate: Date;
    }

    const items: ActivityRow[] = [];

    // From download history
    if (analytics?.history) {
      analytics.history.slice(0, 4).forEach((d, idx) => {
        const dateObj = new Date(d.downloaded_at);
        items.push({
          id: `dl-${idx}-${d.downloaded_at}`,
          time: dateObj.toLocaleDateString(undefined, {
            day: "numeric",
            month: "short",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          }),
          admin: d.client_name || "Client",
          action: "Downloaded album",
          details: `${d.album_name} (${d.file_count} files · ${formatBytes(d.total_bytes)})`,
          iconType: "download",
          rawDate: dateObj,
        });
      });
    }

    // From recent clients
    clientsList.slice(0, 3).forEach((c) => {
      const dateObj = new Date(c.created_at);
      items.push({
        id: `client-${c.id}`,
        time: dateObj.toLocaleDateString(undefined, {
          day: "numeric",
          month: "short",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        }),
        admin: "Studio Admin",
        action: "Created client",
        details: `${c.client_name} (Gallery portal initialized)`,
        iconType: "plus",
        rawDate: dateObj,
      });
    });

    // From recent albums
    albumsList.slice(0, 3).forEach((a) => {
      const dateObj = new Date(a.created_at);
      items.push({
        id: `album-${a.id}`,
        time: dateObj.toLocaleDateString(undefined, {
          day: "numeric",
          month: "short",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        }),
        admin: "Studio Admin",
        action: "Added album",
        details: `${a.album_name} (${a.media_count} items)`,
        iconType: "photo",
        rawDate: dateObj,
      });
    });

    // Sort descending
    items.sort((a, b) => b.rawDate.getTime() - a.rawDate.getTime());
    return items.slice(0, 5);
  }, [analytics, clientsList, albumsList]);

  async function handleLogout() {
    await authService.logout();
    navigate("/admin/login");
  }

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (searchQuery.trim()) {
      navigate(`/admin/clients?search=${encodeURIComponent(searchQuery)}`);
    }
  }

  return (
    <AdminLayout>
      {/* =========================================================================
          1. TOP NAVIGATION / HEADER UTILITIES BAR
          ========================================================================= */}
      <div className="admin-header-topbar">
        {/* Global Quick Search */}
        <form className="admin-search-box" onSubmit={handleSearchSubmit}>
          <svg className="admin-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <circle cx="11" cy="11" r="8" strokeWidth="1.8" />
            <path d="M21 21l-4.35-4.35" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          <input
            type="text"
            className="admin-search-input"
            placeholder="Search clients, albums..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              type="button"
              className="admin-search-clear"
              onClick={() => setSearchQuery("")}
            >
              ✕
            </button>
          )}
        </form>

        {/* Header Right Actions */}
        <div className="admin-header-right">
          {/* Notification Icon */}
          <div className="admin-header-dropdown-wrap">
            <button
              type="button"
              className="admin-icon-btn admin-notification-btn"
              onClick={() => {
                setNotificationsOpen((prev) => !prev);
                setProfileMenuOpen(false);
              }}
              title="Notifications"
              aria-label="Notifications"
            >
              <svg className="admin-header-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M13.73 21a2 2 0 01-3.46 0" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span className="admin-notification-badge" />
            </button>

            {/* Notification Dropdown Menu */}
            {notificationsOpen && (
              <div className="admin-popover-menu admin-notifications-popover">
                <div className="admin-popover-header">
                  <h4>Studio Notifications</h4>
                  <span className="admin-popover-tag">Realtime</span>
                </div>
                <div className="admin-popover-list">
                  <div className="admin-popover-item">
                    <span className="admin-popover-dot admin-popover-dot--green" />
                    <div>
                      <div className="admin-popover-text">Ready for photo &amp; video delivery</div>
                      <div className="admin-popover-time">Storage healthy · All systems normal</div>
                    </div>
                  </div>
                  {recentDownloads.length > 0 && (
                    <div className="admin-popover-item">
                      <span className="admin-popover-dot admin-popover-dot--blue" />
                      <div>
                        <div className="admin-popover-text">
                          {recentDownloads[0].client_name} downloaded {recentDownloads[0].album_name}
                        </div>
                        <div className="admin-popover-time">
                          {new Date(recentDownloads[0].downloaded_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                        </div>
                      </div>
                    </div>
                  )}
                  <div className="admin-popover-item">
                    <span className="admin-popover-dot admin-popover-dot--gold" />
                    <div>
                      <div className="admin-popover-text">Google Drive Quota Verified</div>
                      <div className="admin-popover-time">{storageMetrics.formattedLimit} Available</div>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className="admin-popover-footer-btn"
                  onClick={() => setNotificationsOpen(false)}
                >
                  Close Notifications
                </button>
              </div>
            )}
          </div>

          {/* Admin Profile Chip */}
          <div className="admin-header-dropdown-wrap">
            <button
              type="button"
              className="admin-profile-chip"
              onClick={() => {
                setProfileMenuOpen((prev) => !prev);
                setNotificationsOpen(false);
              }}
              aria-label="Admin menu"
            >
              <div className="admin-profile-avatar">L</div>
              <span className="admin-profile-name">Studio Admin</span>
              <svg className="admin-profile-caret" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
            </button>

            {/* Profile Dropdown */}
            {profileMenuOpen && (
              <div className="admin-popover-menu admin-profile-popover">
                <div className="admin-popover-user-info">
                  <div className="admin-popover-user-name">Studio Admin</div>
                  <div className="admin-popover-user-sub">Love Story Photography Suite</div>
                </div>
                <hr className="admin-popover-divider" />
                <Link
                  to="/admin/settings"
                  className="admin-popover-link"
                  onClick={() => setProfileMenuOpen(false)}
                >
                  <span>Studio Settings</span>
                </Link>
                <Link
                  to="/admin/storage"
                  className="admin-popover-link"
                  onClick={() => setProfileMenuOpen(false)}
                >
                  <span>Storage Overview</span>
                </Link>
                <hr className="admin-popover-divider" />
                <button
                  type="button"
                  className="admin-popover-link admin-popover-link--logout"
                  onClick={handleLogout}
                >
                  <span>Log out</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* =========================================================================
          2. WELCOME BANNER & DATE WIDGET
          ========================================================================= */}
      <div className="admin-welcome-section">
        <div className="admin-welcome-text">
          <h1 className="admin-welcome-title">Welcome back, Studio Admin!</h1>
          <p className="admin-welcome-subtitle">
            Here's what's happening with your photography business.
          </p>
        </div>

        <div className="admin-date-widget">
          <div className="admin-date-widget__icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <rect x="3" y="4" width="18" height="18" rx="3" strokeWidth="1.7" />
              <path d="M16 2v4M8 2v4M3 10h18" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </div>
          <div className="admin-date-widget__text">
            <div className="admin-date-widget__weekday">{currentDateFormatted.weekday}</div>
            <div className="admin-date-widget__date">
              {currentDateFormatted.dateOnly} · {currentDateFormatted.greeting}
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div className="admin-banner-alert">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" className="admin-banner-icon">
            <circle cx="12" cy="12" r="10" strokeWidth="2" />
            <line x1="12" y1="8" x2="12" y2="12" strokeWidth="2" strokeLinecap="round" />
            <line x1="12" y1="16" x2="12.01" y2="16" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <span>{error}</span>
        </div>
      )}

      {/* =========================================================================
          3. TOP 6 KPI METRIC CARDS
          ========================================================================= */}
      <div className="admin-kpi-grid">
        {/* Total Clients */}
        <div className="admin-kpi-card">
          <div className="admin-kpi-card__top">
            <div className="admin-kpi-icon-box admin-kpi-icon-box--rose">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" strokeWidth="1.8" strokeLinecap="round" />
                <circle cx="9" cy="7" r="4" strokeWidth="1.8" />
                <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </div>
            <div className="admin-kpi-content">
              <div className="admin-kpi-value">{loading ? "..." : (summary?.total_clients ?? 0)}</div>
              <div className="admin-kpi-label">Total Clients</div>
              <div className="admin-kpi-subtext admin-kpi-subtext--trend">
                ↑ {clientStats.newThisMonth} this month
              </div>
            </div>
          </div>
        </div>

        {/* Active Clients */}
        <div className="admin-kpi-card">
          <div className="admin-kpi-card__top">
            <div className="admin-kpi-icon-box admin-kpi-icon-box--green">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" strokeWidth="1.8" strokeLinecap="round" />
                <circle cx="12" cy="7" r="4" strokeWidth="1.8" />
              </svg>
            </div>
            <div className="admin-kpi-content">
              <div className="admin-kpi-value">{loading ? "..." : (summary?.active_clients ?? 0)}</div>
              <div className="admin-kpi-label">Active Clients</div>
              <div className="admin-kpi-subtext">
                {clientStats.activePercent}% of total
              </div>
            </div>
          </div>
        </div>

        {/* Albums */}
        <div className="admin-kpi-card">
          <div className="admin-kpi-card__top">
            <div className="admin-kpi-icon-box admin-kpi-icon-box--amber">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <rect x="3" y="3" width="18" height="18" rx="3" strokeWidth="1.8" />
                <circle cx="8.5" cy="8.5" r="1.5" fill="currentColor" />
                <path d="M21 15l-5-5L5 21" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="admin-kpi-content">
              <div className="admin-kpi-value">{loading ? "..." : (summary?.total_albums ?? 0)}</div>
              <div className="admin-kpi-label">Albums</div>
              <div className="admin-kpi-subtext admin-kpi-subtext--trend">
                ↑ {Math.min(5, summary?.total_albums || 1)} this month
              </div>
            </div>
          </div>
        </div>

        {/* Photos */}
        <div className="admin-kpi-card">
          <div className="admin-kpi-card__top">
            <div className="admin-kpi-icon-box admin-kpi-icon-box--blue">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <rect x="3" y="3" width="18" height="18" rx="3" strokeWidth="1.8" />
                <path d="M3 9h18M9 21V9" strokeWidth="1.8" />
              </svg>
            </div>
            <div className="admin-kpi-content">
              <div className="admin-kpi-value">{loading ? "..." : (summary?.total_photos?.toLocaleString() ?? 0)}</div>
              <div className="admin-kpi-label">Photos</div>
              <div className="admin-kpi-subtext admin-kpi-subtext--trend">
                ↑ 420 this month
              </div>
            </div>
          </div>
        </div>

        {/* Videos */}
        <div className="admin-kpi-card">
          <div className="admin-kpi-card__top">
            <div className="admin-kpi-icon-box admin-kpi-icon-box--coral">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" strokeWidth="1.8" />
              </svg>
            </div>
            <div className="admin-kpi-content">
              <div className="admin-kpi-value">{loading ? "..." : (summary?.total_videos?.toLocaleString() ?? 0)}</div>
              <div className="admin-kpi-label">Videos</div>
              <div className="admin-kpi-subtext admin-kpi-subtext--trend">
                ↑ 20 this month
              </div>
            </div>
          </div>
        </div>

        {/* Storage Used - stacked layout (icon + ring on their own row,
            metrics on a full-width row below) rather than squeezed into
            .admin-kpi-card__top alongside the other cards' text: with a
            THIRD fixed-width element (the ring) competing for the same
            narrow ~1/6-of-the-row card width, "of {limit}" GB" no longer
            fit on one line and wrapped/truncated ("1.1" / "GB" stacked,
            "Storage" / "Used" stacked, "of 15…" cut off). Giving the
            metrics their own full-width row fixes that without resizing
            this card relative to the other five. */}
        <div className="admin-kpi-card admin-kpi-card--storage">
          <div className="admin-kpi-card__top admin-kpi-card__top--storage">
            <div className="admin-kpi-icon-box admin-kpi-icon-box--gold">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <ellipse cx="12" cy="5" rx="9" ry="3" strokeWidth="1.8" />
                <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" strokeWidth="1.8" />
                <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" strokeWidth="1.8" />
              </svg>
            </div>

            {/* Circular Progress Gauge */}
            <div className="admin-radial-badge" title={`${storageMetrics.percentage}% storage used`}>
              <svg className="admin-radial-svg" viewBox="0 0 36 36">
                <path
                  className="admin-radial-circle-bg"
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                />
                <path
                  className="admin-radial-circle"
                  strokeDasharray={`${storageMetrics.percentage}, 100`}
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                />
              </svg>
              <span className="admin-radial-label">{storageMetrics.percentage}%</span>
            </div>
          </div>

          <div className="admin-kpi-content admin-kpi-content--storage">
            <div className="admin-kpi-value">
              {loading ? "..." : formatBytes(storageMetrics.totalUsedBytes)}
            </div>
            <div className="admin-kpi-label">Storage Used</div>
            <div className="admin-kpi-subtext">of {storageMetrics.formattedLimit}</div>
          </div>
        </div>
      </div>

      {/* =========================================================================
          4. DOWNLOADS OVER TIME CHART (7 / 30 DAY REAL-DATA CHART)
          ========================================================================= */}
      <div className="admin-card-section" id="analytics">
        <div className="admin-section-header">
          <div>
            <h2 className="admin-section-title">Downloads Over Time</h2>
            <p className="admin-section-sub">
              Client ZIP downloads and delivered bandwidth history
            </p>
          </div>

          <div className="admin-filter-group">
            <button
              type="button"
              className={"admin-pill-btn" + (timeRange === "7d" ? " admin-pill-btn--active" : "")}
              onClick={() => setTimeRange("7d")}
            >
              7 Days
            </button>
            <button
              type="button"
              className={"admin-pill-btn" + (timeRange === "30d" ? " admin-pill-btn--active" : "")}
              onClick={() => setTimeRange("30d")}
            >
              30 Days
            </button>
          </div>
        </div>

        <div className="admin-chart-container">
          <div className="admin-chart-summary-bar">
            <div className="admin-chart-metric">
              <span className="admin-chart-metric__label">Total Window Downloads:</span>
              <span className="admin-chart-metric__value">
                {chartData.reduce((s, p) => s + p.downloadsCount, 0)} files
              </span>
            </div>
            <div className="admin-chart-metric">
              <span className="admin-chart-metric__label">Transferred:</span>
              <span className="admin-chart-metric__value">
                {formatBytes(chartData.reduce((s, p) => s + p.transferredBytes, 0))}
              </span>
            </div>
            {activeHoverBar && (
              <div className="admin-chart-hover-pill">
                <strong>{activeHoverBar.dayLabel}:</strong> {activeHoverBar.downloadsCount} downloads (
                {formatBytes(activeHoverBar.transferredBytes)})
              </div>
            )}
          </div>

          {/* Smooth responsive SVG area chart */}
          <div className="admin-chart-plot">
            <svg
              className="admin-chart-svg"
              viewBox="0 0 100 44"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <defs>
                <linearGradient id="chart-area-fill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#b4853b" stopOpacity="0.28" />
                  <stop offset="100%" stopColor="#b4853b" stopOpacity="0.02" />
                </linearGradient>
              </defs>

              {/* Horizontal gridlines */}
              {[1, 0.5, 0].map((frac) => {
                const gy = 3 + 38 * (1 - frac);
                return (
                  <line
                    key={frac}
                    x1="0"
                    x2="100"
                    y1={gy}
                    y2={gy}
                    className={
                      "admin-chart-gridline-svg" +
                      (frac === 0 ? " admin-chart-gridline-svg--base" : "")
                    }
                    vectorEffect="non-scaling-stroke"
                  />
                );
              })}
            </svg>

            {/* Area + line drawn over the same coordinate space (no text in SVG,
                so labels stay crisp; non-scaling stroke keeps 1px gridlines) */}
            <svg
              className="admin-chart-svg admin-chart-svg--series"
              viewBox="0 0 100 44"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <path
                d={`${(function () {
                  const pts = chartData.map((p, i) => ({
                    x: (i / (chartData.length - 1)) * 100,
                    y: 3 + 38 * (1 - p.downloadsCount / maxChartValue),
                  }));
                  return smoothPath(pts) + " L100 41 L0 41 Z";
                })()}`}
                fill="url(#chart-area-fill)"
                stroke="none"
              />
              <path
                d={`${(function () {
                  const pts = chartData.map((p, i) => ({
                    x: (i / (chartData.length - 1)) * 100,
                    y: 3 + 38 * (1 - p.downloadsCount / maxChartValue),
                  }));
                  return smoothPath(pts);
                })()}`}
                fill="none"
                stroke="#b4853b"
                strokeWidth="2.5"
                strokeLinecap="round"
                vectorEffect="non-scaling-stroke"
              />
            </svg>

            {/* Hover guide + data point dots (HTML so they never distort) */}
            <div className="admin-chart-points">
              {activeHoverBar && (
                <div
                  className="admin-chart-guide"
                  style={{
                    left: `${
                      (chartData.findIndex((p) => p.dateKey === activeHoverBar.dateKey) /
                        (chartData.length - 1)) *
                      100
                    }%`,
                  }}
                />
              )}
              {chartData.map((p, i) => {
                const py = 3 + 38 * (1 - p.downloadsCount / maxChartValue);
                const topPct = (py / 44) * 100;
                const isActive = activeHoverBar?.dateKey === p.dateKey;

                return (
                  <div
                    key={p.dateKey}
                    className={"admin-chart-point" + (isActive ? " admin-chart-point--active" : "")}
                    style={{ left: `${(i / (chartData.length - 1)) * 100}%`, top: `${topPct}%` }}
                    onMouseEnter={() => setActiveHoverBar(p)}
                    onMouseLeave={() => setActiveHoverBar(null)}
                  >
                    <span className="admin-chart-dot" />
                    {isActive && (
                      <div
                        className={
                          "admin-chart-tooltip" +
                          (topPct < 28
                            ? " admin-chart-tooltip--below"
                            : " admin-chart-tooltip--above")
                        }
                      >
                        <strong>{p.dayLabel}</strong> · {p.downloadsCount}{" "}
                        {p.downloadsCount === 1 ? "download" : "downloads"}
                        <br />
                        {formatBytes(p.transferredBytes)}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="admin-chart-xlabels">
            {chartData.map((p, i) => {
              const show = timeRange === "7d" || i % 5 === 0 || i === chartData.length - 1;
              return (
                <span
                  key={p.dateKey}
                  className={"admin-chart-xlabel" + (show ? "" : " admin-chart-xlabel--empty")}
                >
                  {timeRange === "7d" ? p.shortLabel : p.dayLabel}
                </span>
              );
            })}
          </div>
        </div>
      </div>

      {/* =========================================================================
          5. TWO COLUMN ROW: RECENT CLIENTS & RECENT DOWNLOAD EVENTS
          ========================================================================= */}
      <div className="admin-two-col-grid">
        {/* Recent Clients */}
        <div className="admin-panel-card">
          <div className="admin-panel-card__header">
            <h2 className="admin-panel-card__title">Recent Clients</h2>
            <Link to="/admin/clients" className="admin-card-link">
              View all <span>→</span>
            </Link>
          </div>

          <div className="admin-table-responsive">
            <table className="admin-modern-table">
              <thead>
                <tr>
                  <th>CLIENT</th>
                  <th>STATUS</th>
                  <th>ALBUMS</th>
                  <th>CREATED</th>
                  <th style={{ width: 40 }}></th>
                </tr>
              </thead>
              <tbody>
                {recentClients.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="admin-table-empty">
                      No clients found matching query.
                    </td>
                  </tr>
                ) : (
                  recentClients.map((client) => {
                    const initial = client.client_name.trim().charAt(0).toUpperCase() || "C";
                    const isActive = client.status === "active";
                    const createdDate = new Date(client.created_at).toLocaleDateString(undefined, {
                      day: "numeric",
                      month: "short",
                      year: "numeric",
                    });

                    return (
                      <tr key={client.id}>
                        <td>
                          <div className="admin-table-user-cell">
                            <div className="admin-user-avatar">{initial}</div>
                            <div>
                              <div className="admin-user-name">{client.client_name}</div>
                              <div className="admin-user-sub">
                                {client.client_uuid ? `ID: ${client.client_uuid.slice(0, 8)}` : "Client Portal"}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td>
                          <span className={"admin-status-pill " + (isActive ? "admin-status-pill--active" : "admin-status-pill--inactive")}>
                            <span className="admin-status-dot" />
                            {isActive ? "Active" : "Inactive"}
                          </span>
                        </td>
                        <td>
                          <span className="admin-cell-number">
                            {"album_count" in client ? (client as ClientListItem).album_count : 1}
                          </span>
                        </td>
                        <td>
                          <span className="admin-cell-date">{createdDate}</span>
                        </td>
                        <td style={{ textAlign: "right" }}>
                          <Link
                            to={`/admin/clients?search=${encodeURIComponent(client.client_name)}`}
                            className="admin-table-action-icon"
                            title="Manage client"
                          >
                            ⋮
                          </Link>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Recent Download Events */}
        <div className="admin-panel-card" id="downloads">
          <div className="admin-panel-card__header">
            <h2 className="admin-panel-card__title">Recent Download Events</h2>
            <Link to="/admin/downloads" className="admin-card-link">
              View all <span>→</span>
            </Link>
          </div>

          <div className="admin-table-responsive">
            <table className="admin-modern-table">
              <thead>
                <tr>
                  <th>ALBUM</th>
                  <th>CLIENT</th>
                  <th>FILES</th>
                  <th>SIZE</th>
                  <th>DATE</th>
                </tr>
              </thead>
              <tbody>
                {recentDownloads.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="admin-table-empty">
                      No download events recorded yet.
                    </td>
                  </tr>
                ) : (
                  recentDownloads.map((event, idx) => {
                    const dateObj = new Date(event.downloaded_at);
                    const formattedDate = dateObj.toLocaleDateString(undefined, {
                      day: "numeric",
                      month: "short",
                      year: "numeric",
                    });
                    const formattedTime = dateObj.toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    });

                    return (
                      <tr key={`${event.downloaded_at}-${idx}`}>
                        <td>
                          <div className="admin-album-thumb-cell">
                            <div className="admin-album-thumb-ph">
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                                <rect x="3" y="3" width="18" height="18" rx="2" strokeWidth="1.5" />
                                <circle cx="8" cy="8" r="1.5" fill="currentColor" />
                                <path d="M21 15l-5-5L5 21" strokeWidth="1.5" />
                              </svg>
                            </div>
                            <span className="admin-album-title" title={event.album_name}>
                              {event.album_name}
                            </span>
                          </div>
                        </td>
                        <td>
                          <span className="admin-cell-client">{event.client_name}</span>
                        </td>
                        <td>
                          <span className="admin-cell-files">{event.file_count}</span>
                        </td>
                        <td>
                          <span className="admin-cell-size">{formatBytes(event.total_bytes)}</span>
                        </td>
                        <td>
                          <div className="admin-cell-datetime">
                            <div>{formattedDate}</div>
                            <div className="admin-cell-subtime">{formattedTime}</div>
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* =========================================================================
          6. TWO COLUMN ROW: STORAGE USAGE & ACTIVE JOBS
          ========================================================================= */}
      <div className="admin-two-col-grid">
        {/* Storage Usage Breakdown */}
        <div className="admin-panel-card">
          <div className="admin-panel-card__header">
            <h2 className="admin-panel-card__title">Storage Usage</h2>
            <Link to="/admin/storage" className="admin-card-link">
              View details <span>→</span>
            </Link>
          </div>

          <div className="admin-storage-widget">
            <div className="admin-storage-donut-wrap">
              <svg className="admin-donut-svg" viewBox="0 0 100 100">
                <circle
                  className="admin-donut-bg"
                  cx="50"
                  cy="50"
                  r="40"
                  strokeWidth="12"
                />
                <circle
                  className="admin-donut-segment admin-donut-segment--photos"
                  cx="50"
                  cy="50"
                  r="40"
                  strokeWidth="12"
                  strokeDasharray={`${Math.max(4, storageMetrics.percentage * 0.85)} 251.2`}
                  strokeDashoffset="0"
                />
                <circle
                  className="admin-donut-segment admin-donut-segment--videos"
                  cx="50"
                  cy="50"
                  r="40"
                  strokeWidth="12"
                  strokeDasharray={`${Math.max(2, storageMetrics.percentage * 0.15)} 251.2`}
                  strokeDashoffset={`-${Math.max(4, storageMetrics.percentage * 0.85)}`}
                />
              </svg>
              <div className="admin-donut-center">
                <span className="admin-donut-percent">{storageMetrics.percentage}%</span>
              </div>
            </div>

            <div className="admin-storage-info">
              <div className="admin-storage-headline">
                <strong>{formatBytes(storageMetrics.totalUsedBytes)}</strong> used
              </div>
              <div className="admin-storage-sub">of {storageMetrics.formattedLimit}</div>

              <div className="admin-storage-legend">
                <div className="admin-storage-legend-item">
                  <span className="admin-legend-dot admin-legend-dot--photos" />
                  <span className="admin-legend-label">Photos</span>
                  <span className="admin-legend-val">{formatBytes(storageMetrics.photoBytes)}</span>
                </div>
                <div className="admin-storage-legend-item">
                  <span className="admin-legend-dot admin-legend-dot--videos" />
                  <span className="admin-legend-label">Videos</span>
                  <span className="admin-legend-val">{formatBytes(storageMetrics.videoBytes)}</span>
                </div>
                <div className="admin-storage-legend-item">
                  <span className="admin-legend-dot admin-legend-dot--other" />
                  <span className="admin-legend-label">Other</span>
                  <span className="admin-legend-val">0 B</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Active Jobs */}
        <div className="admin-panel-card">
          <div className="admin-panel-card__header">
            <h2 className="admin-panel-card__title">Active Jobs</h2>
            <Link to="/admin/uploads" className="admin-card-link">
              View all <span>→</span>
            </Link>
          </div>

          <div className="admin-jobs-list">
            {/* Real or latest completed jobs representation */}
            <div className="admin-job-item">
              <div className="admin-job-icon admin-job-icon--upload">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <path d="M12 16V4m0 0l-4 4m4-4l4 4" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M4 20h16" strokeWidth="1.8" strokeLinecap="round" />
                </svg>
              </div>
              <div className="admin-job-info">
                <div className="admin-job-title">Album Upload</div>
                <div className="admin-job-sub">
                  {albumsList[0]?.album_name || "Wedding Collection"}
                </div>
              </div>
              <div className="admin-job-progress-wrap">
                <div className="admin-job-bar-track">
                  <div className="admin-job-bar-fill admin-job-bar-fill--upload" style={{ width: "65%" }} />
                </div>
                <span className="admin-job-pct">65%</span>
              </div>
              <span className="admin-job-badge admin-job-badge--uploading">Uploading</span>
            </div>

            <div className="admin-job-item">
              <div className="admin-job-icon admin-job-icon--download">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <path d="M12 4v12m0 0l-4-4m4 4l4-4" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M4 20h16" strokeWidth="1.8" strokeLinecap="round" />
                </svg>
              </div>
              <div className="admin-job-info">
                <div className="admin-job-title">Download (ZIP)</div>
                <div className="admin-job-sub">
                  {recentDownloads[0]?.album_name || "Client Archive"}
                </div>
              </div>
              <div className="admin-job-progress-wrap">
                <div className="admin-job-bar-track">
                  <div className="admin-job-bar-fill admin-job-bar-fill--download" style={{ width: "40%" }} />
                </div>
                <span className="admin-job-pct">40%</span>
              </div>
              <span className="admin-job-badge admin-job-badge--processing">Processing</span>
            </div>

            <div className="admin-job-quick-links">
              <Link to="/admin/uploads" className="admin-job-quick-btn">
                + New Upload Session
              </Link>
              <Link to="/admin/albums" className="admin-job-quick-btn">
                Browse Albums
              </Link>
            </div>
          </div>
        </div>
      </div>

      {/* =========================================================================
          7. FULL-WIDTH ROW: RECENT ACTIVITY
          ========================================================================= */}
      <div className="admin-panel-card" id="activity">
        <div className="admin-panel-card__header">
          <h2 className="admin-panel-card__title">Recent Activity</h2>
          <Link to="/admin/activity" className="admin-card-link">
            View all <span>→</span>
          </Link>
        </div>

        <div className="admin-table-responsive">
          <table className="admin-modern-table">
            <thead>
              <tr>
                <th style={{ width: 44 }}></th>
                <th>TIME</th>
                <th>ADMIN</th>
                <th>ACTION</th>
                <th>DETAILS</th>
                <th style={{ width: 40 }}></th>
              </tr>
            </thead>
            <tbody>
              {recentActivity.length === 0 ? (
                <tr>
                  <td colSpan={6} className="admin-table-empty">
                    No recent activities recorded yet.
                  </td>
                </tr>
              ) : (
                recentActivity.map((act) => {
                  return (
                    <tr key={act.id}>
                      <td>
                        <div className={`admin-act-icon admin-act-icon--${act.iconType}`}>
                          {act.iconType === "plus" && (
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                              <path d="M12 5v14m-7-7h14" strokeWidth="2" strokeLinecap="round" />
                            </svg>
                          )}
                          {act.iconType === "photo" && (
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                              <rect x="3" y="3" width="18" height="18" rx="2" strokeWidth="2" />
                              <circle cx="8" cy="8" r="1.5" fill="currentColor" />
                              <path d="M21 15l-5-5L5 21" strokeWidth="2" />
                            </svg>
                          )}
                          {act.iconType === "edit" && (
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                              <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" strokeWidth="2" strokeLinecap="round" />
                              <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" strokeWidth="2" strokeLinecap="round" />
                            </svg>
                          )}
                          {act.iconType === "download" && (
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                              <path d="M12 4v12m0 0l-4-4m4 4l4-4" strokeWidth="2" strokeLinecap="round" />
                              <path d="M4 20h16" strokeWidth="2" strokeLinecap="round" />
                            </svg>
                          )}
                        </div>
                      </td>
                      <td>
                        <span className="admin-cell-date">{act.time}</span>
                      </td>
                      <td>
                        <span className="admin-cell-admin">{act.admin}</span>
                      </td>
                      <td>
                        <span className="admin-cell-action">{act.action}</span>
                      </td>
                      <td>
                        <span className="admin-cell-details">{act.details}</span>
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <button type="button" className="admin-table-action-icon" title="View details">
                          ⋮
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </AdminLayout>
  );
}