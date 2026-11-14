import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { authService } from "../../services/auth";
import { assetUrl } from "../../services/api";
import PoweredBy from "../PoweredBy";
import { IconChevronDown, IconDashboard, IconKey, IconLog, IconLogout, IconSettings, IconStorage, IconStudios } from "./Icons";
import { useCurrentUser } from "./RequireSuperAdmin";
import { ToastProvider } from "./Toast";

// Grouped like the studio admin sidebar (a small caption over each group).
const SECTIONS = [
  { items: [{ to: "/super-admin/dashboard", label: "Dashboard", icon: <IconDashboard />, end: true }] },
  {
    category: "MANAGEMENT",
    items: [
      { to: "/super-admin/studios", label: "Studios", icon: <IconStudios />, end: false },
      { to: "/super-admin/logins", label: "Studio logins", icon: <IconKey />, end: false },
    ],
  },
  { category: "OPERATIONS", items: [{ to: "/super-admin/storage", label: "Storage", icon: <IconStorage />, end: false }] },
  { category: "INSIGHTS", items: [{ to: "/super-admin/audit-logs", label: "Audit log", icon: <IconLog />, end: false }] },
  { category: "SYSTEM", items: [{ to: "/super-admin/settings", label: "Settings", icon: <IconSettings />, end: false }] },
];

export default function SuperAdminLayout() {
  const [open, setOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const user = useCurrentUser();

  async function logout() {
    try {
      await authService.logout();
    } finally {
      navigate("/admin/login", { replace: true });
    }
  }

  // The profile menu closes on a click elsewhere, on Escape, and when you navigate.
  useEffect(() => setMenuOpen(false), [location.pathname]);
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  // The company name and logo set on the Settings page; "Platform" until then.
  const brand = <Brand name={user?.company_name} logoUrl={user?.logo_url} />;

  const initial = (user?.name ?? "S").trim().charAt(0).toUpperCase() || "S";

  return (
    <ToastProvider>
    <div className="sa">
    <div className="sa-shell">
      <header className="sa-topbar">
        <div className="sa-topbar__brand">{brand}</div>
        <button className="sa-topbar__toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-label="Toggle navigation">
          {open ? "✕" : "☰"}
        </button>
      </header>

      <aside className={"sa-sidebar" + (open ? " sa-sidebar--open" : "")}>
        <div className="sa-brand">{brand}</div>
        <div className="sa-sidebar__scroll">
          <nav className="sa-sidebar__nav">
            {SECTIONS.map((section, i) => (
              <div key={i} className="sa-sidebar__group">
                {section.category && <div className="sa-sidebar__category">{section.category}</div>}
                {section.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) => "sa-sidebar__link" + (isActive ? " sa-sidebar__link--active" : "")}
                    onClick={() => setOpen(false)}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </NavLink>
                ))}
              </div>
            ))}
          </nav>
        </div>
        <div className="sa-sidebar__footer">
          <button className="sa-sidebar__logout" onClick={logout}>
            <IconLogout />
            <span>Sign out</span>
          </button>
          <div className="sa-sidebar__powered">
            <PoweredBy />
          </div>
        </div>
      </aside>

      <main className="sa-main">
        <div className="sa-header-topbar">
          <div className="sa-profile" ref={menuRef}>
            <button
              type="button"
              className="sa-profile__chip"
              onClick={() => setMenuOpen((v) => !v)}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-label="Account menu"
            >
              <Avatar initial={initial} logoUrl={user?.logo_url} />
              <span className="sa-profile__name">{user?.name ?? "Super admin"}</span>
              <IconChevronDown />
            </button>
            {menuOpen && (
              <div className="sa-profile__menu" role="menu">
                <div className="sa-profile__who">
                  <div className="sa-profile__who-name">{user?.name ?? "Super admin"}</div>
                  <div className="sa-profile__who-role">Super admin</div>
                </div>
                <hr className="sa-profile__divider" />
                <Link to="/super-admin/settings" className="sa-profile__link" role="menuitem">
                  Account settings
                </Link>
                <Link to="/super-admin/audit-logs" className="sa-profile__link" role="menuitem">
                  Audit log
                </Link>
                <hr className="sa-profile__divider" />
                <button type="button" className="sa-profile__link sa-profile__link--danger" role="menuitem" onClick={logout}>
                  Log out
                </button>
              </div>
            )}
          </div>
        </div>
        <Outlet />
      </main>
    </div>
    </div>
    </ToastProvider>
  );
}

// With a logo: the picture, and the company name under it. Without one: the name in the script face.
function Brand({ name, logoUrl }: { name?: string | null; logoUrl?: string | null }) {
  const [failed, setFailed] = useState<string | null>(null);
  const src = assetUrl(logoUrl ?? null);
  const company = (name ?? "").trim();
  if (src && failed !== src) {
    return (
      <>
        <img className="sa-brand__logo" src={src} alt={company || "Platform"} onError={() => setFailed(src)} />
        <span className="sa-brand__sub">{company || "CONSOLE"}</span>
      </>
    );
  }
  return (
    <>
      <span className="sa-brand__script">{company || "Platform"}</span>
      <span className="sa-brand__sub">CONSOLE</span>
    </>
  );
}

// The profile chip's round avatar: the company logo when there is one, otherwise the user's initial.
function Avatar({ initial, logoUrl }: { initial: string; logoUrl?: string | null }) {
  const [failed, setFailed] = useState<string | null>(null);
  const src = assetUrl(logoUrl ?? null);
  if (src && failed !== src) {
    return (
      <span className="sa-profile__avatar sa-profile__avatar--logo">
        <img src={src} alt="" onError={() => setFailed(src)} />
      </span>
    );
  }
  return <span className="sa-profile__avatar">{initial}</span>;
}
