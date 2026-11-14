import { Fragment } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import AdminLogin from "./pages/AdminLogin";
import AdminDashboard from "./pages/AdminDashboard";
import Activity from "./pages/Activity";
import Clients from "./pages/Clients";
import Downloads from "./pages/Downloads";
import Albums from "./pages/Albums";
import AlbumMedia from "./pages/AlbumMedia";

import BookView from "./pages/BookView";
import GalleryUrlGate from "./components/GalleryUrlGate";

import Uploads from "./pages/Uploads";
import Storage from "./pages/Storage";
import ClientLogin from "./pages/ClientLogin";
import Gallery from "./pages/Gallery";
import AlbumView from "./pages/AlbumView";
import Wishlist from "./pages/Wishlist";
import Settings from "./pages/Settings";
import NotFound from "./pages/NotFound";
import RequireAdmin from "./components/RequireAdmin";
import { UploadProvider } from "./contexts/Uploadcontext"
import GlobalUploadBadge from "./components/Globaluploadbadge";
import RequireSuperAdmin from "./components/superadmin/RequireSuperAdmin";
import SuperAdminLayout from "./components/superadmin/SuperAdminLayout";
import SuperAdminDashboard from "./pages/superadmin/Dashboard";
import SuperAdminStudios from "./pages/superadmin/Studios";
import SuperAdminStudioDetail from "./pages/superadmin/StudioDetail";
import SuperAdminAuditLogs from "./pages/superadmin/AuditLogs";
import SuperAdminStorage from "./pages/superadmin/Storage";
import SuperAdminStudioLogins from "./pages/superadmin/StudioLogins";
import SuperAdminSettings from "./pages/superadmin/Settings";
import SuperAdminNotFound from "./pages/superadmin/SuperAdminNotFound";

export default function App() {
  return (
    // Mounted here, above <Routes>, so it's created ONCE for the life of
    // the app and never torn down by client-side navigation between
    // pages - that's what lets an upload keep running (and stay visible
    // via GlobalUploadBadge) while the admin navigates to Clients,
    // Albums, etc. and back. See contexts/UploadContext.tsx for exactly
    // what this does and does not survive (a real page reload or tab
    // close still ends any in-flight direct-to-Drive transfer).
    <UploadProvider>
      <Routes>
        {/* The front door, and the only route a visitor lands on: it offers
            the two ways in (a client gallery link, or the studio sign-in)
            instead of guessing one of them for them. */}
        <Route path="/" element={<Home />} />

        <Route path="/admin/login" element={<AdminLogin />} />

        {/* Every other admin page sits behind RequireAdmin, which confirms a
            real admin session with GET /auth/me before rendering. This is
            what stops an unauthenticated visitor reaching the dashboard -
            e.g. via the 404 page's "Back to dashboard" button, which
            navigates client-side and so never triggers a fresh page load. */}
        <Route element={<RequireAdmin />}>
          <Route path="/admin/dashboard" element={<AdminDashboard />} />
          <Route path="/admin/activity" element={<Activity />} />
          <Route path="/admin/clients" element={<Clients />} />
          <Route path="/admin/albums" element={<Albums />} />
          <Route path="/admin/albums/:albumId" element={<AlbumMedia />} />
          <Route path="/admin/uploads" element={<Uploads />} />
          <Route path="/admin/downloads" element={<Downloads />} />
          <Route path="/admin/storage" element={<Storage />} />
          <Route path="/admin/settings" element={<Settings />} />
        </Route>

        {/* Platform console for the super admin. Same app, same sign-in page
            (/admin/login) and same session cookie as the studio admin area;
            RequireSuperAdmin only lets a super_admin through, and the API
            enforces the same rule on every /api/super-admin route. */}
        <Route path="/super-admin" element={<RequireSuperAdmin />}>
          <Route element={<SuperAdminLayout />}>
            <Route index element={<Navigate to="/super-admin/dashboard" replace />} />
            <Route path="dashboard" element={<SuperAdminDashboard />} />
            <Route path="studios" element={<SuperAdminStudios />} />
            <Route path="studios/:studioId" element={<SuperAdminStudioDetail />} />
            <Route path="logins" element={<SuperAdminStudioLogins />} />
            <Route path="storage" element={<SuperAdminStorage />} />
            <Route path="audit-logs" element={<SuperAdminAuditLogs />} />
            <Route path="settings" element={<SuperAdminSettings />} />
            <Route path="*" element={<SuperAdminNotFound />} />
          </Route>
        </Route>

        {/* Client galleries live at /<studio name>/gallery/<link id>. The older /gallery/<link id> form is
            kept so links already shared keep working: GalleryUrlGate sends each one to the studio's
            address (and corrects a wrong studio name). A gallery whose studio has no name slug stays
            on the older form. */}
        {["/:studioSlug/gallery/:galleryId", "/gallery/:galleryId"].map((base) => (
          <Fragment key={base}>
            {/* Book View - the client-facing page-turning reader for one album. Gated on the album's own
                book_view_enabled flag, which the page re-checks on entry. */}
            <Route path={`${base}/view/:albumId/book`} element={<GalleryUrlGate><BookView /></GalleryUrlGate>} />
            <Route path={base} element={<GalleryUrlGate><ClientLogin /></GalleryUrlGate>} />
            <Route path={`${base}/view`} element={<GalleryUrlGate><Gallery /></GalleryUrlGate>} />
            <Route path={`${base}/view/:albumId`} element={<GalleryUrlGate><AlbumView /></GalleryUrlGate>} />
            <Route path={`${base}/wishlist`} element={<GalleryUrlGate><Wishlist /></GalleryUrlGate>} />
          </Fragment>
        ))}

        <Route path="*" element={<NotFound />} />
      </Routes>
      <GlobalUploadBadge />
    </UploadProvider>
  );
}