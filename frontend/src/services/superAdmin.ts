import { api, API_BASE_URL, Page } from "./api";
import type {
  AuditLogPage,
  AuditLogQuery,
  AuditLogRow,
  PlatformStats,
  PlatformTrends,
  LoginState,
  StorageReport,
  SuperAdminAccount,
  StudioLoginsPage,
  Studio,
  StudioAdminRow,
  StudioCreateInput,
  StudioCreated,
  StudioDetail,
  StudioStatus,
  StudioUpdateInput,
} from "../types/superAdmin";

function qs(params: Record<string, string | number | null | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

function auditQs(q: AuditLogQuery, paged: boolean): string {
  return qs({
    page: paged ? q.page : undefined,
    limit: paged ? q.limit : undefined,
    sort: paged ? q.sort : undefined,
    studio_id: q.studio_id,
    action: q.action?.trim(),
    from: q.from,
    to: q.to,
    category: q.category,
    actor: q.actor,
    search: q.search?.trim(),
    // from/to are the viewer's calendar days, so the server needs their UTC offset (minutes east).
    tz_offset: -new Date().getTimezoneOffset(),
  });
}

export const superAdminService = {
  stats: () => api.get<PlatformStats>("/super-admin/stats"),
  logins: (p: { page?: number; limit?: number; state?: LoginState | ""; search?: string } = {}) =>
    api.get<StudioLoginsPage>(`/super-admin/logins${qs({ page: p.page, limit: p.limit, state: p.state, search: p.search?.trim() })}`),
  storageCheck: () => api.get<StorageReport>("/super-admin/storage/reconcile"),
  storageRepair: () => api.post<StorageReport>("/super-admin/storage/reconcile", {}),
  trends: (r: { days: number } | { start: string; end: string }) =>
    api.get<PlatformTrends>(`/super-admin/stats/trends${qs("days" in r ? { days: r.days } : { start: r.start, end: r.end })}`),

  listStudios: (p: { page?: number; limit?: number; search?: string; status?: StudioStatus | "" } = {}) =>
    api.get<Page<Studio>>(
      `/super-admin/studios${qs({ page: p.page, limit: p.limit, search: p.search?.trim(), status: p.status })}`
    ),
  createStudio: (input: StudioCreateInput) => api.post<StudioCreated>("/super-admin/studios", input),
  getStudio: (id: number) => api.get<StudioDetail>(`/super-admin/studios/${id}`),
  updateStudio: (id: number, input: StudioUpdateInput) => api.put<Studio>(`/super-admin/studios/${id}`, input),
  // The logo is a picture upload (multipart), not a URL.
  uploadLogo: (id: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.postForm<Studio>(`/super-admin/studios/${id}/logo`, form);
  },
  removeLogo: (id: number) => api.delete<Studio>(`/super-admin/studios/${id}/logo`),
  // Without options only an empty studio is deleted. With deleteData the studio AND everything it holds
  // (clients, albums, photos/videos and their stored files) goes too; the exact studio name must be sent.
  deleteStudio: (id: number, opts?: { deleteData: boolean; confirmName: string }) =>
    api.delete<{ id: number; deleted: boolean; data_deleted?: boolean; storage_failures?: number }>(
      `/super-admin/studios/${id}${
        opts?.deleteData ? `?delete_data=true&confirm_name=${encodeURIComponent(opts.confirmName)}` : ""
      }`
    ),
  suspendStudio: (id: number, reason?: string) =>
    api.post<Studio>(`/super-admin/studios/${id}/suspend`, { reason: reason?.trim() || null }),
  reactivateStudio: (id: number, reason?: string) =>
    api.post<Studio>(`/super-admin/studios/${id}/reactivate`, { reason: reason?.trim() || null }),
  setQuota: (id: number, quotaBytes: number) =>
    api.put<Studio>(`/super-admin/studios/${id}/quota`, { quota_bytes: quotaBytes }),

  listAdmins: (studioId: number) => api.get<StudioAdminRow[]>(`/super-admin/studios/${studioId}/admins`),
  createAdmin: (studioId: number, input: { name: string; email: string; password?: string | null }) =>
    api.post<{ admin: { id: number; name: string; email: string }; temporary_password: string | null }>(
      `/super-admin/studios/${studioId}/admins`,
      input
    ),
  updateAdmin: (studioId: number, adminId: number, input: { name?: string; email?: string }) =>
    api.put<StudioAdminRow>(`/super-admin/studios/${studioId}/admins/${adminId}`, input),
  disableAdmin: (studioId: number, adminId: number) =>
    api.post<{ id: number; status: string }>(`/super-admin/studios/${studioId}/admins/${adminId}/disable`),
  enableAdmin: (studioId: number, adminId: number) =>
    api.post<{ id: number; status: string }>(`/super-admin/studios/${studioId}/admins/${adminId}/enable`),
  resetAdminPassword: (studioId: number, adminId: number, newPassword?: string | null) =>
    api.post<{ admin_id: number; temporary_password: string | null }>(
      `/super-admin/studios/${studioId}/admins/${adminId}/reset-password`,
      newPassword ? { new_password: newPassword } : {}
    ),

  account: () => api.get<SuperAdminAccount>("/super-admin/account"),
  /** Name, company name and contact number need no password; a new email needs the current password.
   *  An empty company name / contact number clears it. */
  updateAccount: (input: {
    name?: string;
    email?: string;
    current_password?: string;
    company_name?: string;
    contact_phone?: string;
  }) => api.put<SuperAdminAccount>("/super-admin/account", input),
  /** The company logo shown in the sidebar: a picture upload (multipart). */
  uploadAccountLogo: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.postForm<SuperAdminAccount>("/super-admin/account/logo", form);
  },
  removeAccountLogo: () => api.delete<SuperAdminAccount>("/super-admin/account/logo"),
  /** Signs out every other browser/device; this one stays signed in. */
  signOutOtherDevices: () => api.post<null>("/super-admin/sign-out-others", {}),
  // The signed-in super admin changes their OWN password.
  changePassword: (currentPassword: string, newPassword: string) =>
    api.post<null>("/super-admin/change-password", {
      current_password: currentPassword,
      new_password: newPassword,
    }),

  auditLogs: (q: AuditLogQuery = {}) => api.get<AuditLogPage>(`/super-admin/audit-logs${auditQs(q, true)}`),
  /** CSV of every entry matching the filters (newest first, at most 10,000). Returns the file to save. */
  exportAuditLogs: async (q: AuditLogQuery = {}): Promise<{ blob: Blob; filename: string }> => {
    const res = await fetch(`${API_BASE_URL}/api/super-admin/audit-logs/export${auditQs(q, false)}`, {
      credentials: "include",
      cache: "no-store",
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new Error(body?.error?.message ?? "The export failed.");
    }
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1];
    return { blob: await res.blob(), filename: name ?? "audit-log.csv" };
  },
};
