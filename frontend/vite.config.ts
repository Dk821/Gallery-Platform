import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        // Kept for the fallback case where VITE_API_BASE_URL is unset,
        // matching the production backend (never localhost).
        target: "https://api.madgen.space",
        changeOrigin: true,
      },
    },
  },
});