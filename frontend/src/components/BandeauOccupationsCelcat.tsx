/**
 * Bandeau discret : le relevé des occupations hors MMI (Celcat) est ancien.
 *
 * Les contraintes restent appliquées telles quelles (mieux vaut une
 * occupation un peu ancienne que plus aucune) ; on prévient seulement que
 * les blocs « Occupé ailleurs » / « Réservé dans Celcat » peuvent avoir
 * bougé. Rien quand le relevé est frais, ni quand il n'y en a jamais eu
 * (l'écran Celcat le dit — pas chaque vue).
 */
import type { AppPayload } from "../types/app";
import { bandeauFraicheur } from "../utils/occupationsExternes";

export function BandeauOccupationsCelcat({ payload }: { payload: Pick<AppPayload, "occupationsExternes"> }) {
  const texte = bandeauFraicheur(payload);
  if (!texte) return null;
  return (
    <p className="muted bandeau-occupations-celcat" role="status">
      {texte}
    </p>
  );
}
