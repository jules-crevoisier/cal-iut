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

/** Actions de partage des fiches Groupe et Enseignant (côté planification :
 *  on y prépare l'envoi du lien), posées à droite de la barre d'outils.
 *
 *  Deux groupes séparés par un filet : ce qu'on fait de la semaine affichée
 *  (image, impression) et ce qu'on ENVOIE à la personne (son agenda, un
 *  mail, son lien). « Copier son lien » est l'action principale de la fiche,
 *  en dernier, à droite (refonte v2 du 29/09/2026 : plus de boutons encadrés
 *  en pastilles, une rangée à plat).
 *
 *  Le TÉLÉCHARGEMENT .ics a été retiré le 30/08/2026 : le lien d'abonnement
 *  le remplace puisqu'il se remet à jour tout seul. */
export function ShareBar({ onCopyLink, onCopySubscribeLink, imageEdt, extra }: ShareBarProps) {
  const lienPerso = onCopyLink();
  return (
    <div className="sharebar no-print">
      <span className="sharebar-groupe" role="group" aria-label="Semaine affichée">
        {imageEdt && <BoutonsImageEdt options={imageEdt} />}
        <button type="button" className="btn btn--ghost" onClick={() => window.print()}>
          Imprimer
        </button>
      </span>
      <span className="sharebar-sep" aria-hidden="true" />
      <span className="sharebar-groupe" role="group" aria-label="Envoyer">
        {onCopySubscribeLink && (
          <CopyButton
            text={onCopySubscribeLink}
            idleLabel="Lien agenda"
            className="btn"
            title="Lien à coller dans Google Agenda / Apple Calendrier / Outlook (« ajouter un agenda par URL ») — se remet à jour tout seul."
          />
        )}
        {extra}
        <OpenLinkButton href={lienPerso} label="Ouvrir son lien dans un nouvel onglet" />
        <CopyButton text={onCopyLink} idleLabel="Copier son lien" className="btn btn--primary" />
      </span>
    </div>
  );
}
