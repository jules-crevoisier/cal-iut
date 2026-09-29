import { Fragment, useEffect, useRef, useState } from "react";
import { TriangleAlert } from "lucide-react";

import { registerConfirmListener, resolveConfirm, type ConfirmRequest } from "../utils/confirmDialog";
import "./ConfirmModal.css";

/**
 * Montée UNE fois dans App.tsx — remplace `window.confirm(...)` partout
 * (cf. utils/confirmDialog.ts pour le pourquoi).
 *
 * Refonte du 29/09/2026 :
 *   - le focus reste DANS la modale (Tab / Maj+Tab bouclent) et revient à
 *     l'élément qui l'a ouverte à la fermeture ;
 *   - Échap annule, sans fermer en même temps ce qu'il y a dessous ;
 *   - un message qui contient une liste (« • … » ou « - … » en début de
 *     ligne) est rendu comme une vraie liste : les confirmations qui
 *     énumèrent ce qu'elles vont toucher (suppressions Celcat) se lisent
 *     d'un coup d'œil ;
 *   - la variante « danger » colore aussi le titre, pas seulement le bouton.
 *
 * Le bouton Annuler garde le focus par défaut : Entrée sur une modale
 * ouverte par erreur ne confirme jamais rien.
 *
 * Refonte v2 (même jour, direction « Lumière / Nuit ») : en-tête, corps et
 * pied séparés, les boutons à droite dans un pied gris clair ; la variante
 * « danger » porte une petite marque rouge (icône) plutôt qu'un liseré.
 */

/** Paragraphes séparés par une ligne vide ; un paragraphe dont toutes les
 * lignes commencent par une puce devient une liste. */
function Message({ texte }: { texte: string }) {
  const paragraphes = texte.split(/\n\s*\n/).filter((p) => p.trim());
  return (
    <div className="confirmdlg-message" id="confirmmodal-message">
      {paragraphes.map((p, i) => {
        const lignes = p.split("\n").filter((l) => l.trim());
        const puce = /^\s*[•\-–]\s+/;
        if (lignes.length > 0 && lignes.every((l) => puce.test(l))) {
          return (
            <ul key={i} className="confirmdlg-liste">
              {lignes.map((l, j) => (
                <li key={j}>{l.replace(puce, "")}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={i}>
            {lignes.map((l, j) => (
              <Fragment key={j}>
                {j > 0 ? <br /> : null}
                {l}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}

const FOCUSABLES = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function ConfirmModal() {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);
  const boite = useRef<HTMLDivElement>(null);
  const annuler = useRef<HTMLButtonElement>(null);

  useEffect(() => registerConfirmListener(setRequest), []);

  useEffect(() => {
    if (!request) return;
    const avant = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    annuler.current?.focus();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        resolveConfirm(false);
        return;
      }
      if (e.key !== "Tab" || !boite.current) return;
      const elements = [...boite.current.querySelectorAll<HTMLElement>(FOCUSABLES)];
      if (elements.length === 0) return;
      const premier = elements[0];
      const dernier = elements[elements.length - 1];
      const actif = document.activeElement;
      if (e.shiftKey && (actif === premier || !boite.current.contains(actif))) {
        e.preventDefault();
        dernier.focus();
      } else if (!e.shiftKey && (actif === dernier || !boite.current.contains(actif))) {
        e.preventDefault();
        premier.focus();
      }
    };
    // Phase de capture : Échap ne doit pas atteindre une autre modale ou un
    // raccourci de la page restés dessous.
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      if (avant && document.contains(avant)) avant.focus();
    };
  }, [request]);

  if (!request) return null;
  const danger = request.variant === "danger";

  return (
    <div className="confirmmodal-overlay" role="presentation" onClick={() => resolveConfirm(false)}>
      <div
        ref={boite}
        className={`panel confirmmodal confirmdlg${danger ? " confirmdlg--danger" : ""}`}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirmmodal-titre"
        aria-describedby="confirmmodal-message"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="confirmdlg-tete">
          {danger && (
            <span className="confirmdlg-marque" aria-hidden="true">
              <TriangleAlert size={16} />
            </span>
          )}
          <h3 id="confirmmodal-titre" className="confirmdlg-titre">
            {request.title}
          </h3>
        </div>
        <Message texte={request.message} />
        <div className="confirmmodal-actions">
          <button ref={annuler} type="button" className="btn" onClick={() => resolveConfirm(false)}>
            {request.cancelLabel}
          </button>
          {/* Pas de bouton d'action quand il n'y a rien à forcer : cf.
              `alerterAsync` dans utils/confirmDialog.ts. */}
          {request.confirmLabel !== null && (
            <button
              type="button"
              className={`btn ${danger ? "btn--danger confirmdlg-danger" : "btn--accent"}`}
              onClick={() => resolveConfirm(true)}
            >
              {request.confirmLabel}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
