/**
 * Images jointes à une tâche du kanban (30/09/2026, demande utilisateur :
 * « dans les tâches, ajoute la possibilité de mettre des images » — cas
 * principal : coller une capture d'écran avec Ctrl V).
 *
 * - `ImagesTache` : la section de la modale de tâche (vignettes, bouton
 *   « Ajouter une image », retrait avec confirmation légère dans la vignette).
 *   Le collage (Ctrl V) et le glisser-déposer sont captés par la modale
 *   elle-même (`KanbanView.tsx::TacheModal`), sur toute sa surface.
 * - `ApercuImages` : l'aperçu en grand (Échap ferme, ← → naviguent), ouvert
 *   depuis une vignette ou depuis le compteur d'une carte du tableau — y
 *   compris en lecture seule.
 *
 * Le serveur reste seul juge (types vérifiés sur le contenu, limites) :
 * `trierFichiers` ne fait que refuser TOUT DE SUITE ce qui le serait de
 * toute façon, avec un message clair.
 */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, ExternalLink, ImageOff, ImagePlus, X } from "lucide-react";

import type { ImageTache } from "../api/client";
import { IMAGES_TACHE } from "../api/client";
import "./ImagesTache.css";

/** Ce qu'affichent vignettes et aperçu : une image enregistrée, ou un
 * fichier choisi à la création d'une tâche, pas encore envoyé. */
export interface ImageAffichable {
  cle: string;
  url: string;
  nom: string;
  largeur?: number | null;
  hauteur?: number | null;
  enAttente?: boolean;
}

export function imageAffichable(image: ImageTache): ImageAffichable {
  return { cle: `img-${image.id}`, url: image.url, nom: image.nom, largeur: image.largeur, hauteur: image.hauteur };
}

const LIBELLE_TYPES = "PNG, JPEG, WebP ou GIF";
const TAILLE_MO = IMAGES_TACHE.tailleMax / (1024 * 1024);

/** Répartit les fichiers reçus : acceptés (dans la limite de `places`) et
 * messages de refus, un par fichier écarté. */
export function trierFichiers(fichiers: File[], places: number): { acceptes: File[]; refus: string[] } {
  const acceptes: File[] = [];
  const refus: string[] = [];
  let deTrop = 0;
  for (const f of fichiers) {
    if (!(IMAGES_TACHE.types as readonly string[]).includes(f.type)) {
      refus.push(`« ${f.name || "fichier"} » : format non accepté (${LIBELLE_TYPES}).`);
    } else if (f.size > IMAGES_TACHE.tailleMax) {
      refus.push(`« ${f.name} » : trop lourde (${TAILLE_MO} Mo au maximum).`);
    } else if (acceptes.length >= places) {
      deTrop++;
    } else {
      acceptes.push(f);
    }
  }
  if (deTrop > 0) {
    refus.push(
      `${deTrop} image${deTrop > 1 ? "s" : ""} de trop : ${IMAGES_TACHE.max} au maximum par tâche.`,
    );
  }
  return { acceptes, refus };
}

const EXTENSIONS: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/webp": "webp",
  "image/gif": "gif",
};

/** Une capture collée arrive nommée « image.png » : on lui donne un nom
 * daté, plus parlant dans la liste (« capture-2026-09-30-14h05.png »). */
export function nommerCapture(fichier: File, maintenant: Date = new Date()): File {
  if (fichier.name && !/^image\.\w+$/i.test(fichier.name)) return fichier;
  const deux = (n: number) => String(n).padStart(2, "0");
  const horodatage = `${maintenant.getFullYear()}-${deux(maintenant.getMonth() + 1)}-${deux(maintenant.getDate())}-${deux(
    maintenant.getHours(),
  )}h${deux(maintenant.getMinutes())}`;
  const extension = EXTENSIONS[fichier.type] ?? "png";
  return new File([fichier], `capture-${horodatage}.${extension}`, { type: fichier.type });
}

const RACCOURCI_COLLER =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform ?? "") ? "⌘ V" : "Ctrl V";

// ── Section de la modale ────────────────────────────────────────────────

interface ImagesTacheProps {
  images: ImageAffichable[];
  peutModifier: boolean;
  /** Complément de l'aide (ex. « enregistrées dès l'ajout »). */
  precision?: string;
  /** Envois en cours (affichés comme tels, et comptés dans la limite). */
  envois: number;
  erreur: string | null;
  onAjouter: (fichiers: File[]) => void;
  onRetirer: (image: ImageAffichable) => void;
}

export function ImagesTache({ images, peutModifier, precision, envois, erreur, onAjouter, onRetirer }: ImagesTacheProps) {
  const refChoix = useRef<HTMLInputElement>(null);
  const [apercu, setApercu] = useState<number | null>(null);
  const plein = images.length + envois >= IMAGES_TACHE.max;

  // L'image affichée a été retirée : l'aperçu se recale ou se ferme.
  useEffect(() => {
    if (apercu !== null && apercu >= images.length) setApercu(images.length ? images.length - 1 : null);
  }, [apercu, images.length]);

  return (
    <section className="pj" aria-labelledby="pj-titre">
      <div className="pj-tete">
        <h4 id="pj-titre" className="pj-titre">
          Images
          <span className="pj-nb">
            {images.length}/{IMAGES_TACHE.max}
          </span>
        </h4>
        {peutModifier && (
          <>
            <button
              type="button"
              className="btn btn--sm"
              disabled={plein}
              title={plein ? `${IMAGES_TACHE.max} images au maximum par tâche` : `${LIBELLE_TYPES}, ${TAILLE_MO} Mo au maximum`}
              onClick={() => refChoix.current?.click()}
            >
              <ImagePlus size={14} aria-hidden="true" />
              Ajouter une image
            </button>
            <input
              ref={refChoix}
              type="file"
              className="pj-choix"
              accept={IMAGES_TACHE.types.join(",")}
              multiple
              tabIndex={-1}
              aria-hidden="true"
              onChange={(e) => {
                const fichiers = Array.from(e.target.files ?? []);
                e.target.value = "";
                if (fichiers.length) onAjouter(fichiers);
              }}
            />
          </>
        )}
      </div>

      {images.length > 0 && (
        <ul className="pj-liste">
          {images.map((image, index) => (
            <Vignette
              key={image.cle}
              image={image}
              peutRetirer={peutModifier}
              onOuvrir={() => setApercu(index)}
              onRetirer={() => onRetirer(image)}
            />
          ))}
          {Array.from({ length: envois }, (_, i) => (
            <li key={`envoi-${i}`} className="pj-vignette pj-vignette--envoi" aria-hidden="true" />
          ))}
        </ul>
      )}

      {peutModifier && (
        <p className="pj-aide">
          Collez une capture d’écran (<kbd>{RACCOURCI_COLLER}</kbd>) ou glissez des images sur cette fenêtre
          {precision ? ` — ${precision}` : ""}.
        </p>
      )}
      <p className="pj-etat" role="status">
        {envois > 0 ? `Envoi de ${envois} image${envois > 1 ? "s" : ""}…` : ""}
      </p>
      {erreur && (
        <p className="alerte pj-erreur" role="alert">
          {erreur}
        </p>
      )}

      {apercu !== null && images[apercu] && (
        <ApercuImages images={images} index={apercu} onIndex={setApercu} onClose={() => setApercu(null)} />
      )}
    </section>
  );
}

interface VignetteProps {
  image: ImageAffichable;
  peutRetirer: boolean;
  onOuvrir: () => void;
  onRetirer: () => void;
}

function Vignette({ image, peutRetirer, onOuvrir, onRetirer }: VignetteProps) {
  const [confirmer, setConfirmer] = useState(false);
  const [indisponible, setIndisponible] = useState(false);
  return (
    <li className={`pj-vignette${image.enAttente ? " pj-vignette--attente" : ""}`}>
      <button type="button" className="pj-vignette-image" aria-label={`Agrandir « ${image.nom} »`} onClick={onOuvrir}>
        {indisponible || !image.url ? (
          <span className="pj-indisponible">
            <ImageOff size={16} aria-hidden="true" />
            Image indisponible
          </span>
        ) : (
          <img src={image.url} alt="" loading="lazy" decoding="async" onError={() => setIndisponible(true)} />
        )}
      </button>
      {image.enAttente && <span className="pj-vignette-note" title="Envoyée à la création de la tâche">
          en attente
        </span>}
      {peutRetirer && !confirmer && (
        <button
          type="button"
          className="pj-retirer"
          aria-label={`Retirer « ${image.nom} »`}
          title="Retirer"
          // Pas encore envoyée : rien à perdre, retirée sans question.
          onClick={() => (image.enAttente ? onRetirer() : setConfirmer(true))}
        >
          <X size={13} aria-hidden="true" />
        </button>
      )}
      {confirmer && (
        <div className="pj-confirmer" role="group" aria-label={`Retirer « ${image.nom} » ?`}>
          <span>Retirer ?</span>
          <span className="pj-confirmer-actions">
            <button
              type="button"
              className="btn btn--danger btn--sm"
              autoFocus
              onClick={() => {
                setConfirmer(false);
                onRetirer();
              }}
            >
              Retirer
            </button>
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => setConfirmer(false)}>
              Garder
            </button>
          </span>
        </div>
      )}
    </li>
  );
}

// ── Aperçu en grand ─────────────────────────────────────────────────────

interface ApercuImagesProps {
  images: ImageAffichable[];
  index: number;
  onIndex: (index: number) => void;
  onClose: () => void;
}

export function ApercuImages({ images, index, onIndex, onClose }: ApercuImagesProps) {
  const refFermer = useRef<HTMLButtonElement>(null);
  const image = images[index];
  const nb = images.length;

  // Focus sur « Fermer » à l'ouverture, rendu à l'élément d'origine ensuite.
  useEffect(() => {
    const origine = document.activeElement as HTMLElement | null;
    refFermer.current?.focus();
    return () => origine?.focus?.();
  }, []);

  // Capturé sur `window` AVANT tout le reste : Échap ne ferme que l'aperçu,
  // pas la modale de tâche en dessous (qui écoute `document`).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        e.stopPropagation();
        const suivant = index + (e.key === "ArrowLeft" ? -1 : 1);
        if (suivant >= 0 && suivant < nb) onIndex(suivant);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [index, nb, onClose, onIndex]);

  if (!image) return null;
  const dimensions = image.largeur && image.hauteur ? `${image.largeur} × ${image.hauteur}` : null;

  return createPortal(
    <div
      className="pj-apercu"
      role="dialog"
      aria-modal="true"
      aria-label={`Aperçu de « ${image.nom} »${nb > 1 ? `, image ${index + 1} sur ${nb}` : ""}`}
      onClick={(e) => {
        e.stopPropagation();
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="pj-apercu-barre">
        <span className="pj-apercu-nom" title={image.nom}>
          {image.nom}
        </span>
        <span className="pj-apercu-infos">
          {nb > 1 && (
            <span className="pj-apercu-rang">
              {index + 1} / {nb}
            </span>
          )}
          {dimensions && <span className="pj-apercu-dim">{dimensions}</span>}
        </span>
        {!image.enAttente && (
          <a className="pj-apercu-bouton" href={image.url} target="_blank" rel="noopener noreferrer" title="Ouvrir l’original dans un onglet">
            <ExternalLink size={16} aria-hidden="true" />
            <span className="pj-apercu-libelle">Original</span>
          </a>
        )}
        <button ref={refFermer} type="button" className="pj-apercu-bouton" aria-label="Fermer l’aperçu" title="Fermer (Échap)" onClick={onClose}>
          <X size={18} aria-hidden="true" />
        </button>
      </div>
      <div
        className="pj-apercu-scene"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
      >
        <img className="pj-apercu-image" src={image.url} alt={image.nom} />
        {nb > 1 && (
          <>
            <button
              type="button"
              className="pj-apercu-nav pj-apercu-nav--prec"
              aria-label="Image précédente"
              title="Précédente (←)"
              disabled={index === 0}
              onClick={() => onIndex(index - 1)}
            >
              <ChevronLeft size={22} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="pj-apercu-nav pj-apercu-nav--suiv"
              aria-label="Image suivante"
              title="Suivante (→)"
              disabled={index === nb - 1}
              onClick={() => onIndex(index + 1)}
            >
              <ChevronRight size={22} aria-hidden="true" />
            </button>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}
