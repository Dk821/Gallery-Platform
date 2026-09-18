import { memo } from "react";
import { Link, useLocation } from "react-router-dom";
import { useUploads } from "../contexts/Uploadcontext";

// Floating pill visible on every admin page EXCEPT Uploads itself (which
// already shows the full panel) whenever there's an active batch - this is
// the actual visible proof that navigating away from Uploads didn't lose
// the transfer. Clicking it goes back to the Uploads page to see details.
export default memo(function GlobalUploadBadge() {
  const { summary } = useUploads();
  const location = useLocation();

  if (summary.total === 0) return null;
  if (location.pathname === "/admin/uploads") return null;
  if (!location.pathname.startsWith("/admin")) return null;

  const inProgress = summary.active > 0 || summary.total - summary.completed - summary.failed - summary.cancelled > 0;
  if (!inProgress) return null;

  return (
    <Link to="/admin/uploads" className="global-upload-badge" title="Go to Uploads">
      <span className="global-upload-badge__spinner" aria-hidden="true" />
      <span>
        Uploading {summary.total - summary.completed} {summary.total - summary.completed === 1 ? "file" : "files"} ·{" "}
        {summary.overallPercent}%
      </span>
    </Link>
  );
});