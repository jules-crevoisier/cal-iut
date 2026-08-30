import { useState } from "react";
import { copyToClipboard } from "../utils/clipboard";
import { construireSvg, nomFichierImage, svgVersPng, type OptionsImage } from "../utils/imageEdt";

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
   *  image : mieux vaut ne rien proposer qu'un bouton qui produit une image
   *  vide (retour utilisateur 30/08/2026). */
  imageEdt?: () => OptionsImage;
  extra?: React.ReactNode;
}

/** Barre "Copier son lien / Agenda .ics / Imprimer", commune aux vues Groupe et Enseignant. */
export function ShareBar({ onCopyLink, onDownloadIcs, onCopySubscribeLink, imageEdt, extra }: ShareBarProps) {
  const [copied, setCopied] = useState(false);
  const [subscribeCopied, setSubscribeCopied] = useState(false);
  const [imageEnCours, setImageEnCours] = useState(false);
  const [erreurImage, setErreurImage] = useState<string | null>(null);

  /** Rend l'image de la semaine affichée. Isolé parce que le téléchargement
   *  ET le partage en ont besoin, et qu'un rendu qui échoue ne doit rien
   *  laisser derrière lui (URL d'objet, état bloqué). */
  const rendreImage = async () => {
    const options = imageEdt!();
    const png = await svgVersPng(construireSvg(options));
    return { png, nom: nomFichierImage(options.titre, options.sousTitre) };
  };

  const telechargerImage = async () => {
    setImageEnCours(true);
    setErreurImage(null);
    try {
      const { png, nom } = await rendreImage();
      const url = URL.createObjectURL(png);
      const a = document.createElement("a");
      a.href = url;
      a.download = nom;
      a.click();
      // Révoqué APRÈS le clic : révoquer trop tôt annule le téléchargement
      // sur certains navigateurs, sans message.
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch (e) {
      setErreurImage(e instanceof Error ? e.message : "Export impossible");
    } finally {
      setImageEnCours(false);
    }
  };

  const partager = async () => {
    setImageEnCours(true);
    setErreurImage(null);
    try {
      const { png, nom } = await rendreImage();
      const fichier = new File([png], nom, { type: "image/png" });
      // `canShare` AVANT `share` : sur ordinateur, l'API existe souvent sans
      // accepter les fichiers, et `share` échouerait après avoir fait
      // attendre. Dans ce cas on retombe sur le téléchargement, qui rend le
      // même service.
      if (navigator.canShare?.({ files: [fichier] })) {
        await navigator.share({ files: [fichier], title: nom });
      } else {
        const url = URL.createObjectURL(png);
        const a = document.createElement("a");
        a.href = url;
        a.download = nom;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 4000);
      }
    } catch (e) {
      // Fermer la feuille de partage lève `AbortError` : ce n'est pas une
      // erreur, c'est un choix.
      if (!(e instanceof DOMException && e.name === "AbortError")) {
        setErreurImage(e instanceof Error ? e.message : "Partage impossible");
      }
    } finally {
      setImageEnCours(false);
    }
  };

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
      {imageEdt && (
        <>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => void telechargerImage()}
            disabled={imageEnCours}
            title="Image PNG de la semaine affichée, prête à envoyer"
          >
            {imageEnCours ? "…" : "Exporter en image"}
          </button>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => void partager()}
            disabled={imageEnCours}
            title="Partager l'image de la semaine (téléchargement si le partage n'est pas disponible)"
          >
            Partager
          </button>
        </>
      )}
      <button type="button" className="btn btn--ghost btn--sm" onClick={() => window.print()}>
        Imprimer
      </button>
      {extra}
      {erreurImage && <span className="sharebar-erreur">{erreurImage}</span>}
    </div>
  );
}
