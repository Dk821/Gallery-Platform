import { api } from "./api";

export interface CurrentUser {
  user_type: "admin" | "client";
  id: number;
  name: string;
}

export const authService = {
  adminLogin: (email: string, password: string) =>
    api.post<{ id: number; name: string }>("/auth/admin/login", { email, password }),

  clientLogin: (galleryId: string, password: string) =>
    api.post<{ id: number; name: string }>("/auth/client/login", { gallery_id: galleryId, password }),

  logout: () => api.post<null>("/auth/logout"),

  me: () => api.get<CurrentUser | null>("/auth/me"),
};
