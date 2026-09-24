import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to this project's FastAPI backend on :8004.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5176,
    proxy: { "/api": { target: "http://127.0.0.1:8004", changeOrigin: true } },
  },
});
