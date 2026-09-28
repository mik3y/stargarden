import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The program serves the built app itself (src/stargarden/web.py serves
// web/dist). For development, `bun start` runs vite on :7711 and proxies the
// API and the WebSocket to a running `uv run stargarden` on :7710, so the app
// hot-reloads against the live program.
const STARGARDEN = "http://127.0.0.1:7710";

export default defineConfig({
  server: {
    port: 7711,
    strictPort: true,
    host: true,
    proxy: {
      "/api": STARGARDEN,
      "/ws": { target: STARGARDEN, ws: true },
    },
  },
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "src"),
    },
  },
  plugins: [react()],
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
