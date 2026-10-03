import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { runsPlugin } from "./server/runs";

// `npm run dev` / `npm run preview` both serve /api/runs from ../.manifest/runs (override: MANIFEST_RUNS_DIR).
export default defineConfig({
  plugins: [react(), runsPlugin()],
  server: { port: 5173, host: "127.0.0.1" },
  preview: { port: 4173, host: "127.0.0.1" },
  build: { target: "es2022", assetsInlineLimit: 0, chunkSizeWarningLimit: 900 },
});
