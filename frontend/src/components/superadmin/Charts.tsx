import { ReactNode, RefObject, useEffect, useRef, useState } from "react";

// Small dependency-free SVG charts for the Super Admin dashboard. Colours come
// from CSS custom properties on `.sa` (--sa-c1 ...), so they follow the console theme.

export const CHART_COLORS = ["var(--sa-c1)", "var(--sa-c2)", "var(--sa-c3)", "var(--sa-c4)"];

function useWidth<T extends HTMLElement>(): [RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

/** Rounds a maximum up to a "nice" number so the grid lines read well (1, 2, 2.5, 5, 10 x 10^n). */
function niceMax(max: number): number {
  if (max <= 0) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(max)));
  const n = max / pow;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
  return step * pow;
}

export interface Point {
  label: string; // shown in the tooltip
  short: string; // shown on the x axis
  value: number;
}

interface AreaChartProps {
  points: Point[];
  format: (v: number) => string;
  color?: string;
  height?: number;
  ariaLabel: string;
  emptyText?: string;
}

export function AreaChart({ points, format, color = CHART_COLORS[0], height = 250, ariaLabel, emptyText }: AreaChartProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const gradId = useRef(`sa-grad-${Math.random().toString(36).slice(2, 8)}`).current;

  const padL = 52, padR = 14, padT = 14, padB = 26;
  const w = Math.max(width, 240);
  const innerW = w - padL - padR;
  const innerH = height - padT - padB;
  const max = niceMax(Math.max(0, ...points.map((p) => p.value)));
  const empty = points.every((p) => p.value === 0);
  const x = (i: number) => padL + (points.length <= 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
  const y = (v: number) => padT + innerH - (v / max) * innerH;

  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const area = points.length ? `${line} L${x(points.length - 1).toFixed(1)},${padT + innerH} L${x(0).toFixed(1)},${padT + innerH} Z` : "";
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * max);
  const every = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(innerW / 70))));

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left - padL;
    const idx = Math.round((px / innerW) * (points.length - 1));
    setHover(Math.min(points.length - 1, Math.max(0, idx)));
  };
  const hp = hover !== null ? points[hover] : null;
  const tipLeft = hover !== null ? Math.min(Math.max(x(hover), 70), w - 70) : 0;

  return (
    <div className="sa-chart" ref={ref} style={{ height }}>
      {width > 0 && (
        <svg width={w} height={height} role="img" aria-label={ariaLabel} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.28" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={padL} x2={w - padR} y1={y(t)} y2={y(t)} className="sa-chart__grid" />
              <text x={padL - 8} y={y(t) + 4} textAnchor="end" className="sa-chart__tick">
                {format(t)}
              </text>
            </g>
          ))}
          {points.map((p, i) =>
            i % every === 0 ? (
              <text key={p.label} x={x(i)} y={height - 7} textAnchor="middle" className="sa-chart__tick">
                {p.short}
              </text>
            ) : null
          )}
          {!empty && <path d={area} fill={`url(#${gradId})`} />}
          <path d={line} fill="none" stroke={color} strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />
          {hover !== null && hp && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={padT} y2={padT + innerH} className="sa-chart__cursor" />
              <circle cx={x(hover)} cy={y(hp.value)} r="4.5" fill="#fff" stroke={color} strokeWidth="2.2" />
            </g>
          )}
        </svg>
      )}
      {empty && width > 0 && <div className="sa-chart__empty">{emptyText ?? "No activity in this period"}</div>}
      {hp && (
        <div className="sa-chart__tip" style={{ left: tipLeft, top: Math.max(0, y(hp.value) - 54) }}>
          <span>{hp.label}</span>
          <strong>{format(hp.value)}</strong>
        </div>
      )}
    </div>
  );
}

/** Tiny trend line for the KPI cards. */
export function Sparkline({ values, color = CHART_COLORS[0] }: { values: number[]; color?: string }) {
  const W = 120, H = 34, pad = 3;
  const max = Math.max(1, ...values);
  const x = (i: number) => pad + (values.length <= 1 ? (W - 2 * pad) / 2 : (i / (values.length - 1)) * (W - 2 * pad));
  const y = (v: number) => H - pad - (v / max) * (H - 2 * pad);
  const d = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg className="sa-spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
      <path d={d} fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export interface Slice {
  label: string;
  value: number;
  color: string;
}

/** Ring chart; `children` is rendered in the hole (HTML, centred). */
export function Donut({ slices, size = 168, thickness = 20, ariaLabel, children }: { slices: Slice[]; size?: number; thickness?: number; ariaLabel: string; children?: ReactNode }) {
  const total = slices.reduce((a, s) => a + Math.max(0, s.value), 0);
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div className="sa-donut" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={ariaLabel}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" className="sa-donut__track" strokeWidth={thickness} />
        {total > 0 &&
          slices.map((s) => {
            const len = (Math.max(0, s.value) / total) * c;
            const el = (
              <circle
                key={s.label}
                cx={size / 2}
                cy={size / 2}
                r={r}
                fill="none"
                stroke={s.color}
                strokeWidth={thickness}
                strokeDasharray={`${Math.max(0, len - (slices.length > 1 && len > 2 ? 2 : 0))} ${c}`}
                strokeDashoffset={-offset}
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
              />
            );
            offset += len;
            return len > 0 ? el : null;
          })}
      </svg>
      <div className="sa-donut__center">{children}</div>
    </div>
  );
}

export interface BarRow {
  key: string | number;
  label: ReactNode;
  value: number; // the bar length
  display: string; // text at the right end
  sub?: string;
  level?: "ok" | "warn" | "danger";
}

/** Horizontal bar list. Bars scale to `max` (defaults to the largest value). */
export function BarList({ rows, max }: { rows: BarRow[]; max?: number }) {
  const top = max ?? Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="sa-bars">
      {rows.map((r) => (
        <li key={r.key} className="sa-bars__row">
          <div className="sa-bars__top">
            <span className="sa-bars__label">{r.label}</span>
            <span className="sa-bars__value">{r.display}</span>
          </div>
          <div className="sa-bars__track" aria-hidden="true">
            <div className={`sa-bars__fill sa-bars__fill--${r.level ?? "ok"}`} style={{ width: `${Math.min(100, Math.max(r.value > 0 ? 1.5 : 0, (r.value / top) * 100))}%` }} />
          </div>
          {r.sub && <span className="sa-bars__sub">{r.sub}</span>}
        </li>
      ))}
    </ul>
  );
}
