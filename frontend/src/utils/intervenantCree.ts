/**
 * « Intervenant créé » (30/09/2026) : la modale « Nouvel intervenant » ouvre
 * la fiche du nouveau venu — mais le planning n'est relu qu'un instant plus
 * tard (`apresEnregistrement`). Entre les deux, la fiche ne doit ni afficher
 * « Enseignant introuvable », ni oublier d'annoncer la création. La modale
 * vit dans deux écrans (annuaire, Référence → Codes Celcat), la fiche dans
 * un troisième : ce petit relais, sans état React, les relie.
 */

const DUREE_MS = 60_000;

let dernier: { code: string; le: number } | null = null;

export function marquerIntervenantCree(code: string): void {
  dernier = { code: code.toUpperCase(), le: Date.now() };
}

/** `code` vient-il d'être créé depuis ce poste (depuis moins d'une minute) ? */
export function vientDEtreCree(code: string): boolean {
  return !!dernier && dernier.code === code.toUpperCase() && Date.now() - dernier.le < DUREE_MS;
}

/** Pour les tests. */
export function oublierIntervenantCree(): void {
  dernier = null;
}
