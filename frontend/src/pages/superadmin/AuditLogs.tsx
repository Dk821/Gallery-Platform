import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { superAdminService } from "../../services/superAdmin";
import type { AuditActor, AuditLogPage, AuditLogRow, Studio } from "../../types/superAdmin";
import Pagination from "../../components/superadmin/Pagination";
import { IconSearch } from "../../components/superadmin/Icons";
import { formatDateTime, formatNumber, humanizeAction } from "../../utils/superAdminFormat";
import { useDebounced } from "../../utils/useDebounced";

const PAGE_SIZES = [25, 50, 100] as const;

const ACTORS: { key: AuditActor | ""; label: string }[] = [
  { key: "", label: "Everyone" },
  { key: "super_admin", label: "Super admin" },
  { key: "studio_admin", label: "Studio admins" },
  { key: "client", label: "Clients" },
];

type Preset = "any" | "today" | "7d" | "30d" | "custom";
const PRESETS: { key: Preset; label: string }[] = [
  { key: "any", label: "Any time" },
  { key: "today", label: "Today" },
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
  { key: "custom", label: "Custom" },
];

const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return isoDay(d);
};

// The time range the log opens on: Today unless the Settings page chose another one.
function defaultPreset(): Preset {
  const saved = recall("sa.audit.range");
  return saved === "any" || saved === "7d" || saved === "30d" ? saved : "today";
}
function rangeFor(preset: Preset): { from: string; to: string } {
  if (preset === "today") return { from: isoDay(new Date()), to: isoDay(new Date()) };
  if (preset === "7d") return { from: daysAgo(6), to: isoDay(new Date()) };
  if (preset === "30d") return { from: daysAgo(29), to: isoDay(new Date()) };
  return { from: "", to: "" };
}

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

export default function AuditLogs() {
  const [params] = useSearchParams();
  const [studios, setStudios] = useState<Studio[]>([]);
  const [studioId, setStudioId] = useState(params.get("studio") ?? "");
  const [actor, setActor] = useState<AuditActor | "">("");
  const [search, setSearch] = useState("");
  // The log opens on today's entries (or the range chosen in Settings); the other ranges are one click away.
  const [initialPreset] = useState<Preset>(defaultPreset);
  const [preset, setPreset] = useState<Preset>(initialPreset);
  const [from, setFrom] = useState(() => rangeFor(initialPreset).from);
  const [to, setTo] = useState(() => rangeFor(initialPreset).to);
  const [sort, setSort] = useState<"newest" | "oldest">("newest");
  const [limit, setLimit] = useState<number>(() => {
    const saved = Number(recall("sa.audit.pageSize"));
    return (PAGE_SIZES as readonly number[]).includes(saved) ? saved : 50;
  });
  const [page, setPage] = useState(1);
  const [data, setData] = useState<AuditLogPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const debouncedSearch = useDebounced(search);

  useEffect(() => {
    superAdminService
      .listStudios({ limit: 200 })
      .then((p) => setStudios(p.items))
      .catch(() => {
        /* the filter just stays empty; logs still load */
      });
  }, []);

  useEffect(() => setPage(1), [studioId, actor, debouncedSearch, from, to, sort, limit]);

  const invalidRange = !!from && !!to && from > to;
  const query = useMemo(
    () => ({
      studio_id: studioId ? Number(studioId) : null,
      actor,
      search: debouncedSearch,
      from,
      to,
    }),
    [studioId, actor, debouncedSearch, from, to]
  );

  useEffect(() => {
    if (invalidRange) return;
    let active = true;
    setError(null);
    setLoading(true);
    superAdminService
      .auditLogs({ ...query, page, limit, sort })
      .then((d) => {
        if (!active) return;
        setData(d);
        setUpdatedAt(new Date());
      })
      .catch((err) => active && setError(err instanceof Error ? err.message : "Could not load the audit log."))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [query, page, limit, sort, invalidRange]);

  const choosePreset = useCallback((next: Preset) => {
    setPreset(next);
    if (next === "any") {
      setFrom("");
      setTo("");
    } else if (next === "today") {
      setFrom(isoDay(new Date()));
      setTo(isoDay(new Date()));
    } else if (next === "7d") {
      setFrom(daysAgo(6));
      setTo(isoDay(new Date()));
    } else if (next === "30d") {
      setFrom(daysAgo(29));
      setTo(isoDay(new Date()));
    }
  }, []);

  // The default range is the normal view, so it does not count as an active filter.
  const filtersActive = !!(studioId || actor || search || preset !== initialPreset);
  function clearAll() {
    setStudioId("");
    setActor("");
    setSearch("");
    choosePreset(initialPreset);
  }

  const names = new Map(studios.map((s) => [s.id, s.name]));

  return (
    <>
      <div className="sa-page-head">
        <div>
          <h1>Audit log</h1>
          <p className="sa-page-head__sub">
            Who did what, across every studio. Passwords, tokens and storage credentials are never recorded.
            {updatedAt && <span className="sa-dash-updated"> Updated {updatedAt.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}.</span>}
          </p>
        </div>
      </div>

      <div className="sa-toolbar sa-toolbar--wrap">
        <label className="sa-search">
          <IconSearch />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search action, studio, IP or id" aria-label="Search the audit log" />
        </label>
        <select value={studioId} onChange={(e) => setStudioId(e.target.value)} aria-label="Filter by studio">
          <option value="">All studios</option>
          {studios.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <select value={actor} onChange={(e) => setActor(e.target.value as AuditActor | "")} aria-label="Filter by who did it">
          {ACTORS.map((a) => (
            <option key={a.key || "all"} value={a.key}>
              {a.key ? a.label : "Everyone"}
            </option>
          ))}
        </select>
      </div>

      <div className="sa-toolbar sa-toolbar--wrap">
        <div className="sa-seg" role="group" aria-label="Time range">
          {PRESETS.map((p) => (
            <button key={p.key} type="button" className={`sa-seg__btn${preset === p.key ? " is-active" : ""}`} aria-pressed={preset === p.key} onClick={() => choosePreset(p.key)}>
              {p.label}
            </button>
          ))}
        </div>
        {(preset === "custom" || from || to) && (
          <>
            <label className="sa-date-field">
              <span>From</span>
              <input
                type="date"
                value={from}
                onChange={(e) => {
                  setPreset("custom");
                  setFrom(e.target.value);
                }}
              />
            </label>
            <label className="sa-date-field">
              <span>To</span>
              <input
                type="date"
                value={to}
                onChange={(e) => {
                  setPreset("custom");
                  setTo(e.target.value);
                }}
              />
            </label>
          </>
        )}
        <div className="sa-toolbar__bulk">
          <select value={sort} onChange={(e) => setSort(e.target.value as "newest" | "oldest")} aria-label="Sort order">
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
          </select>
          <select
            value={limit}
            onChange={(e) => {
              setLimit(Number(e.target.value));
              remember("sa.audit.pageSize", e.target.value);
            }}
            aria-label="Rows per page"
          >
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n} per page
              </option>
            ))}
          </select>
          {filtersActive && (
            <button type="button" className="sa-btn sa-btn--ghost sa-btn--sm" onClick={clearAll}>
              Clear filters
            </button>
          )}
        </div>
      </div>

      {invalidRange && <p className="sa-form-error">“From” must not be after “To”.</p>}
      {error && !invalidRange && <p className="sa-form-error">{error}</p>}
      {!data && !error && <p className="sa-muted">Loading…</p>}

      {data && !invalidRange && (
        <div className={`sa-card sa-card--flush${loading ? " is-busy" : ""}`}>
          {data.items.length === 0 ? (
            <p className="sa-empty">No audit entries match these filters.</p>
          ) : (
            <div className="sa-table-wrap">
              <table className="sa-table sa-table--stack sa-table--audit">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Action</th>
                    <th>Studio</th>
                    <th>Target</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((row) => (
                    <AuditRow key={row.id} row={row} studioName={row.studio_id ? (names.get(row.studio_id) ?? `#${row.studio_id}`) : null} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pagination page={data.page} limit={data.limit} total={data.total} onPage={setPage} />
        </div>
      )}
      {data && !invalidRange && <p className="sa-muted sa-small">{formatNumber(data.total)} matching entr{data.total === 1 ? "y" : "ies"}</p>}
    </>
  );
}

function AuditRow({ row, studioName }: { row: AuditLogRow; studioName: string | null }) {
  const failed = row.action.endsWith("_failed");
  return (
    <tr className={failed ? "sa-row--problem" : undefined}>
      <td className="sa-nowrap sa-muted" data-label="When">{formatDateTime(row.created_at)}</td>
      <td data-label="Action">
        <span className="sa-table__title">{humanizeAction(row.action)}</span>
        {failed && <span className="sa-badge sa-badge--danger sa-badge--inline">failed</span>}
      </td>
      <td data-label="Studio">
        {row.studio_id ? (
          <Link to={`/super-admin/studios/${row.studio_id}`}>{studioName}</Link>
        ) : (
          <span className="sa-muted">Platform</span>
        )}
      </td>
      <td className="sa-muted" data-label="Target">
        {row.resource_type ? `${row.resource_type.replace(/_/g, " ")}${row.resource_id ? ` #${row.resource_id}` : ""}` : "—"}
      </td>
    </tr>
  );
}
