import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Консоль раздаётся из /console/ (app.mount в src/main.py).
  // Без base бандл сошлётся на /assets/... и отдаст 404.
  base: "/console/",
  server: {
    port: 5173,
    proxy: {
      // В dev браузер считает всё same-origin — CORS не задействован.
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
