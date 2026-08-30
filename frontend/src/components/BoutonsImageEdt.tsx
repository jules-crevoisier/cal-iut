/**
 * « Exporter en image » et « Partager », à côté du lien d'abonnement.
 *
 * Retour utilisateur 30/08/2026 : « un bouton à côté du lien d'abonnement
 * qui permette d'exporter cela en image » puis « et un bouton partager »,
 * enfin « je ne vois pas les boutons de photo en prod ».
 *
 * Ils étaient dans `ShareBar`, qui ne s'affiche QUE côté planification
 * (`!readOnly`) — donc invisibles sur les liens personnels, c'est-à-dire
 * précisément là où quelqu'un veut partager son emploi du temps. D'où ce
 * composant à part, posé aux DEUX endroits : la barre de partage côté admin,
 * et l'en-tête du planning en lecture seule, à côté du lien d'abonnement
 * comme demandé.
 */

import { useState } from "react";

import { construireSvg, nomFichierImage, svgVersPng, type OptionsImage } from "../utils/imageEdt";

interface BoutonsImageEdtProps {
  /** Appelé au moment du clic, pas avant : la semaine affichée peut avoir
   *  changé depuis le rendu, et l'image doit montrer celle qu'on regarde. */
  options: () => OptionsImage;
}

export function BoutonsImageEdt({ options }: BoutonsImageEdtProps) {
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const rendre = async () => {
    const o = options();
    const png = await svgVersPng(construireSvg(o));
    return { png, nom: nomFichierImage(o.titre, o.sousTitre) };
  };

  const telecharger = (png: Blob, nom: string) => {
    const url = URL.createObjectURL(png);
    const a = document.createElement("a");
    a.href = url;
    a.download = nom;
    a.click();
    // Révoqué APRÈS le clic : trop tôt, certains navigateurs annulent le
    // téléchargement sans le moindre message.
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  };

  const exporter = async () => {
    setEnCours(true);
    setErreur(null);
    try {
      const { png, nom } = await rendre();
      telecharger(png, nom);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Export impossible");
    } finally {
      setEnCours(false);
    }
  };

  const partager = async () => {
    setEnCours(true);
    setErreur(null);
    try {
      const { png, nom } = await rendre();
      const fichier = new File([png], nom, { type: "image/png" });
      // `canShare` AVANT `share` : sur ordinateur l'API existe souvent sans
      // accepter les fichiers, et `share` échouerait après avoir fait
      // attendre. On retombe alors sur le téléchargement, qui rend le même
      // service.
      if (navigator.canShare?.({ files: [fichier] })) {
        await navigator.share({ files: [fichier], title: nom });
      } else {
        telecharger(png, nom);
      }
    } catch (e) {
      // Fermer la feuille de partage lève `AbortError` : c'est un choix, pas
      // une erreur — l'afficher comme telle serait mensonger.
      if (!(e instanceof DOMException && e.name === "AbortError")) {
        setErreur(e instanceof Error ? e.message : "Partage impossible");
      }
    } finally {
      setEnCours(false);
    }
  };

  return (
    <>
      <button
        type="button"
        className="btn btn--ghost btn--sm"
        onClick={() => void exporter()}
        disabled={enCours}
        title="Image PNG de la semaine affichée, prête à envoyer"
      >
        {enCours ? "…" : "Exporter en image"}
      </button>
      <button
        type="button"
        className="btn btn--ghost btn--sm"
        onClick={() => void partager()}
        disabled={enCours}
        title="Partager l'image de la semaine (téléchargement si le partage n'est pas disponible sur l'appareil)"
      >
        Partager
      </button>
      {erreur && <span className="sharebar-erreur">{erreur}</span>}
    </>
  );
}
