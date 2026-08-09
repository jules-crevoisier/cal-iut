import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/app/",
  server: {
    port: 5173,
    proxy: {
      "/health": "http://127.0.0.1:8000",
      "/meta": "http://127.0.0.1:8000",
      "/ingest": "http://127.0.0.1:8000",
      "/solve": "http://127.0.0.1:8000",
      "/timetable": "http://127.0.0.1:8000",
      "/sessions": "http://127.0.0.1:8000",
      "/placements": "http://127.0.0.1:8000",
      "/export": "http://127.0.0.1:8000",
      "/diff": "http://127.0.0.1:8000",
      "/feedback": "http://127.0.0.1:8000",
      "/weights": "http://127.0.0.1:8000",
    },
  },
});
