import { ReactNode, useState } from "react";
import Sidebar from "./Sidebar";
import StudioBrandMark from "./StudioBrandMark";

export default function AdminLayout({ children }: { children: ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="admin-shell">
      <div className="admin-topbar">
        <StudioBrandMark variant="topbar" />
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
