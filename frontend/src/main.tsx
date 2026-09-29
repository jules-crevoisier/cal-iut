import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
// Polices embarquées (refonte du 29/09/2026, direction « Lumière / Nuit ») :
// Geist et Geist Mono, identiques sur tous les postes et servies par
// l'application elle-même — aucun appel à un service externe. Jeu latin
// seulement.
import "@fontsource/geist-sans/latin-400.css";
import "@fontsource/geist-sans/latin-500.css";
import "@fontsource/geist-sans/latin-600.css";
import "@fontsource/geist-sans/latin-700.css";
import "@fontsource/geist-mono/latin-400.css";
import "@fontsource/geist-mono/latin-500.css";
import "./styles/app.css";
import { appliquerTheme, lireTheme } from "./utils/theme";

// Avant le premier rendu : pas de flash de l'autre thème.
appliquerTheme(lireTheme());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* Dernier filet : `App.tsx` en pose déjà une autour du contenu, celle-ci
        ne sert que si la navigation elle-même plante. */}
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
