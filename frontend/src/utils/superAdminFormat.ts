// DECIMAL units on purpose (1 GB = 10^9 bytes, 1 TB = 10^12): the backend's
// PLATFORM_CAPACITY_BYTES / DEFAULT_STUDIO_QUOTA_BYTES defaults are decimal,
// so "1 TB" here means exactly the same thing as "1 TB" in the configuration.
export const BYTE_UNITS = [
  { label: "MB", factor: 1e6 },
  { label: "GB", factor: 1e9 },
  { label: "TB", factor: 1e12 },
] as const;

export type ByteUnit = (typeof BYTE_UNITS)[number]["label"];

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  const exp = Math.min(Math.floor(Math.log10(bytes) / 3), units.length - 1);
  const value = bytes / Math.pow(1000, exp);
  const digits = exp === 0 ? 0 : value >= 100 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${units[exp]}`;
}

/** Picks the largest unit that keeps the number >= 1 - used to pre-fill the quota editor. */
export function splitBytes(bytes: number): { value: string; unit: ByteUnit } {
  for (let i = BYTE_UNITS.length - 1; i >= 0; i--) {
    const { label, factor } = BYTE_UNITS[i];
    if (bytes >= factor) return { value: String(Math.round((bytes / factor) * 1000) / 1000), unit: label };
  }
  return { value: String(Math.round((bytes / 1e6) * 1000) / 1000), unit: "MB" };
}

/** Parses "<number> + unit" into whole bytes; null when the input is not a positive number. */
export function toBytes(value: string, unit: ByteUnit): number | null {
  const n = Number(value.replace(",", ".").trim());
  if (!Number.isFinite(n) || n <= 0) return null;
  const factor = BYTE_UNITS.find((u) => u.label === unit)!.factor;
  return Math.round(n * factor);
}

export function percent(part: number, whole: number): number {
  if (whole <= 0) return 0;
  return Math.min(100, Math.max(0, (part / whole) * 100));
}

export function formatDateTime(iso: string): string {
  // The API returns naive UTC timestamps (no zone suffix); treat them as UTC.
  const hasZone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso);
  const d = new Date(hasZone ? iso : `${iso}Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDate(iso: string): string {
  const hasZone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso);
  const d = new Date(hasZone ? iso : `${iso}Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function formatNumber(n: number): string {
  return n.toLocaleString();
}

/** "studio_quota_changed" -> "Studio quota changed" */
export function humanizeAction(action: string): string {
  const s = action.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}
