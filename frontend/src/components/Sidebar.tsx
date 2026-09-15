import { Link, useLocation, useNavigate } from "react-router-dom";
import { authService } from "../services/auth";

interface NavItem {
  id: string;
  to: string;
  label: string;
  icon: JSX.Element;
}

interface NavSection {
  category?: string;
  items: NavItem[];
}

const navSections: NavSection[] = [
  {
    items: [
      {
        id: "dashboard",
        to: "/admin/dashboard",
        label: "Dashboard",
        icon: (
          <svg className="admin-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path d="M3 10.5L12 3l9 7.5v9.75a1.5 1.5 0 01-1.5 1.5h-4.5v-6h-6v6H4.5A1.5 1.5 0 013 20.25V10.5z" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ),
      },
    ],
  },
  {
    category: "MANAGEMENT",
    items: [
      {
        id: "clients",
        to: "/admin/clients",
        label: "Clients",
        icon: (
          <svg className="admin-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2" strokeWidth="1.6" strokeLinecap="round" />
            <circle cx="9" cy="7" r="4" strokeWidth="1.6" />
            <path d="M22 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        ),
      },
      {
        id: "albums",
        to: "/admin/albums",
        label: "Albums",
        icon: (
          <svg className="admin-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <rect x="3" y="3" width="18" height="18" rx="2.5" strokeWidth="1.6" />
            <circle cx="8.5" cy="8.5" r="1.5" fill="currentColor" />
            <path d="M21 15l-5-5L5 21" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ),
      },
      {
        id: "media",
        to: "/admin/albums?filter=media",
        label: "Media",
        icon: (
          <svg className="admin-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <rect x="3" y="3" width="18" height="18" rx="2.5" strokeWidth="1.6" />
            <path d="M3 9h18M9 21V9" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        ),
      },
    ],
  },
  {
    category: "OPERATIONS",
    items: [
      {
        id: "uploads",
        to: "/admin/uploads",
        label: "Uploads",
        icon: (
          <svg className="admin-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M12 12v9M8 16l4-4 4 4" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ),
      },
      {
        id: "downloads",
        to: "/admin/downloads",
        label: "Downloads",
        icon: (
          <svg className="admin-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path d="M20 14v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5M12 3v12m-4-4l4 4 4-4" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ),
      },
    ],
  },
  {
    category: "INSIGHTS",
    items: [
      {
        id: "activity",
        to: "/admin/activity",
        label: "Activity",
        icon: (
          <svg className="admin-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <circle cx="12" cy="12" r="9" strokeWidth="1.6" />
            <path d="M12 7v5l3 3" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ),
      },
      {
        id: "storage",
        to: "/admin/storage",
        label: "Storage",
        icon: (
          <svg className="admin-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <ellipse cx="12" cy="5" rx="9" ry="3" strokeWidth="1.6" />
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" strokeWidth="1.6" />
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" strokeWidth="1.6" />
          </svg>
        ),
      },
    ],
  },
  {
    category: "SYSTEM",
    items: [
      {
        id: "settings",
        to: "/admin/settings",
        label: "Settings",
        icon: (
          <svg className="admin-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <circle cx="12" cy="12" r="3" strokeWidth="1.6" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" strokeWidth="1.6" />
          </svg>
        ),
      },
    ],
  },
];

interface SidebarProps {
  open?: boolean;
  onNavigate?: () => void;
}

export default function Sidebar({ open, onNavigate }: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();

  function isItemActive(item: NavItem): boolean {
    const currentPath = location.pathname;
    const currentHash = location.hash;
    const currentSearch = location.search;

    // 1. Dashboard: active ONLY when directly on /admin/dashboard without any hash anchor
    if (item.id === "dashboard") {
      return currentPath === "/admin/dashboard" && (!currentHash || currentHash === "");
    }

    // 2. Clients: active on /admin/clients
    if (item.id === "clients") {
      return currentPath.startsWith("/admin/clients");
    }

    // 3. Albums: active on /admin/albums when not specifically filtering for media
    if (item.id === "albums") {
      return currentPath === "/admin/albums" && !currentSearch.includes("filter=media");
    }

    // 4. Media: active on /admin/albums/:albumId or when explicitly browsing media
    if (item.id === "media") {
      return (
        currentPath.startsWith("/admin/albums/") ||
        (currentPath === "/admin/albums" && currentSearch.includes("filter=media"))
      );
    }

    // 5. Uploads: active on /admin/uploads
    if (item.id === "uploads") {
      return currentPath.startsWith("/admin/uploads");
    }

    // 6. Downloads: active on /admin/downloads (dedicated page)
    if (item.id === "downloads") {
      return currentPath.startsWith("/admin/downloads");
    }

    // 7. Activity: active on /admin/activity (dedicated page)
    if (item.id === "activity") {
      return currentPath.startsWith("/admin/activity");
    }

    // 8. Storage: active on /admin/storage
    if (item.id === "storage") {
      return currentPath.startsWith("/admin/storage");
    }

    // 9. Settings: active on /admin/settings
    if (item.id === "settings") {
      return currentPath.startsWith("/admin/settings");
    }

    return false;
  }

  async function handleLogout() {
    await authService.logout();
    navigate("/admin/login");
  }

  return (
    <aside className={"admin-sidebar" + (open ? " admin-sidebar--open" : "")}>
      <div className="admin-sidebar__brand">
        <span className="admin-sidebar__logo-script">sam</span>
        <span className="admin-sidebar__logo-sub">PHOTOGRAPHY</span>
      </div>

      <div className="admin-sidebar__scroll-area">
        <nav className="admin-sidebar__nav">
          {navSections.map((sec, sIdx) => (
            <div key={sIdx} className="admin-sidebar__group">
              {sec.category && (
                <div className="admin-sidebar__category">{sec.category}</div>
              )}
              {sec.items.map((item) => {
                const active = isItemActive(item);
                return (
                  <Link
                    key={item.id}
                    to={item.to}
                    onClick={() => {
                      if (onNavigate) onNavigate();
                      // If navigating to a hash anchor on the same page, trigger scroll directly
                      if (item.to.includes("#")) {
                        const hash = item.to.split("#")[1];
                        const target = document.getElementById(hash);
                        if (target) {
                          target.scrollIntoView({ behavior: "smooth", block: "start" });
                        }
                      }
                    }}
                    className={
                      "admin-sidebar__link" + (active ? " admin-sidebar__link--active" : "")
                    }
                  >
                    <span className="admin-sidebar__link-icon">{item.icon}</span>
                    <span className="admin-sidebar__link-text">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
      </div>

      <div className="admin-sidebar__footer">
        
        <button className="admin-sidebar__logout-row" onClick={handleLogout}>
          <svg className="admin-logout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.6" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l3 3m0 0l-3 3m3-3H3" />
          </svg>
          <span>Logout</span>
        </button>
      </div>
    </aside>
  );
}
