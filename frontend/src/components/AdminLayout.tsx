import { ReactNode, useState } from "react";
import Sidebar from "./Sidebar";

export default function AdminLayout({ children }: { children: ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="admin-shell">
      <div className="admin-topbar">
        <div className="admin-topbar__brand">
          <span className="admin-topbar__logo-script">Love Story</span>
          <span className="admin-topbar__logo-sub">PHOTOGRAPHY</span>
        </div>
        <button
          className="admin-topbar__toggle"
          onClick={() => setMobileNavOpen((v) => !v)}
          aria-expanded={mobileNavOpen}
          aria-label="Toggle navigation menu"
        >
          {mobileNavOpen ? "✕" : "☰"}
        </button>
      </div>
      <Sidebar open={mobileNavOpen} onNavigate={() => setMobileNavOpen(false)} />
      <main className="admin-main">{children}</main>
    </div>
  );
}
