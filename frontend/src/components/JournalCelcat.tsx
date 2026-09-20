/**
 * Ce que le worker a réellement écrit dans Celcat, rangé par issue.
 *
 * Des colonnes plutôt qu'une liste chronologique : « 12 échecs sur le même
 * motif » et « 12 incidents distincts » n'appellent pas le même geste, et
 * une liste à plat ne les distinguait pas (retour utilisateur 08/09/2026,
 * « un peu comme un kanban »).
 *
 * Replié par défaut : il répond à « qu'est-ce qui s'est passé ? », une
 * question d'enquête, pas de tous les jours. Le résumé porte quand même les
 * chiffres qui font décider de l'ouvrir — un échec se voit sans cliquer.
 *
 * L'horodatage est écrit dans la ligne. Il ne vivait que dans l'attribut
 * `title`, lisible au survol de la souris et nulle part ailleurs : ni au
 * clavier, ni au doigt.
 */
import type { CelcatLog } from "../api/client";
import { CopyButton } from "./CopyButton";
import { dateLisible, pluriel } from "../utils/celcatStatut";

const COLONNES: Array<{ kind: string; titre: string; ton: string }> = [
  { kind: "created", titre: "Créées", ton: "good" },
  { kind: "modified", titre: "Modifiées", ton: "good" },
  { kind: "deleted", titre: "Supprimées", ton: "" },
  { kind: "echec", titre: "Échecs", ton: "bad" },
  { kind: "blocked", titre: "Bloquées", ton: "bad" },
];

/** Ce qu'on colle dans un message ou un ticket : l'identifiant de séance,
 * l'évènement Celcat pour aller vérifier, le nombre de tentatives, et le
 * motif. Relire à l'écran pour retaper à côté est exactement la friction qui
 * fait qu'un problème n'est pas signalé. */
function texteColonne(titre: string, lignes: CelcatLog[]): string {
  const entete = `${titre} (${lignes.length})`;
  const corps = lignes.map((l) => {
    const morceaux = [l.session_id ?? l.course_code ?? "?"];
    if (l.event_id) morceaux.push(`event_id=${l.event_id}`);
    if (l.repetitions && l.repetitions > 1) morceaux.push(`${l.repetitions} tentatives`);
    if (l.at) morceaux.push(l.at);
    if (l.motif) morceaux.push(l.motif);
    return `- ${morceaux.join(" | ")}`;
  });
  return [entete, ...corps].join("\n");
}

export function JournalCelcat({ logs }: { logs: CelcatLog[] }) {
  const parKind = (kind: string) => logs.filter((l) => l.kind === kind);
  const echecs = parKind("echec").length + parKind("blocked").length;
  const ecrits = parKind("created").length + parKind("modified").length + parKind("deleted").length;

  return (
    <details className="panel celcat-journal" data-testid="journal-celcat">
      <summary>
        <h2>Activité récente</h2>
        <span className="celcat-sous-texte">
          {logs.length === 0 ? (
            "aucune entrée"
          ) : (
            <>
              {pluriel(ecrits, "écriture")}
              {echecs > 0 ? (
                <>
                  {" · "}
                  <span className="celcat-texte-panne">{pluriel(echecs, "échec ou blocage", "échecs ou blocages")}</span>
                </>
              ) : null}{" "}
              sur les {logs.length} dernières entrées
            </>
          )}
        </span>
      </summary>

      {logs.length === 0 ? (
        <p className="celcat-sous-texte">Aucune entrée.</p>
      ) : (
        <div className="celcat-kanban">
          {COLONNES.map((colonne) => {
            const lignes = parKind(colonne.kind);
            return (
              <section key={colonne.kind} className="celcat-kanban-col" data-testid={`colonne-${colonne.kind}`}>
                <div className="celcat-kanban-entete">
                  <h3>
                    {colonne.titre} <span className={`pill ${colonne.ton}`}>{lignes.length}</span>
                  </h3>
                  {lignes.length > 0 ? (
                    <CopyButton
                      text={() => texteColonne(colonne.titre, lignes)}
                      idleLabel="Copier"
                      title={`Copier les ${lignes.length} ligne(s) de « ${colonne.titre} »`}
                    />
                  ) : null}
                </div>
                {lignes.length === 0 ? (
                  <p className="celcat-sous-texte">—</p>
                ) : (
                  <ul className="celcat-journal-list">
                    {lignes.map((item, i) => (
                      <li
                        key={`${item.session_id ?? colonne.kind}-${i}`}
                        className={`celcat-journal-item celcat-journal-item--${colonne.kind}`}
                      >
                        <strong>{item.session_id ?? item.course_code ?? "?"}</strong>
                        {/* Le nombre de tentatives distingue un blocage installé
                            d'un incident isolé. */}
                        {item.repetitions && item.repetitions > 1 ? (
                          <span className="pill bad"> {item.repetitions}× </span>
                        ) : null}
                        {item.event_id ? <span className="celcat-sous-texte"> #{item.event_id}</span> : null}
                        {item.at ? <span className="celcat-sous-texte celcat-horodatage">{dateLisible(item.at)}</span> : null}
                        {item.motif ? <div className="celcat-sous-texte">{item.motif}</div> : null}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            );
          })}
        </div>
      )}
    </details>
  );
}
