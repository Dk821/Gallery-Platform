export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, exponent);
  return `${value.toFixed(exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

export interface ExpiryInfo {
  isExpired: boolean;
  daysUntil: number;
  isNearExpiry: boolean; // expires within 3 days, not yet expired
  label: string;
}

const NEAR_EXPIRY_DAYS = 3;

export function getExpiryInfo(expiresAt: string | null): ExpiryInfo | null {
  if (!expiresAt) return null;

  const expiryDate = new Date(expiresAt);
  const now = new Date();
  const msPerDay = 1000 * 60 * 60 * 24;
  const daysUntil = Math.ceil((expiryDate.getTime() - now.getTime()) / msPerDay);
  const isExpired = expiryDate.getTime() <= now.getTime();
  const isNearExpiry = !isExpired && daysUntil <= NEAR_EXPIRY_DAYS;

  const formattedDate = expiryDate.toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  let label: string;
  if (isExpired) {
    label = "Expired";
  } else if (isNearExpiry) {
    label = `⚠ Expires in ${daysUntil} ${daysUntil === 1 ? "day" : "days"}`;
  } else {
    label = `Expires on ${formattedDate}`;
  }

  return { isExpired, daysUntil, isNearExpiry, label };
}
