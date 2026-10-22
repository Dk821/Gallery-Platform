import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { authService } from "../services/auth";

// Route-level session gate for every /admin/* page (dashboard, clients,
// albums, etc.). Without this, the admin shell was only ever "protected"
// indirectly: a page's own API calls would 401 and api.ts would bounce to
// /admin/login a beat later. But any admin route that renders before those
// calls resolve - most visibly the 404 page's "Back to dashboard" button,
// which navigates client-side without a fresh page load - would still mount
// the dashboard for an unauthenticated visitor. This component asks the
// server who we are (GET /auth/me) FIRST and only renders the admin page
// once it confirms an admin session, redirecting to the login screen
// otherwise.
type Status = "checking" | "authorized" | "unauthorized";

export default function RequireAdmin() {
  const location = useLocation();
  const [status, setStatus] = useState<Status>("checking");

  // Checked once when the admin area is entered, not on every in-app
  // navigation between admin pages: this layout route stays mounted while
  // the admin moves around the dashboard, so re-running the check (and
  // re-showing the loader) on each click would only cause a needless flash.
  // A session that expires mid-use is still caught by api.ts's 401 handler.
  useEffect(() => {
    let active = true;

    authService
      .me()
      .then((user) => {
        if (!active) return;
        // me() resolves with null when no session cookie is present, and
        // with a client identity if a *gallery* session is what's active -
        // both must be treated as "not an admin".
        setStatus(user?.user_type === "admin" ? "authorized" : "unauthorized");
      })
      .catch(() => {
        // Network failure or an unexpected 401 (api.ts's own session-expired
        // handler) both mean we can't prove an admin session exists, so fail
        // closed rather than exposing the dashboard.
        if (active) setStatus("unauthorized");
      });

    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (status === "checking") {
    return <div className="auth-page" aria-busy="true" />;
  }

  if (status === "unauthorized") {
    const returnTo = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/admin/login?redirect=${returnTo}`} replace />;
  }

  return <Outlet />;
}
