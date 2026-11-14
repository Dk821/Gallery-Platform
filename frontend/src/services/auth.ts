import { api } from "./api";
import { clearBranding } from "./studioBranding";

export type AdminRole = "super_admin" | "studio_admin";

export interface CurrentUser {
  user_type: "admin" | "client";
  id: number;
  name: string;
  // Only present for admins. A missing role is treated as a studio admin.
  role?: AdminRole;
  studio_id?: number | null;
  studio_name?: string | null;
  // Super admins only: the company name and logo shown in the console sidebar.
  company_name?: string | null;
  logo_url?: string | null;
}

export function isSuperAdmin(user: CurrentUser | null | undefined): boolean {
  return !!user && user.user_type === "admin" && user.role === "super_admin";
}

export const authService = {
  adminLogin: (email: string, password: string) => {
    clearBranding(); // never show the previous admin's studio
    return api.post<{ id: number; name: string; role?: AdminRole; studio_id?: number | null }>("/auth/admin/login", {
      email,
      password,
    });
  },

  clientLogin: (galleryId: string, password: string) =>
    api.post<{ id: number; name: string }>("/auth/client/login", { gallery_id: galleryId, password }),

  logout: () => {
    clearBranding();
    return api.post<null>("/auth/logout");
  },

  me: () => api.get<CurrentUser | null>("/auth/me"),
};
