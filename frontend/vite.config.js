import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// API base comes from VITE_API_BASE (see .env), default localhost:8000.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
