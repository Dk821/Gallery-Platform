import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { superAdminService } from "../../services/superAdmin";
import type { LoginState, StudioLoginsPage } from "../../types/superAdmin";
import Pagination from "../../components/superadmin/Pagination";
import StatusBadge from "../../components/superadmin/StatusBadge";
import { IconSearch } from "../../components/superadmin/Icons";
import { formatDate, formatDateTime, formatNumber } from "../../utils/superAdminFormat";
import { useDebounced } from "../../utils/useDebounced";

const LIMIT = 25;

const FILTERS: { key: LoginState | ""; label: string; count: (s: StudioLoginsPage["summary"]) => number }[] = [
  { key: "", label: "All studios", count: (s) => s.studios },
  { key: "active", label: "Active logins", count: (s) => s.active },
  { key: "disabled", label: "Disabled", count: (s) => s.disabled },
  { key: "none", label: "No login", count: (s) => s.none },
];

export default function StudioLogins() {
  const [search, setSearch] = useState("");
  const [state, setState] = useState<LoginState | "">("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<StudioLoginsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const debounced = useDebounced(search);

  useEffect(() => setPage(1), [debounced, state]);

  useEffect(() => {
    let active = true;
    setError(null);
    superAdminService
      .logins({ page, limit: LIMIT, state, search: debounced })
      .then((d) => active && setData(d))
      .catch((err) => active && setError(err instanceof Error ? err.message : "Could not load the studio logins."));
    return () => {
      active = false;
    };
  }, [page, state, debounced]);

  return (
    <>
      <div className="sa-page-head">
        <div>
          <h1>Studio logins</h1>
          <p className="sa-page-head__sub">
            Every studio has exactly one login. Open a studio to reset its password, change the email or switch the login off.
          </p>
        </div>
      </div>

      {data && (
        <div className="sa-chips" role="group" aria-label="Filter by login state">
          {FILTERS.map((f) => (
            <button
              key={f.key || "all"}
              type="button"
              className={`sa-chip${state === f.key ? " is-active" : ""}`}
              aria-pressed={state === f.key}
              onClick={() => setState(f.key)}
            >
              {f.label} <strong>{formatNumber(f.count(data.summary))}</strong>
            </button>
          ))}
        </div>
      )}

      <div className="sa-toolbar">
        <label className="sa-search">
          <IconSearch />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by studio, login name or email" aria-label="Search logins" />
        </label>
      </div>

      {error && <p className="sa-form-error">{error}</p>}
      {!data && !error && <p className="sa-muted">Loading…</p>}

      {data && (
        <div className="sa-card sa-card--flush">
          {data.items.length === 0 ? (
            <p className="sa-empty">{debounced || state ? "No logins match these filters." : "No studios yet."}</p>
          ) : (
            <div className="sa-table-wrap">
              <table className="sa-table">
                <thead>
                  <tr>
                    <th>Studio</th>
                    <th>Login</th>
                    <th>Status</th>
                    <th>Last sign-in</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((row) => (
                    <tr key={`${row.studio_id}-${row.login?.id ?? "none"}`}>
                      <td>
                        <Link to={`/super-admin/studios/${row.studio_id}`} className="sa-table__title">
                          {row.studio_name}
                        </Link>
                        {row.studio_status === "suspended" && (
                          <>
                            {" "}
                            <StatusBadge status="suspended" />
                          </>
                        )}
                      </td>
                      <td>
                        {row.login ? (
                          <>
                            <div>{row.login.name}</div>
                            <div className="sa-muted sa-small">{row.login.email}</div>
                          </>
                        ) : (
                          <span className="sa-muted">—</span>
                        )}
                      </td>
                      <td>
                        {row.login ? (
                          <span className={`sa-badge sa-badge--${row.login.status === "active" ? "ok" : "muted"}`}>{row.login.status}</span>
                        ) : (
                          <span className="sa-badge sa-badge--warn">no login</span>
                        )}
                      </td>
                      <td className="sa-muted sa-nowrap">{row.login ? (row.login.last_login ? formatDateTime(row.login.last_login) : "Never") : "—"}</td>
                      <td className="sa-muted sa-nowrap">{row.login ? formatDate(row.login.created_at) : "—"}</td>
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
    </>
  );
}
