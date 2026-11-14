import { FormEvent, useEffect, useState } from "react";
import { superAdminService } from "../../services/superAdmin";
import type { Studio } from "../../types/superAdmin";
import UsageMeter from "./UsageMeter";
import { BYTE_UNITS, ByteUnit, formatBytes, splitBytes, toBytes } from "../../utils/superAdminFormat";

export default function StudioQuotaCard({
  studio,
  onSaved,
  bare = false,
}: {
  studio: Pick<Studio, "id" | "usage">;
  onSaved: () => void;
  // Inside a dialog the surrounding card/heading are dropped.
  bare?: boolean;
}) {
  const { usage } = studio;
  const initial = splitBytes(usage.quota_bytes);
  const [value, setValue] = useState(initial.value);
  const [unit, setUnit] = useState<ByteUnit>(initial.unit);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-seed the editor when the saved quota changes (after save / reload).
  useEffect(() => {
    const s = splitBytes(usage.quota_bytes);
    setValue(s.value);
    setUnit(s.unit);
  }, [usage.quota_bytes]);

  const held = usage.used_bytes + usage.reserved_bytes;
  const parsed = toBytes(value, unit);
  const changed = parsed !== null && parsed !== usage.quota_bytes;

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (parsed === null) {
      setError("Enter a positive number.");
      return;
    }
    if (parsed < held) {
      setError(`The quota cannot be lower than what the studio already holds (${formatBytes(held)}).`);
      return;
    }
    setBusy(true);
    try {
      await superAdminService.setQuota(studio.id, parsed);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update the quota.");
    } finally {
      setBusy(false);
    }
  }

  const Wrapper = bare ? "div" : "section";
  return (
    <Wrapper className={bare ? undefined : "sa-card"}>
      {!bare && (
        <div className="sa-card__head">
          <h2>Storage</h2>
          <span className="sa-muted">Quota enforced by the platform on every upload.</span>
        </div>
      )}
      <UsageMeter used={usage.used_bytes} reserved={usage.reserved_bytes} total={usage.quota_bytes} />
      <dl className="sa-kv sa-kv--row">
        <div>
          <dt>Quota</dt>
          <dd>{formatBytes(usage.quota_bytes)}</dd>
        </div>
        <div>
          <dt>Stored</dt>
          <dd>{formatBytes(usage.used_bytes)}</dd>
        </div>
        <div>
          <dt>Reserved by uploads</dt>
          <dd>{formatBytes(usage.reserved_bytes)}</dd>
        </div>
        <div>
          <dt>Remaining</dt>
          <dd>{formatBytes(usage.remaining_bytes)}</dd>
        </div>
      </dl>

      <form className="sa-inline-form" onSubmit={save}>
        <div className="sa-field">
          <span>Set quota</span>
          <div className="sa-input-group">
            <input inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} aria-label="Quota" />
            <select value={unit} onChange={(e) => setUnit(e.target.value as ByteUnit)} aria-label="Quota unit">
              {BYTE_UNITS.map((u) => (
                <option key={u.label} value={u.label}>
                  {u.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        <button type="submit" className="sa-btn sa-btn--dark" disabled={busy || !changed}>
          {busy ? "Saving…" : "Save quota"}
        </button>
      </form>
      {error && (
        <p className="sa-form-error" role="alert">
          {error}
        </p>
      )}
    </Wrapper>
  );
}
