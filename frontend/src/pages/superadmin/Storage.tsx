import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Page } from "../../services/api";
import { superAdminService } from "../../services/superAdmin";
import type { PlatformStats, Studio } from "../../types/superAdmin";
import Modal from "../../components/superadmin/Modal";
import StatusBadge from "../../components/superadmin/StatusBadge";
import StudioQuotaCard from "../../components/superadmin/StudioQuotaCard";
import UsageMeter from "../../components/superadmin/UsageMeter";
import { IconRefresh, IconSearch, IconWarn } from "../../components/superadmin/Icons";
import { useToast } from "../../components/superadmin/Toast";
import { formatBytes, formatNumber, percent } from "../../utils/superAdminFormat";
import { useDebounced } from "../../utils/useDebounced";

type Filter = "" | "nearly" | "suspended";
type SortKey = "used" | "pct" | "quota" | "name";

const held = (s: Studio) => s.usage.used_bytes + s.usage.reserved_bytes;
const pct = (s: Studio) => percent(held(s), s.usage.quota_bytes);

export default function Storage() {
  const toast = useToast();
  const [stats, setStats] = useState<PlatformStats | null>(null);
  const [studios, setStudios] = useState<Page<Studio> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("");
  const [sort, setSort] = useState<SortKey>("used");
  const debounced = useDebounced(search);
  const [editingId, setEditingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    const [s, st] = await Promise.all([superAdminService.stats(), superAdminService.listStudios({ limit: 200 })]);
    setStats(s);
    setStudios(st);
  }, []);

  useEffect(() => {
    load().catch((err) => setError(err instanceof Error ? err.message : "Could not load storage."));
  }, [load]);

  const refresh = () => {
    setRefreshing(true);
    load()
      .catch((err) => setError(err instanceof Error ? err.message : "Could not refresh."))
      .finally(() => setRefreshing(false));
  };

  const rows = useMemo(() => {
    if (!studios) return [];
    const q = debounced.trim().toLowerCase();
    return studios.items
      .filter((s) => (q ? s.name.toLowerCase().includes(q) : true))
      .filter((s) => (filter === "nearly" ? s.usage.quota_bytes > 0 && pct(s) >= 80 : filter === "suspended" ? s.status === "suspended" : true))
      .sort((a, b) => {
        if (sort === "name") return a.name.localeCompare(b.name);
        if (sort === "pct") return pct(b) - pct(a);
        if (sort === "quota") return b.usage.quota_bytes - a.usage.quota_bytes;
        return held(b) - held(a);
      });
  }, [studios, debounced, filter, sort]);

  if (error) return <p className="sa-form-error">{error}</p>;
  if (!stats || !studios) return <p className="sa-muted">Loading…</p>;

  const { storage } = stats;
  const oversold = storage.allocated_quota_bytes > storage.capacity_bytes;
  const capacityPct = percent(storage.used_bytes + storage.reserved_bytes, storage.capacity_bytes);
  const nearlyCount = studios.items.filter((s) => s.usage.quota_bytes > 0 && pct(s) >= 80).length;
  const editing = studios.items.find((s) => s.id === editingId) ?? null;

  return (
    <>
      <div className="sa-page-head">
        <div>
          <h1>Storage</h1>
          <p className="sa-page-head__sub">Platform capacity and every studio's storage allowance.</p>
        </div>
        <button type="button" className="sa-btn sa-btn--ghost sa-btn--sm sa-btn--icon" onClick={refresh} disabled={refreshing}>
          <span className={refreshing ? "sa-spin" : undefined}>
            <IconRefresh />
          </span>
          Refresh
        </button>
      </div>

      <section className="sa-card">
        <div className="sa-card__head">
          <h2>Platform capacity</h2>
          <span className="sa-muted sa-small">Capacity is enforced by the platform, not the storage provider.</span>
        </div>
        <UsageMeter used={storage.used_bytes} reserved={storage.reserved_bytes} total={storage.capacity_bytes} />
        <dl className="sa-kv sa-kv--row">
          <div>
            <dt>Capacity</dt>
            <dd>{formatBytes(storage.capacity_bytes)}</dd>
          </div>
          <div>
            <dt>Stored</dt>
            <dd>{formatBytes(storage.used_bytes)}</dd>
          </div>
          <div>
            <dt>Reserved by uploads</dt>
            <dd>{formatBytes(storage.reserved_bytes)}</dd>
          </div>
          <div>
            <dt>Remaining</dt>
            <dd>{formatBytes(storage.remaining_bytes)}</dd>
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
          <p className="sa-notice sa-notice--warn sa-notice--icon" role="status">
            <IconWarn />
            <span>Platform storage is {capacityPct.toFixed(0)}% full. New uploads are rejected once capacity is reached.</span>
          </p>
        )}
        {oversold && (
          <p className="sa-muted sa-small">
            Studio quotas add up to more than the platform capacity. That is allowed, but the platform limit will stop uploads first.
          </p>
        )}
      </section>

      <section>
        <div className="sa-sec-head">
          <h2>Studio allowances</h2>
          <span className="sa-muted sa-small">{formatNumber(rows.length)} of {formatNumber(studios.items.length)} studios</span>
        </div>

        <div className="sa-toolbar sa-toolbar--wrap">
          <label className="sa-search">
            <IconSearch />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search studios" aria-label="Search studios" />
          </label>
          <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)} aria-label="Filter studios">
            <option value="">All studios</option>
            <option value="nearly">Nearly full (80%+){nearlyCount ? ` · ${nearlyCount}` : ""}</option>
            <option value="suspended">Suspended</option>
          </select>
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Sort studios">
            <option value="used">Most storage</option>
            <option value="pct">Closest to quota</option>
            <option value="quota">Largest quota</option>
            <option value="name">Name</option>
          </select>
        </div>

        <div className="sa-card sa-card--flush">
          {rows.length === 0 ? (
            <p className="sa-empty">{debounced || filter ? "No studios match these filters." : "No studios yet."}</p>
          ) : (
            <div className="sa-table-wrap">
              <table className="sa-table">
                <thead>
                  <tr>
                    <th>Studio</th>
                    <th className="sa-num">Quota</th>
                    <th className="sa-num">Stored</th>
                    <th className="sa-num">Reserved</th>
                    <th className="sa-num">Remaining</th>
                    <th className="sa-col-usage">Used</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((s) => (
                    <tr key={s.id}>
                      <td>
                        <Link to={`/super-admin/studios/${s.id}`} className="sa-table__title">
                          {s.name}
                        </Link>{" "}
                        {s.status === "suspended" && <StatusBadge status="suspended" />}
                      </td>
                      <td className="sa-num">{formatBytes(s.usage.quota_bytes)}</td>
                      <td className="sa-num">{formatBytes(s.usage.used_bytes)}</td>
                      <td className="sa-num sa-muted">{formatBytes(s.usage.reserved_bytes)}</td>
                      <td className="sa-num">{formatBytes(s.usage.remaining_bytes)}</td>
                      <td className="sa-col-usage">
                        <UsageMeter compact used={s.usage.used_bytes} reserved={s.usage.reserved_bytes} total={s.usage.quota_bytes} />
                      </td>
                      <td className="sa-table__actions">
                        <button type="button" className="sa-btn sa-btn--ghost sa-btn--sm" onClick={() => setEditingId(s.id)}>
                          Edit quota
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      {editing && (
        <Modal title={`Storage quota — ${editing.name}`} onClose={() => setEditingId(null)}>
          <StudioQuotaCard
            bare
            studio={editing}
            onSaved={() => {
              // Close the dialog once the quota is saved, so it is clear the change went through.
              setEditingId(null);
              toast.success(`Storage quota updated for ${editing.name}.`);
              load().catch(() => undefined);
            }}
          />
          <div className="sa-modal-card__actions">
            <button type="button" className="sa-btn sa-btn--dark" onClick={() => setEditingId(null)}>
              Done
            </button>
          </div>
        </Modal>
      )}

    </>
  );
}
