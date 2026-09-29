/**
 * Lecture/écriture JSON dans `localStorage`, sans jamais planter : navigation
 * privée, stockage bloqué ou quota plein font simplement retomber sur la
 * valeur par défaut (même idiome que `utils/preferences.ts` et
 * `utils/kanbanTabPrefs.ts`). Sert aux réglages d'écran qu'on veut retrouver
 * d'une visite à l'autre : filtres, sections repliées, onglet ouvert.
 */

export function lireLocal<T>(cle: string, defaut: T, valider?: (v: unknown) => v is T): T {
  try {
    const brut = window.localStorage.getItem(cle);
    if (brut === null) return defaut;
    const v: unknown = JSON.parse(brut);
    if (valider) return valider(v) ? v : defaut;
    return v as T;
  } catch {
    return defaut;
  }
}

export function ecrireLocal(cle: string, valeur: unknown): void {
  try {
    window.localStorage.setItem(cle, JSON.stringify(valeur));
  } catch {
    /* réglage perdu à la fermeture, sans conséquence sur l'écran courant */
  }
}
