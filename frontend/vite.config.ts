import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Racine de l'app depuis le 11/08/2026 (retour utilisateur : « je veux
  // react en local ») — auparavant "/app/", quand React n'était qu'un
  // frontend secondaire monté sous ce préfixe par `api/main.py`. Doit rester
  // cohérent avec `app.mount("/", ...)` côté backend, sinon les assets buildés
  // référencent un préfixe que le serveur ne sert plus.
  base: "/",
  server: {
    port: 5173,
    proxy: {
      "/health": "http://127.0.0.1:8000",
      "/mcp": "http://127.0.0.1:8000",
      "/auth": "http://127.0.0.1:8000",
      "/meta": "http://127.0.0.1:8000",
      "/app-state": "http://127.0.0.1:8000",
      "/ingest": "http://127.0.0.1:8000",
      "/solve": "http://127.0.0.1:8000",
      "/regen": "http://127.0.0.1:8000",
      "/weeks": "http://127.0.0.1:8000",
      "/timetable": "http://127.0.0.1:8000",
      "/sessions": "http://127.0.0.1:8000",
      "/exceptions": "http://127.0.0.1:8000",
      "/placements": "http://127.0.0.1:8000",
      "/corrections": "http://127.0.0.1:8000",
      "/export": "http://127.0.0.1:8000",
      "/diff": "http://127.0.0.1:8000",
      "/feedback": "http://127.0.0.1:8000",
      "/weights": "http://127.0.0.1:8000",
      "/legacy": "http://127.0.0.1:8000",
      "/celcat": "http://127.0.0.1:8000",
      // Compléter une donnée manquante (`api/reference.py`).
      "/reference": "http://127.0.0.1:8000",
      // API v1 (`api/v1.py`) — `useRevision` sonde `/api/v1/version`.
      "/api": "http://127.0.0.1:8000",
      // Routes appelées par le front et absentes du proxy jusqu'au
      // 19/10/2026 : Vite répondait index.html (200) et le bandeau « Serveur
      // injoignable » s'affichait en local (Tâches, Comptes, Sauvegardes,
      // Trafic, doublons, notifications, mail, salles, calendrier).
      "/admin": "http://127.0.0.1:8000",
      "/taches": "http://127.0.0.1:8000",
      "/controles": "http://127.0.0.1:8000",
      "/sauvegardes": "http://127.0.0.1:8000",
      "/notifications": "http://127.0.0.1:8000",
      "/mail": "http://127.0.0.1:8000",
      "/rooms": "http://127.0.0.1:8000",
      "/calendrier": "http://127.0.0.1:8000",
      "/ics": "http://127.0.0.1:8000",
    },
  },
});
