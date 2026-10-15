import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: the API runs on :8000. Build output (dist/) is served by FastAPI, so one process serves everything.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000", "/agent": "http://localhost:8000" } },
});
