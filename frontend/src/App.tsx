import { Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import AdminLogin from "./pages/AdminLogin";
import AdminDashboard from "./pages/AdminDashboard";
import Activity from "./pages/Activity";
import Clients from "./pages/Clients";
import Downloads from "./pages/Downloads";
import Albums from "./pages/Albums";
import AlbumMedia from "./pages/AlbumMedia";

import BookView from "./pages/BookView";

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

        {/* Book View - the client-facing page-turning reader for one album.
            Gated on the album's own book_view_enabled flag, which the page
            re-checks on entry, so this route is only ever useful once an
            admin has switched the feature on for that album. */}
        <Route path="/gallery/:galleryId/view/:albumId/book" element={<BookView />} />
        <Route path="/gallery/:galleryId" element={<ClientLogin />} />
        <Route path="/gallery/:galleryId/view" element={<Gallery />} />
        <Route path="/gallery/:galleryId/view/:albumId" element={<AlbumView />} />
        <Route path="/gallery/:galleryId/wishlist" element={<Wishlist />} />

        <Route path="*" element={<NotFound />} />
      </Routes>
      <GlobalUploadBadge />
    </UploadProvider>
  );
}