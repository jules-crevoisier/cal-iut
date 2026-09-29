import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
// Polices embarquées (refonte du 29/09/2026) : identiques sur tous les postes,
// servies par l'application elle-même — aucun appel à un service externe.
// Jeu latin seulement, quatre graisses : ~120 Ko en tout.
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-sans/latin-700.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-600.css";
import "./styles/app.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* Dernier filet : `App.tsx` en pose déjà une autour du contenu, celle-ci
        ne sert que si la navigation elle-même plante. */}
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
