/**
 * Export de l'emploi du temps en image — retour utilisateur 30/08/2026 :
 * « un bouton à côté du lien d'abonnement qui permette d'exporter cela en
 * image, genre ça fait comme un screen de l'EDT propre ».
 *
 * L'image est DESSINÉE, pas capturée. Deux raisons :
 *
 * 1. Une capture du DOM embarquerait ce qui traîne autour — barres de
 *    boutons, ascenseurs, moitié de ligne coupée — alors que la demande est
 *    justement « propre ». Ici, ce qui entre dans l'image est décidé :
 *    titre, semaine, cinq jours, six créneaux, les séances.
 * 2. Aucune dépendance. `html2canvas` et consorts pèsent quelques centaines
 *    de kilo-octets, ne savent pas rendre toutes les propriétés CSS, et
 *    échouent silencieusement sur celles qu'ils ignorent.
 *
 * Le chemin est SVG -> `<img>` -> `<canvas>` -> PNG. Le SVG n'utilise que
 * des polices système : une police chargée par le navigateur n'est pas
 * disponible dans l'image détachée, et le texte y sortirait dans une police
 * de repli sans prévenir.
 */

import { teinteMatiere, varianteMatiere } from "./couleursMatiere";
import { DAY_LABELS, SLOT_TIMES } from "./slots";
import type { AppPayload, AppRow } from "../types/app";

const LARGEUR_HEURES = 78;
const LARGEUR_JOUR = 250;
const HAUTEUR_ENTETE = 70;
const HAUTEUR_JOURS = 34;
const HAUTEUR_CRENEAU = 92;
const MARGE = 20;

/** Échappe le texte pour du XML : un « & » ou un « < » dans un nom de cours
 *  casserait le SVG en entier, et le PNG sortirait vide. */
function xml(texte: string): string {
  return String(texte)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Coupe un libellé trop long pour la colonne, en mots entiers. */
function couper(texte: string, maxCaracteres: number, maxLignes: number): string[] {
  const mots = texte.split(" ");
  const lignes: string[] = [];
  let courante = "";
  for (const mot of mots) {
    const essai = courante ? `${courante} ${mot}` : mot;
    if (essai.length > maxCaracteres && courante) {
      lignes.push(courante);
      courante = mot;
      if (lignes.length === maxLignes) break;
    } else {
      courante = essai;
    }
  }
  if (lignes.length < maxLignes && courante) lignes.push(courante);
  if (lignes.length === maxLignes && mots.join(" ").length > lignes.join(" ").length) {
    lignes[maxLignes - 1] = lignes[maxLignes - 1].replace(/.{1}$/, "…");
  }
  return lignes;
}

export interface OptionsImage {
  titre: string;
  sousTitre: string;
  rows: AppRow[];
  payload: AppPayload;
  couleursParMatiere: boolean;
}

function couleursSeance(r: AppRow, parMatiere: boolean): { fond: string; barre: string } {
  if (!parMatiere) {
    const parType: Record<string, [string, string]> = {
      CM: ["#eef0f4", "#6b7280"],
      TD: ["#e9f0fb", "#3b6fd4"],
      TP: ["#e6f5f2", "#159a86"],
    };
    const [fond, barre] = parType[r.t] ?? ["#f1f2f5", "#8b93a3"];
    return { fond, barre };
  }
  const teinte = teinteMatiere(r.c);
  const variante = varianteMatiere(r.c);
  return {
    fond: `hsl(${teinte} ${64 - variante * 10}% ${95 - variante * 5}%)`,
    barre: `hsl(${teinte} ${62 - variante * 8}% ${48 - variante * 7}%)`,
  };
}

export function construireSvg(options: OptionsImage): string {
  const { titre, sousTitre, rows, payload, couleursParMatiere } = options;
  const largeur = MARGE * 2 + LARGEUR_HEURES + LARGEUR_JOUR * 5;
  const hauteur = MARGE * 2 + HAUTEUR_ENTETE + HAUTEUR_JOURS + HAUTEUR_CRENEAU * 6;

  const parts: string[] = [];
  parts.push(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${largeur}" height="${hauteur}" ` +
      `viewBox="0 0 ${largeur} ${hauteur}">`,
    `<rect width="${largeur}" height="${hauteur}" fill="#ffffff"/>`,
    // Polices SYSTÈME uniquement : une police téléchargée par la page n'est
    // pas disponible dans l'image une fois détachée du document.
    `<style>text{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;}</style>`,
  );

  parts.push(
    `<text x="${MARGE}" y="${MARGE + 26}" font-size="21" font-weight="700" fill="#111827">${xml(titre)}</text>`,
    `<text x="${MARGE}" y="${MARGE + 50}" font-size="14" fill="#6b7280">${xml(sousTitre)}</text>`,
  );

  const hautGrille = MARGE + HAUTEUR_ENTETE;

  for (let d = 0; d < 5; d++) {
    const x = MARGE + LARGEUR_HEURES + d * LARGEUR_JOUR;
    parts.push(
      `<rect x="${x}" y="${hautGrille}" width="${LARGEUR_JOUR}" height="${HAUTEUR_JOURS}" fill="#f6f7f9"/>`,
      `<text x="${x + LARGEUR_JOUR / 2}" y="${hautGrille + 22}" font-size="13" font-weight="600" ` +
        `text-anchor="middle" fill="#374151">${xml(DAY_LABELS[d])}</text>`,
    );
  }

  for (let s = 0; s < 6; s++) {
    const y = hautGrille + HAUTEUR_JOURS + s * HAUTEUR_CRENEAU;
    parts.push(
      `<rect x="${MARGE}" y="${y}" width="${LARGEUR_HEURES}" height="${HAUTEUR_CRENEAU}" fill="#f6f7f9"/>`,
      `<text x="${MARGE + LARGEUR_HEURES / 2}" y="${y + 20}" font-size="11" text-anchor="middle" ` +
        `fill="#6b7280">${xml(SLOT_TIMES[s].label)}</text>`,
    );
    for (let d = 0; d < 5; d++) {
      const x = MARGE + LARGEUR_HEURES + d * LARGEUR_JOUR;
      parts.push(
        `<rect x="${x}" y="${y}" width="${LARGEUR_JOUR}" height="${HAUTEUR_CRENEAU}" ` +
          `fill="none" stroke="#e5e7eb" stroke-width="1"/>`,
      );
    }
  }

  // Une séance de 3h occupe DEUX créneaux : elle est dessinée une fois, sur
  // toute sa hauteur — la découper en deux blocs identiques donnerait une
  // image qui ment sur la durée.
  for (const r of rows) {
    if (r.d < 0 || r.d > 4 || r.s < 0 || r.s > 5) continue;
    const duree = Math.max(1, r.dur || 1);
    const x = MARGE + LARGEUR_HEURES + r.d * LARGEUR_JOUR;
    const y = hautGrille + HAUTEUR_JOURS + r.s * HAUTEUR_CRENEAU;
    const h = HAUTEUR_CRENEAU * duree - 6;
    const { fond, barre } = couleursSeance(r, couleursParMatiere);
    const groupes = r.g.map((g) => payload.groupLabels[g] ?? g).join(", ");

    parts.push(
      `<rect x="${x + 4}" y="${y + 3}" width="${LARGEUR_JOUR - 8}" height="${h}" rx="6" fill="${fond}"/>`,
      `<rect x="${x + 4}" y="${y + 3}" width="4" height="${h}" rx="2" fill="${barre}"/>`,
    );
    const nom = couper(r.n || r.c, 30, duree > 1 ? 3 : 2);
    nom.forEach((ligne, i) => {
      parts.push(
        `<text x="${x + 16}" y="${y + 24 + i * 16}" font-size="12.5" font-weight="600" ` +
          `fill="#111827">${xml(ligne)}</text>`,
      );
    });
    const basInfos = y + 24 + nom.length * 16;
    parts.push(
      `<text x="${x + 16}" y="${basInfos + 2}" font-size="10.5" fill="#6b7280">` +
        `${xml(r.c)} · ${xml(r.t)}${groupes ? ` · ${xml(groupes)}` : ""}</text>`,
    );
    if (r.r) {
      parts.push(
        `<text x="${x + LARGEUR_JOUR - 16}" y="${y + 24}" font-size="12" font-weight="600" ` +
          `text-anchor="end" fill="#111827">${xml(r.r)}</text>`,
      );
    }
  }

  parts.push(`</svg>`);
  return parts.join("");
}

/** Rend le SVG en PNG. `devicePixelRatio` × 2 : une image d'emploi du temps
 *  finit agrandie ou imprimée, et un rendu à 1× y devient illisible. */
export async function svgVersPng(svg: string, echelle = 2): Promise<Blob> {
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  const image = new Image();
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = () => reject(new Error("Le rendu de l'image a échoué."));
    image.src = url;
  });
  const canvas = document.createElement("canvas");
  canvas.width = image.width * echelle;
  canvas.height = image.height * echelle;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas indisponible sur ce navigateur.");
  ctx.scale(echelle, echelle);
  ctx.drawImage(image, 0, 0);
  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Conversion PNG impossible."))), "image/png");
  });
}

export function nomFichierImage(titre: string, sousTitre: string): string {
  const propre = `${titre} ${sousTitre}`
    .normalize("NFD")
    // U+0300-U+036F : les diacritiques que `NFD` vient de détacher.
    // En échappements explicites — écrits en clair, ce sont des
    // caractères combinants invisibles qu'un éditeur peut abîmer.
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .toLowerCase();
  return `edt-${propre || "planning"}.png`;
}
