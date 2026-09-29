import { BoutonsImageEdt } from "./BoutonsImageEdt";
import { CopyButton } from "./CopyButton";
import { OpenLinkButton } from "./OpenLinkButton";
import type { OptionsImage } from "../utils/imageEdt";

interface ShareBarProps {
  onCopyLink: () => string;
  /** Lien d'abonnement .ics (flux qui se remet à jour tout seul dans l'appli
   * agenda) — retour utilisateur 28/08/2026 : « pour le ics on pourrait
   * peut-être faire un lien qui s'update automatique ? ». */
  onCopySubscribeLink?: () => string;
  /** De quoi dessiner l'image de la semaine affichée. Absent = pas de bouton
   *  image : mieux vaut ne rien proposer qu'une image vide. */
  imageEdt?: () => OptionsImage;
  extra?: React.ReactNode;
}

/** Barre « Copier son lien / Lien agenda / Partager / Imprimer » des vues
 *  Groupe et Enseignant (côté planification : on y prépare l'envoi du lien).
 *
 *  Deux groupes séparés par un filet : ce qu'on ENVOIE à la personne (son
 *  lien, son agenda, un mail) et ce qu'on fait de la semaine affichée
 *  (image, impression). En une rangée de boutons identiques, rien ne disait
 *  lesquels allaient ensemble.
 *
 *  Le TÉLÉCHARGEMENT .ics a été retiré le 30/08/2026 : le lien d'abonnement
 *  le remplace puisqu'il se remet à jour tout seul. */
export function ShareBar({ onCopyLink, onCopySubscribeLink, imageEdt, extra }: ShareBarProps) {
  const lienPerso = onCopyLink();
  return (
    <div className="sharebar no-print">
      <span className="sharebar-groupe" role="group" aria-label="Envoyer">
        <CopyButton text={onCopyLink} idleLabel="Copier son lien" />
        <OpenLinkButton href={lienPerso} label="Ouvrir son lien dans un nouvel onglet" />
        {onCopySubscribeLink && (
          <CopyButton
            text={onCopySubscribeLink}
            idleLabel="Lien agenda"
            title="Lien à coller dans Google Agenda / Apple Calendrier / Outlook (« ajouter un agenda par URL ») — se remet à jour tout seul."
          />
        )}
        {extra}
      </span>
      <span className="sharebar-groupe" role="group" aria-label="Semaine affichée">
        {imageEdt && <BoutonsImageEdt options={imageEdt} />}
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => window.print()}>
          Imprimer
        </button>
      </span>
    </div>
  );
}
