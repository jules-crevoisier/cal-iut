/**
 * Tri de tableau par clic sur l'en-tête de colonne (1er clic : croissant,
 * 2e : décroissant). `aria-sort` sur le `<th>`, flèche TEXTE à côté du
 * libellé — l'ordre se lit sans deviner.
 */

import { useMemo, useState, type ReactNode } from "react";

import { ecrireLocal, lireLocal } from "../utils/stockageLocal";

import "./TriColonne.css";

export interface EtatTri<K extends string> {
  cle: K;
  sens: 1 | -1;
}

/**
 * `cleStockage` (facultatif, 01/10/2026) : le tri choisi est retrouvé à la
 * visite suivante, sur ce poste (`localStorage`).
 */
export function useTri<T, K extends string>(
  lignes: T[],
  valeurs: Record<K, (l: T) => string | number>,
  initial: EtatTri<K>,
  cleStockage?: string,
) {
  const [tri, setTriEtat] = useState<EtatTri<K>>(() =>
    cleStockage
      ? lireLocal<EtatTri<K>>(cleStockage, initial, (v): v is EtatTri<K> => {
          const e = v as Partial<EtatTri<K>> | null;
          return !!e && typeof e.cle === "string" && e.cle in valeurs && (e.sens === 1 || e.sens === -1);
        })
      : initial,
  );
  const setTri = (maj: (t: EtatTri<K>) => EtatTri<K>) =>
    setTriEtat((t) => {
      const suivant = maj(t);
      if (cleStockage) ecrireLocal(cleStockage, suivant);
      return suivant;
    });
  const triees = useMemo(() => {
    const f = valeurs[tri.cle];
    return [...lignes].sort((a, b) => {
      const va = f(a);
      const vb = f(b);
      const c =
        typeof va === "number" && typeof vb === "number"
          ? va - vb
          : String(va).localeCompare(String(vb), "fr", { numeric: true, sensitivity: "base" });
      return c * tri.sens;
    });
    // `valeurs` est une table de fonctions stable par écran.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lignes, tri]);
  const trierPar = (cle: K) => setTri((t) => (t.cle === cle ? { cle, sens: t.sens === 1 ? -1 : 1 } : { cle, sens: 1 }));
  return { triees, tri, trierPar };
}

interface TriColonneProps<K extends string> {
  cle: K;
  tri: EtatTri<K>;
  onTrier: (cle: K) => void;
  children: ReactNode;
  num?: boolean;
  /** Classe en plus sur le `<th>` (ex. colonne masquée au téléphone). */
  className?: string;
}

export function TriColonne<K extends string>({ cle, tri, onTrier, children, num, className }: TriColonneProps<K>) {
  const actif = tri.cle === cle;
  const classes = [num ? "num" : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <th
      className={classes || undefined}
      aria-sort={actif ? (tri.sens === 1 ? "ascending" : "descending") : "none"}
    >
      <button type="button" className={`tri-colonne${actif ? " actif" : ""}`} onClick={() => onTrier(cle)}>
        {children}
        <span className="tri-fleche" aria-hidden="true">
          {actif ? (tri.sens === 1 ? "↑" : "↓") : "↕"}
        </span>
      </button>
    </th>
  );
}
