import { BoutonsImageEdt } from "./BoutonsImageEdt";
import { CopyButton } from "./CopyButton";
import { OpenLinkButton } from "./OpenLinkButton";
import type { OptionsImage } from "../utils/imageEdt";

interface ShareBarProps {
  onCopyLink: () => string;
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

/** Barre "Copier son lien / Lien agenda / Partager / Imprimer", commune aux
 *  vues Groupe et Enseignant.
 *
 *  Le TÉLÉCHARGEMENT .ics a été retiré le 30/08/2026 : c'est un fichier
 *  figé au moment du clic, que le lien d'abonnement remplace
 *  avantageusement puisqu'il se remet à jour tout seul dans l'agenda. En
 *  garder deux obligeait à expliquer lequel choisir. */
export function ShareBar({ onCopyLink, onCopySubscribeLink, imageEdt, extra }: ShareBarProps) {
  const lienPerso = onCopyLink();
  return (
    <div className="sharebar no-print">
      <span className="lien-boutons">
        <CopyButton text={onCopyLink} idleLabel="Copier son lien" />
        <OpenLinkButton href={lienPerso} />
      </span>
      {onCopySubscribeLink && (
        <CopyButton
          text={onCopySubscribeLink}
          idleLabel="Lien agenda"
          title="Lien à coller dans Google Agenda / Apple Calendrier / Outlook (« ajouter un agenda par URL ») — se remet à jour tout seul, pas besoin de re-télécharger."
        />
      )}
      {imageEdt && <BoutonsImageEdt options={imageEdt} />}
      <button type="button" className="btn btn--ghost btn--sm" onClick={() => window.print()}>
        Imprimer
      </button>
      {extra}
    </div>
  );
}
