import { useEffect, useState } from "react";

/**
 * Écran étroit (téléphone) : la semaine se lit alors jour par jour au lieu
 * d'une grille des 5 jours (retour utilisateur — même seuil que la page
 * HTML/JS historique). `matchMedia` est optionnel par défense : son absence
 * ne doit désactiver que ce confort, jamais faire planter l'app.
 */
const QUERY = "(max-width: 760px)";

export function useNarrowScreen(): boolean {
  const [narrow, setNarrow] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(QUERY).matches
      : false,
  );

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(QUERY);
    const onChange = () => setNarrow(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  return narrow;
}
