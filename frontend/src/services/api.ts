// Where the backend lives, read from the frontend's own .env (see
// frontend/.env.example). Empty by default, which keeps today's behavior
// exactly as it was: requests go to a relative
// `/api/...` path, resolved by Vite's dev proxy locally and by the same
// reverse proxy/origin as the frontend in production. Set
// VITE_API_BASE_URL only when the frontend is deployed on a DIFFERENT
// origin than the backend (the scenario the backend's own
// CROSS_SITE_FRONTEND setting already exists for) - e.g.
// VITE_API_BASE_URL=https://api.yourdomain.com. Every call in this file,
// admin.ts and gallery.ts is built from this one constant, so pointing the
// whole app at a different backend is a single value to change, not a
// find-and-replace across the codebase.
export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export interface ApiError {
  code: string;
  message: string;
}

export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: ApiError;
}

export interface Page<T> {
  items: T[];
  page: number;
  limit: number;
  total: number;
  has_more: boolean;
}

// Mirrors the backend's MediaResponse exactly (app/schemas/media.py) - both
// the admin media-management UI and the client-facing gallery consume this
// same shape, since both sides are served by the same media_to_response()
// presenter. Defined once here so admin.ts and gallery.ts never drift out
// of sync with each other or with the backend.
export interface MediaItem {
  id: number;
  file_uuid: string;
  album_id: number;
  file_name: string;
  title: string | null;
  description: string | null;
  file_type: "photo" | "video";
  mime_type: string;
  file_size: number;
  has_thumbnail: boolean;
  status: string;
  created_at: string;
}

export type DownloadJobStatus = "queued" | "preparing" | "processing" | "completed" | "failed" | "expired" | "cancelled";

// Mirrors the backend's DownloadJobResponse exactly - shared by both the
// admin and client ZIP-download UIs since they're served by the same
// download_job_to_response() presenter, just reached via different auth.
export interface DownloadJob {
  id: number;
  status: DownloadJobStatus;
  total_files: number;
  completed_files: number;
  total_bytes: number;
  completed_bytes: number;
  error_message: string | null;
  has_password: boolean;
  created_at: string;
  completed_at: string | null;
  expires_at: string | null;
}

// Thrown by request() on any API error. A plain `instanceof Error` check
// still works everywhere existing code already does `err instanceof Error`,
// but callers that need to branch on a specific failure (e.g. "this album
// has expired" vs "not authenticated") can check `.code` instead of
// string-matching the human-readable message.
export class ApiRequestError extends Error {
  code: string;
  status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "ApiRequestError";
    this.code = code;
    this.status = status;
  }
}

// Thrown (instead of ApiRequestError) specifically when the admin session
// was rejected and we're bouncing to /admin/login. Kept as a distinct,
// silent class so components don't need a try/catch just to avoid
// rendering a scary error toast in the instant before the redirect fires.
export class SessionExpiredError extends Error {
  constructor() {
    super("Session expired.");
    this.name = "SessionExpiredError";
  }
}

const ADMIN_LOGIN_PATH = "/admin/login";

// Only auto-redirect for admin routes. The client gallery has its own
// per-galleryId login gate (password modal, not a global /login page), so
// a 401 from a client-facing call must NOT bounce the visitor into the
// admin login screen - it should just surface as a normal ApiRequestError
// for that UI to handle itself.
function isAdminContext(): boolean {
  return window.location.pathname.startsWith("/admin");
}

let redirectingToLogin = false;

function redirectToLogin() {
  if (redirectingToLogin) return; // avoid stacking redirects if several
  // requests 401 in the same tick (e.g. a page firing 3 parallel fetches)
  redirectingToLogin = true;

  if (window.location.pathname !== ADMIN_LOGIN_PATH) {
    const returnTo = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.assign(`${ADMIN_LOGIN_PATH}?redirect=${returnTo}`);
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE_URL}/api${path}`, {
    ...options,
    credentials: "include", // send/receive the HttpOnly session cookie
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  // A 401 mid-session (cookie expired, session revoked, server restarted
  // and dropped in-memory state, etc.) means every subsequent render is
  // working with stale/undefined data anyway - redirecting immediately is
  // safer than letting the calling component try to handle it locally.
  if (res.status === 401 && isAdminContext()) {
    redirectToLogin();
    throw new SessionExpiredError();
  }

  // Not every endpoint returns a body - a 204 No Content, or a 200/201
  // with nothing written, both have an empty response text. Calling
  // res.json() unconditionally on either throws "Unexpected end of JSON
  // input" from deep inside the parser, which is confusing to debug and
  // gives callers no usable error shape. Read as text first and only
  // parse if there's actually something there.
  const rawText = await res.text();
  let body: ApiResponse<T>;

  if (rawText.length === 0) {
    if (res.ok) {
      // Empty-but-successful (e.g. 204): treat as success with no data
      // rather than throwing, so callers that don't care about a return
      // value (verify-password, logout, etc.) don't need special-case
      // handling.
      return undefined as T;
    }
    // Empty AND an error status (e.g. a proxy/timeout returning a bare
    // 502 with no body) - we don't have a code/message from the server,
    // so synthesize one rather than crashing on JSON.parse("").
    throw new ApiRequestError("EMPTY_ERROR_RESPONSE", `Request failed with status ${res.status}.`, res.status);
  }

  try {
    body = JSON.parse(rawText) as ApiResponse<T>;
  } catch {
    throw new ApiRequestError("INVALID_JSON_RESPONSE", "The server returned an unreadable response.", res.status);
  }

  if (!res.ok || !body.success) {
    throw new ApiRequestError(body.error?.code ?? "UNKNOWN_ERROR", body.error?.message ?? "Something went wrong.", res.status);
  }

  return body.data as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, payload?: unknown) =>
    request<T>(path, { method: "POST", body: payload ? JSON.stringify(payload) : undefined }),
  put: <T>(path: string, payload?: unknown) =>
    request<T>(path, { method: "PUT", body: payload ? JSON.stringify(payload) : undefined }),
  patch: <T>(path: string, payload?: unknown) =>
    request<T>(path, { method: "PATCH", body: payload ? JSON.stringify(payload) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};