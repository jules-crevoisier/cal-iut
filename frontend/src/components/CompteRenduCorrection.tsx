/**
 * Ce que « Corriger » a réellement fait — pas ce qu'il voulait faire.
 *
 * Trois choses que le message seul ne disait pas, et dont l'absence poussait
 * à recliquer (retour utilisateur du 16/09/2026) :
 *
 *   - combien de corrections ATTENDAIENT DÉJÀ. Le serveur déduplique, donc
 *     recliquer n'ajoute rien — mais l'écran annonçait le compte entier à
 *     chaque fois, ce qui se lisait « ça n'est pas parti » ;
 *   - ce qui n'a PAS pu être traduit, avec sa raison, groupé par cause :
 *     douze fois le même groupe absent d'une table et douze causes distinctes
 *     n'appellent pas le même geste ;
 *   - les suppressions épargnées sont exclues de ce décompte : elles ont leur
 *     propre panneau, et les compter ici comme « non traduites » ferait
 *     croire à un échec là où il y a un choix.
 */
import type { CelcatCorrection } from "../api/client";
import { pluriel } from "../utils/celcatStatut";

export function CompteRenduCorrection({ correction }: { correction: CelcatCorrection }) {
  const deja = correction.deja_en_file ?? 0;
  const abandonnes = (correction.abandonnes ?? []).filter((a) => a.raison !== "suppression_epargnee");
  const parExplication = new Map<string, string[]>();
  for (const a of abandonnes) {
    const cle = a.explication || a.raison;
    parExplication.set(cle, [...(parExplication.get(cle) ?? []), a.session_id || `#${a.event_id}`]);
  }

  return (
    <div className="celcat-compte-rendu" data-testid="compte-rendu-correction">
      <p>
        {correction.total > 0
          ? `${pluriel(correction.total, "correction mise", "corrections mises")} en file.`
          : "Aucune nouvelle correction à mettre en file."}
      </p>
      {deja > 0 ? (
        <p data-testid="correction-deja-en-file">
          {pluriel(deja, "correction attendait", "corrections attendaient")} déjà d’être poussée
          {deja > 1 ? "s" : ""} — recliquer n’y change rien, elles partent au prochain passage du worker.
        </p>
      ) : null}
      {parExplication.size > 0 ? (
        <details data-testid="correction-abandonnes" className="celcat-repli">
          <summary>
            {pluriel(abandonnes.length, "écart non traduit", "écarts non traduits")} en correction (
            {pluriel(parExplication.size, "cause")})
          </summary>
          <ul>
            {[...parExplication.entries()].map(([explication, seances]) => (
              <li key={explication}>
                <strong>{seances.length}×</strong> {explication}
                <div className="celcat-sous-texte">{seances.join(", ")}</div>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
