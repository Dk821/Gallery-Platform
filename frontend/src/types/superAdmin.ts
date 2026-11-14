import type { Page } from "../services/api";
// Mirrors the backend's /api/super-admin responses (app/schemas/studio.py,
// app/services/studio_service.py, app/services/quota_service.py).

export type StudioStatus = "active" | "suspended";

export interface StudioUsage {
  quota_bytes: number;
  used_bytes: number;
  reserved_bytes: number;
  remaining_bytes: number;
}

export interface Studio {
  id: number;
  name: string;
  contact_email: string | null;
  contact_phone: string | null;
  logo_url: string | null;
  brand_color: string | null;
  status: StudioStatus;
  created_at: string;
  updated_at: string;
  usage: StudioUsage;
}

export interface StudioCounts {
  admins: number;
  clients: number;
  albums: number;
  media: number;
}

export interface StudioDetail extends Studio {
  counts: StudioCounts;
}

export interface PlatformStorage {
  capacity_bytes: number;
  provider_limit_bytes?: number | null;
  provider_usage_bytes?: number | null;
  used_bytes: number;
  reserved_bytes: number;
  remaining_bytes: number;
  allocated_quota_bytes: number;
}

export interface PlatformStats {
  studios: { total: number; active: number; suspended: number };
  totals: { clients: number; albums: number; media: number };
  storage: PlatformStorage;
  unmapped_legacy_rows: { admins: number; clients: number; albums: number; media: number };
}

export interface TrendDay {
  date: string; // YYYY-MM-DD (UTC)
  studios: number;
  clients: number;
  albums: number;
  media: number;
  uploaded_bytes: number;
  downloads: number;
  downloaded_bytes: number;
}

export type TrendTotals = Omit<TrendDay, "date">;

/** GET /api/super-admin/stats/trends - daily activity for the dashboard charts. */
export interface PlatformTrends {
  range_days: number;
  series: TrendDay[];
  totals: TrendTotals;
  previous_totals: TrendTotals;
  media_types: { photo: { files: number; bytes: number }; video: { files: number; bytes: number } };
  most_active_studios: { studio_id: number; name: string; files: number; uploaded_bytes: number }[];
}

export interface StudioAdminRow {
  id: number;
  name: string;
  email: string;
  status: string;
  created_at: string;
}

export interface StudioCreateInput {
  name: string;
  contact_email?: string | null;
  contact_phone?: string | null;
  logo_url?: string | null;
  brand_color?: string | null;
  quota_bytes?: number | null;
  admin_name: string;
  admin_email: string;
  admin_password?: string | null;
}

export interface StudioUpdateInput {
  name?: string;
  contact_email?: string | null;
  contact_phone?: string | null;
  logo_url?: string | null;
  brand_color?: string | null;
}

export interface StudioCreated {
  studio: Studio;
  admin: { id: number; name: string; email: string };
  temporary_password: string | null;
}

export interface AuditLogRow {
  id: number;
  created_at: string;
  action: string;
  user_type: string;
  user_id: number | null;
  actor_role: string | null;
  studio_id: number | null;
  resource_type: string | null;
  resource_id: number | null;
  ip_address: string | null;
  metadata: Record<string, unknown> | null;
}

export type AuditCategory = "sign_in" | "studios" | "logins" | "storage" | "content" | "problems";
export type AuditActor = "super_admin" | "studio_admin" | "client";

export interface AuditLogQuery {
  page?: number;
  limit?: number;
  studio_id?: number | null;
  action?: string;
  from?: string;
  to?: string;
  category?: AuditCategory | "";
  actor?: AuditActor | "";
  search?: string;
  sort?: "newest" | "oldest";
}

/** GET /api/super-admin/audit-logs - a page of rows plus a platform-wide pulse. */
export interface AuditLogPage extends Page<AuditLogRow> {
  summary: { events_24h: number; failed_sign_ins_24h: number; total: number };
}

/** One row of GET /api/super-admin/logins: a studio and its single login (null = no login yet). */
export interface StudioLoginEntry {
  studio_id: number;
  studio_name: string;
  studio_status: StudioStatus;
  login: {
    id: number;
    name: string;
    email: string;
    status: "active" | "disabled";
    created_at: string;
    last_login: string | null;
  } | null;
}

export interface StudioLoginsPage extends Page<StudioLoginEntry> {
  summary: { studios: number; active: number; disabled: number; none: number };
}

export type LoginState = "active" | "disabled" | "none";

/** GET / POST /api/super-admin/storage/reconcile - only studios that need attention are listed. */
export interface StorageDriftRow {
  studio_id: number;
  name: string;
  recorded_used_bytes: number;
  actual_used_bytes: number;
  recorded_reserved_bytes: number;
  actual_reserved_bytes: number;
  quota_bytes: number;
  used_drift_bytes: number;
  reserved_drift_bytes: number;
  over_quota: boolean;
  in_sync: boolean;
}

export interface StorageReport {
  applied: boolean;
  repaired_studios?: number;
  checked_studios: number;
  studios_out_of_sync: number;
  platform: {
    recorded_used_bytes: number;
    recorded_reserved_bytes: number;
    sum_of_studios_used_bytes: number;
    sum_of_studios_reserved_bytes: number;
    in_sync: boolean;
    capacity_bytes: number;
  };
  studios: StorageDriftRow[];
}

/** The signed-in super admin's own account (Settings page). */
export interface SuperAdminAccount {
  name: string;
  email: string;
  role: string;
  /** Company profile: the name and logo appear in the console sidebar. */
  company_name: string | null;
  contact_phone: string | null;
  logo_url: string | null;
  created_at: string;
  /** Newest first; includes failed attempts against this account. */
  recent_sign_ins: { at: string; ip_address: string | null; success: boolean }[];
}
