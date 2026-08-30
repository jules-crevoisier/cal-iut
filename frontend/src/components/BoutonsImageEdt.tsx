/**
 * « Exporter en image » et « Partager », à côté du lien d'abonnement.
 *
 * Retours successifs du 30/08/2026 : « un bouton à côté du lien
 * d'abonnement qui permette d'exporter cela en image », « et un bouton
 * partager », « je ne vois pas les boutons de photo en prod », puis :
 * « le lien partager, je pensais à un partage comme sur les RS où tu
 * partages l'image, ça te propose mail / WhatsApp / Discord etc. »
 *
 * **Cette feuille-là n'existe que sur mobile.** `navigator.share` avec des
 * FICHIERS est implémenté sur Android et iOS ; sur ordinateur, Chrome et
 * Edge ne partagent que du texte et une URL, et Firefox ne partage rien du
 * tout. La première version retombait donc en silence sur un téléchargement
 * — techniquement correct, mais ce n'est pas ce qu'on demande quand on dit
 * « partager ».
 *
 * D'où deux comportements, choisis AU CLIC selon ce que l'appareil sait
 * vraiment faire :
 *
 * - mobile : la vraie feuille système, avec WhatsApp, Discord, Mail… ;
 * - ordinateur : un petit menu, dont **Copier l'image**. C'est l'équivalent
 *   réel : on colle ensuite directement dans Discord, WhatsApp Web ou un
 *   mail avec Ctrl+V. Un `mailto:` ne sait pas porter de pièce jointe, il
 *   ne remplace donc pas le presse-papiers — il est proposé à côté, pas à
 *   la place.
 */

import { useEffect, useRef, useState } from "react";

import { construireSvg, nomFichierImage, svgVersPng, type OptionsImage } from "../utils/imageEdt";

interface BoutonsImageEdtProps {
  /** Appelé au moment du clic, pas avant : la semaine affichée peut avoir
   *  changé depuis le rendu, et l'image doit montrer celle qu'on regarde. */
  options: () => OptionsImage;
}

/** Le presse-papiers image demande `ClipboardItem`, un contexte sécurisé et
 *  un geste utilisateur. Absent de Firefox à ce jour — on ne propose donc
 *  l'option que si elle marchera vraiment. */
function presspapiersImagePossible(): boolean {
  return typeof ClipboardItem !== "undefined" && Boolean(navigator.clipboard?.write);
}

export function BoutonsImageEdt({ options }: BoutonsImageEdtProps) {
  const [enCours, setEnCours] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const conteneur = useRef<HTMLSpanElement>(null);

  // Referme le menu au clic ailleurs et à Échap : un menu qu'on ne peut
  // fermer qu'en rechargeant la page est un piège.
  useEffect(() => {
    if (!menu) return;
    const dehors = (e: MouseEvent) => {
      if (!conteneur.current?.contains(e.target as Node)) setMenu(false);
    };
    const echap = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenu(false);
    };
    document.addEventListener("mousedown", dehors);
    document.addEventListener("keydown", echap);
    return () => {
      document.removeEventListener("mousedown", dehors);
      document.removeEventListener("keydown", echap);
    };
  }, [menu]);

  const rendre = async () => {
    const o = options();
    const png = await svgVersPng(construireSvg(o));
    return { png, nom: nomFichierImage(o.titre, o.sousTitre), titre: `${o.titre} — ${o.sousTitre}` };
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

  const avecImage = async (quoi: (r: Awaited<ReturnType<typeof rendre>>) => Promise<void> | void) => {
    setEnCours(true);
    setMessage(null);
    try {
      await quoi(await rendre());
    } catch (e) {
      // Fermer la feuille de partage lève `AbortError` : c'est un choix, pas
      // une erreur — l'afficher comme telle serait mensonger.
      if (!(e instanceof DOMException && e.name === "AbortError")) {
        setMessage(e instanceof Error ? e.message : "Opération impossible");
      }
    } finally {
      setEnCours(false);
      setMenu(false);
    }
  };

  const partager = async () => {
    setMessage(null);
    const o = options();
    // Un fichier factice suffit à interroger l'appareil : inutile de
    // fabriquer l'image entière pour découvrir qu'il ne saura pas la
    // partager.
    const sonde = new File([new Blob([""], { type: "image/png" })], "e.png", { type: "image/png" });
    if (navigator.canShare?.({ files: [sonde] })) {
      await avecImage(async ({ png, nom, titre }) => {
        await navigator.share({ files: [new File([png], nom, { type: "image/png" })], title: titre });
      });
      return;
    }
    void o;
    setMenu((v) => !v);
  };

  const copier = () =>
    avecImage(async ({ png }) => {
      await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
      setMessage("Image copiée — collez-la avec Ctrl+V");
    });

  const parMail = () =>
    avecImage(async ({ png, nom, titre }) => {
      // `mailto:` ne peut PAS porter de pièce jointe : on met l'image dans le
      // presse-papiers d'abord quand c'est possible, et on le dit. Promettre
      // un mail avec l'image attachée serait faux.
      if (presspapiersImagePossible()) {
        await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
      }
      const corps = presspapiersImagePossible()
        ? "L'image de l'emploi du temps est dans le presse-papiers : collez-la ici avec Ctrl+V."
        : "Emploi du temps en pièce jointe (à joindre depuis le fichier téléchargé).";
      if (!presspapiersImagePossible()) telecharger(png, nom);
      window.location.href = `mailto:?subject=${encodeURIComponent(titre)}&body=${encodeURIComponent(corps)}`;
    });

  return (
    <span className="boutons-image" ref={conteneur}>
      {/* Un seul bouton : « Exporter en image » doublonnait avec l'entrée
          « Télécharger l'image » du menu ci-dessous, et sur mobile la
          feuille système propose déjà d'enregistrer (retour utilisateur
          30/08/2026). */}
      <button
        type="button"
        className="btn btn--ghost btn--sm"
        onClick={() => void partager()}
        disabled={enCours}
        aria-expanded={menu}
        aria-haspopup="menu"
        title="Partager l'image de la semaine — WhatsApp, Discord, mail, ou téléchargement"
      >
        {enCours ? "…" : "Partager"}
      </button>

      {menu && (
        <div className="boutons-image-menu" role="menu">
          {presspapiersImagePossible() && (
            <button type="button" role="menuitem" onClick={() => void copier()}>
              Copier l'image
              <span>à coller dans Discord, WhatsApp, un mail…</span>
            </button>
          )}
          <button type="button" role="menuitem" onClick={() => void parMail()}>
            Envoyer par mail
            <span>ouvre votre messagerie</span>
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => void avecImage(({ png, nom }) => telecharger(png, nom))}
          >
            Télécharger l'image
            <span>fichier PNG</span>
          </button>
        </div>
      )}

      {message && <span className="sharebar-erreur">{message}</span>}
    </span>
  );
}
