/**
 * Identité d'un enseignant côté écran (onglet « Enseignants & vacataires »,
 * 01/10/2026) : prénom, nom, type, téléphone.
 *
 * Une seule source : `payload.teacherIdentites` (calculé par le serveur,
 * `ingestion/identite_enseignants.py`). Sans elle (lien public, serveur plus
 * ancien), prénom et nom se déduisent du nom affiché, avec la MÊME règle
 * (`separerNom`), et le type reste inconnu.
 *
 * Téléphone : mêmes formats que le serveur (`normaliser_telephone`), qui
 * reste juge — ici, un refus immédiat sans aller-retour.
 */

import type { AppPayload, IdentiteEnseignant, TypeEnseignant } from "../types/app";
import { separerNom } from "./nomEnseignant";

export const LIBELLE_TYPE: Record<TypeEnseignant, string> = { enseignant: "Enseignant", vacataire: "Vacataire" };

/** Libellé du type, « à préciser » s'il est inconnu. */
export function libelleType(type: TypeEnseignant | null | undefined): string {
  return type ? LIBELLE_TYPE[type] : "à préciser";
}

export function identiteDe(payload: Pick<AppPayload, "teacherLabels" | "teacherIdentites">, code: string): IdentiteEnseignant {
  const connue = payload.teacherIdentites?.[code];
  if (connue && (connue.prenom || connue.nom)) return connue;
  const { prenom, nom } = separerNom(payload.teacherLabels[code] ?? code, code);
  return { prenom, nom, type: connue?.type ?? null };
}

/** Numéro au format E.164 (« +33612345678 »), ou null s'il est invalide. */
export function normaliserTelephone(brut: string): string | null {
  let t = brut.trim().replace(/^tel:/i, "").trim();
  if (!t) return null;
  t = t.replace(/\(\s*0\s*\)/g, "").replace(/[\s.\-/()]+/g, "");
  if (t.startsWith("00")) t = `+${t.slice(2)}`;
  if (t.startsWith("+")) {
    const chiffres = t.slice(1);
    if (!/^\d+$/.test(chiffres) || chiffres.startsWith("0")) return null;
    if (chiffres.startsWith("33")) {
      const national = chiffres.slice(2);
      return national.length === 9 && !national.startsWith("0") ? `+33${national}` : null;
    }
    return chiffres.length >= 8 && chiffres.length <= 15 ? `+${chiffres}` : null;
  }
  if (/^0[1-9]\d{8}$/.test(t)) return `+33${t.slice(1)}`;
  return null;
}

export function validerTelephone(valeur: string): string | null {
  if (!valeur.trim()) return "Saisissez un numéro.";
  return normaliserTelephone(valeur) ? null : "Numéro invalide (formes attendues : 06 12 34 56 78 ou +33 6 12 34 56 78).";
}

/** « +33612345678 » -> « 06 12 34 56 78 » ; un numéro étranger reste en E.164. */
export function formaterTelephone(e164: string | null | undefined): string {
  const t = (e164 ?? "").trim();
  if (/^\+33\d{9}$/.test(t)) {
    const national = `0${t.slice(3)}`;
    return national.replace(/(\d{2})(?=\d)/g, "$1 ");
  }
  return t;
}
