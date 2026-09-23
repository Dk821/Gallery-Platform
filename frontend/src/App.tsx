import { Navigate, Route, Routes } from "react-router-dom";
import AdminLogin from "./pages/AdminLogin";
import AdminDashboard from "./pages/AdminDashboard";
import Activity from "./pages/Activity";
import Clients from "./pages/Clients";
import Downloads from "./pages/Downloads";
import Albums from "./pages/Albums";
import AlbumMedia from "./pages/AlbumMedia";
import Uploads from "./pages/Uploads";
import Storage from "./pages/Storage";
import ClientLogin from "./pages/ClientLogin";
import Gallery from "./pages/Gallery";
import AlbumView from "./pages/AlbumView";
import Wishlist from "./pages/Wishlist";
import Settings from "./pages/Settings";
import NotFound from "./pages/NotFound";
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
        <Route path="/" element={<Navigate to="/admin/login" replace />} />

        <Route path="/admin/login" element={<AdminLogin />} />
        <Route path="/admin/dashboard" element={<AdminDashboard />} />
        <Route path="/admin/activity" element={<Activity />} />
        <Route path="/admin/clients" element={<Clients />} />
        <Route path="/admin/albums" element={<Albums />} />
        <Route path="/admin/albums/:albumId" element={<AlbumMedia />} />
        <Route path="/admin/uploads" element={<Uploads />} />
        <Route path="/admin/downloads" element={<Downloads />} />
        <Route path="/admin/storage" element={<Storage />} />
        <Route path="/admin/settings" element={<Settings />} />

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