import { formatBytes, percent } from "../../utils/superAdminFormat";

interface UsageMeterProps {
  used: number;
  reserved: number;
  total: number;
  compact?: boolean;
  /** Text under the bar; defaults to "used of total". */
  caption?: string;
}

// Stacked bar: solid = stored, striped = reserved by in-flight uploads.
// Turns amber at 80% and red at 95% of the allowance (stored + reserved).
export default function UsageMeter({ used, reserved, total, compact, caption }: UsageMeterProps) {
  const usedPct = percent(used, total);
  const reservedPct = Math.min(percent(reserved, total), 100 - usedPct);
  const totalPct = percent(used + reserved, total);
  const level = totalPct >= 95 ? "danger" : totalPct >= 80 ? "warn" : "ok";

  return (
    <div className={`sa-meter sa-meter--${level}` + (compact ? " sa-meter--compact" : "")}>
      <div
        className="sa-meter__track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(totalPct)}
        aria-label="Storage used"
      >
        <div className="sa-meter__used" style={{ width: `${usedPct}%` }} />
        <div className="sa-meter__reserved" style={{ width: `${reservedPct}%` }} />
      </div>
      <div className="sa-meter__caption">
        {caption ?? (
          <>
            <strong>{formatBytes(used)}</strong> of {formatBytes(total)}
            {reserved > 0 && <span className="sa-meter__reserved-note"> · {formatBytes(reserved)} reserved</span>}
          </>
        )}
        <span className="sa-meter__pct">{totalPct.toFixed(totalPct >= 10 ? 0 : 1)}%</span>
      </div>
    </div>
  );
}
