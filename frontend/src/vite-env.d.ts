/// <reference types="vite/client" />

// Declares the shape of import.meta.env for this app's own VITE_-prefixed
// variables (see frontend/.env.example). Vite already types the built-in
// ones (MODE, DEV, PROD, ...) via the "vite/client" reference above - this
// just extends that with the custom ones this app reads.
interface ImportMetaEnv {
  /**
   * Base URL the frontend sends API requests to, e.g.
   * "https://api.yourdomain.com". Leave unset for the normal case (frontend
   * and backend on the same origin, or Vite's dev proxy) - every request
   * then falls back to a plain relative `/api/...` path, exactly as before
   * this variable existed.
   */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
