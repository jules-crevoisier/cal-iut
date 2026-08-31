import { useEffect, useRef, useState } from "react";

import { copyToClipboard } from "../utils/clipboard";

interface CopyButtonProps {
  text: string | (() => string);
  idleLabel: string;
  copiedLabel?: string;
  title?: string;
  className?: string;
}

/** Bouton qui copie puis affiche un état visible (texte + couleur), le même
 * partout : annuaire, barre de partage, lien perso. Sans ça, un clic réussi
 * ne changeait rien à l'écran — on ne savait pas si ça avait marché. */
export function CopyButton({
  text,
  idleLabel,
  copiedLabel = "Copié ✓",
  title,
  className = "btn btn--ghost btn--sm",
}: CopyButtonProps) {
  const [etat, setEtat] = useState<"repos" | "ok" | "echec">("repos");
  const timer = useRef<number>(0);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copier = async () => {
    const valeur = typeof text === "function" ? text() : text;
    const ok = await copyToClipboard(valeur);
    window.clearTimeout(timer.current);
    setEtat(ok ? "ok" : "echec");
    timer.current = window.setTimeout(() => setEtat("repos"), ok ? 1400 : 1800);
  };

  const classe = `${className}${etat === "ok" ? " is-copied" : ""}${etat === "echec" ? " is-copy-failed" : ""}`;
  const libelle = etat === "ok" ? copiedLabel : etat === "echec" ? "Échec copie" : idleLabel;

  return (
    <button type="button" className={classe} onClick={() => void copier()} title={title} aria-live="polite">
      {libelle}
    </button>
  );
}
