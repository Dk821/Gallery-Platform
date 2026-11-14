import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { authService, CurrentUser, isSuperAdmin } from "../../services/auth";

const UserContext = createContext<CurrentUser | null>(null);
export const useCurrentUser = () => useContext(UserContext);

// Lets a page re-read the signed-in user after it changed (e.g. the name edited on Settings), so the
// top bar shows the new name without a reload.
const RefreshUserContext = createContext<() => void>(() => undefined);
export const useRefreshCurrentUser = () => useContext(RefreshUserContext);

// Route gate for the whole console: confirms with GET /auth/me that the
// session belongs to a SUPER ADMIN before rendering anything. A studio admin
// (or a gallery client) with a valid cookie is treated as unauthorized - and
// the backend enforces the same rule on every /api/super-admin route, so this
// is a UX gate, not the security boundary.
export default function RequireSuperAdmin() {
  const location = useLocation();
  const [state, setState] = useState<{ status: "checking" | "ok" | "denied"; user: CurrentUser | null }>({
    status: "checking",
    user: null,
  });

  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    let active = true;
    authService
      .me()
      .then((user) => {
        if (!active) return;
        setState(isSuperAdmin(user) ? { status: "ok", user } : { status: "denied", user });
      })
      .catch(() => active && setState({ status: "denied", user: null }));
    return () => {
      active = false;
    };
  }, [reloadKey]);
  const refreshUser = useCallback(() => setReloadKey((k) => k + 1), []);

  if (state.status === "checking") return <div className="auth-page" aria-busy="true" />;
  if (state.status === "denied") {
    // A signed-in studio admin simply belongs in their own area; anyone else
    // (no session, a gallery client) goes to the one shared sign-in page.
    if (state.user?.user_type === "admin") return <Navigate to="/admin/dashboard" replace />;
    const returnTo = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/admin/login?redirect=${returnTo}`} replace />;
  }
  return (
    <UserContext.Provider value={state.user}>
      <RefreshUserContext.Provider value={refreshUser}>
        <Outlet />
      </RefreshUserContext.Provider>
    </UserContext.Provider>
  );
}
