/**
 * Dernier couple semaine/jour utilisé dans `CreerSeanceModal`, mémorisé pour
 * le reste de la session navigateur — todo département, retour Kyllian
 * Bresson (22/09/2026) : « création de nouvelle séance à simplifier (rester
 * sur la semaine à saisir, sur le jour à saisir) [...] pour chaque séance à
 * créer le formulaire est long ».
 *
 * Sert UNIQUEMENT de repli : la Vue Promo pré-remplit toujours depuis ce
 * qu'elle affiche à l'écran (`suggestion.week`/`suggestion.day`, prioritaire)
 * — cette mémoire ne joue que si la modale s'ouvre un jour ailleurs, sans
 * contexte de semaine/jour à proposer.
 *
 * `sessionStorage`, pas `localStorage` (cf. `utils/preferences.ts`, qui lui
 * sert un réglage d'affichage durable) : la demande est explicitement bornée
 * à « le reste de la session navigateur », jamais entre deux visites.
 */
const CLE = "cal-iut:creerSeance:dernierWeekDay:v1";

export interface DernierWeekDay {
  week: number;
  day: number;
}

export function lireDernierWeekDay(): DernierWeekDay | null {
  try {
    const brut = window.sessionStorage.getItem(CLE);
    if (!brut) return null;
    const lu = JSON.parse(brut) as Partial<DernierWeekDay>;
    if (typeof lu.week !== "number" || typeof lu.day !== "number") return null;
    return { week: lu.week, day: lu.day };
  } catch {
    // Navigation privée, stockage bloqué, JSON abîmé : pas de repli, le
    // formulaire reste utilisable avec ses valeurs par défaut.
    return null;
  }
}

export function ecrireDernierWeekDay(valeur: DernierWeekDay): void {
  try {
    window.sessionStorage.setItem(CLE, JSON.stringify(valeur));
  } catch {
    /* repli perdu, sans conséquence sur le formulaire courant */
  }
}
