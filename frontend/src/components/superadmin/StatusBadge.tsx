export default function StatusBadge({ status }: { status: string }) {
  const kind = status === "active" ? "ok" : status === "suspended" ? "danger" : "muted";
  return <span className={`sa-badge sa-badge--${kind}`}>{status}</span>;
}
