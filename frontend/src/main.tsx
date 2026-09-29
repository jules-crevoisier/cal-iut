import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
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
