import { useState } from "react";

import { copyToClipboard } from "../utils/clipboard";
import { BoutonsImageEdt } from "./BoutonsImageEdt";
import type { OptionsImage } from "../utils/imageEdt";

interface ShareBarProps {
  onCopyLink: () => string;
  onDownloadIcs: () => void;
  /** Lien d'abonnement .ics (flux qui se remet à jour tout seul dans l'appli
   * agenda, contrairement au fichier téléchargé une fois) — retour
   * utilisateur 28/08/2026 (relayé depuis Discord) : « pour le ics on
   * pourrait peut-être faire un lien qui s'update automatique ? ». Optionnel
   * : absent tant que l'appelant n'a pas de code/jeton pour construire l'URL. */
  onCopySubscribeLink?: () => string;
  /** De quoi dessiner l'image de la semaine affichée. Absent = pas de bouton
   *  image : mieux vaut ne rien proposer qu'un bouton produisant une image
   *  vide. Les mêmes boutons existent aussi dans l'en-tête du planning en
   *  lecture seule, où cette barre ne s'affiche pas (cf. `BoutonsImageEdt`). */
  imageEdt?: () => OptionsImage;
  extra?: React.ReactNode;
}

/** Barre "Copier son lien / Agenda .ics / Imprimer", commune aux vues Groupe et Enseignant. */
export function ShareBar({ onCopyLink, onDownloadIcs, onCopySubscribeLink, imageEdt, extra }: ShareBarProps) {
  const [copied, setCopied] = useState(false);
  const [subscribeCopied, setSubscribeCopied] = useState(false);

  const handleCopy = async () => {
    const ok = await copyToClipboard(onCopyLink());
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    }
  };

  const handleCopySubscribe = async () => {
    if (!onCopySubscribeLink) return;
    const ok = await copyToClipboard(onCopySubscribeLink());
    if (ok) {
      setSubscribeCopied(true);
      setTimeout(() => setSubscribeCopied(false), 1400);
    }
  };

  return (
    <div className="sharebar no-print">
      <button type="button" className="btn btn--ghost btn--sm" onClick={handleCopy}>
        {copied ? "Copié ✓" : "Copier son lien"}
      </button>
      <button type="button" className="btn btn--ghost btn--sm" onClick={onDownloadIcs}>
        Agenda .ics
      </button>
      {onCopySubscribeLink && (
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={handleCopySubscribe}
          title="Lien à coller dans Google Agenda / Apple Calendrier / Outlook (« ajouter un agenda par URL ») — se remet à jour tout seul, pas besoin de re-télécharger."
        >
          {subscribeCopied ? "Copié ✓" : "Lien d'abonnement"}
        </button>
      )}
      {imageEdt && <BoutonsImageEdt options={imageEdt} />}
      <button type="button" className="btn btn--ghost btn--sm" onClick={() => window.print()}>
        Imprimer
      </button>
      {extra}
    </div>
  );
}
