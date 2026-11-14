import { Link } from "react-router-dom";

export default function SuperAdminNotFound() {
  return (
    <div className="sa-card">
      <h1>Page not found</h1>
      <p className="sa-muted">That page does not exist in the platform console.</p>
      <p>
        <Link to="/super-admin/dashboard" className="sa-btn sa-btn--dark">
          Back to dashboard
        </Link>
      </p>
    </div>
  );
}
