/**
 * Les écarts de la semaine, séance par séance.
 *
 * Le rapprochement est fait PAR LE SERVEUR (`celcat/comparaison.py`) : ses
 * règles — matière, groupe, jour, et l'heure avec son décalage de 9'21" dû
 * au fuseau historique de Paris — y sont écrites et testées. Ce composant ne
 * juge rien, il affiche.
 *
 * Refonte du 29/09/2026 : ce n'est plus un repli sous le verdict mais la
 * colonne principale de l'écran, et la valeur qui diffère (heure, salle,
 * jour) est SOULIGNÉE des deux côtés — on n'a plus à comparer deux lignes
 * caractère par caractère pour trouver ce qui change.
 *
 * Chaque verdict porte son MOT dans une pastille : la couleur ne dit jamais
 * seule ce qui se passe.
 */
import { useEffect, useState } from "react";

import type { CelcatComparaison, LigneComparaison } from "../api/client";
import { CopyButton } from "./CopyButton";
import { PILULE, STATUT_LIGNE, jourDate, pluriel } from "../utils/celcatStatut";

function salles(celcat: { salle: string | null; salles: string[] | null }): string {
  const toutes = celcat.salles && celcat.salles.length ? celcat.salles : null;
  return toutes ? toutes.join(" + ") : (celcat.salle ?? "");
}

function texteLignes(lignes: LigneComparaison[], lundi: string | null): string {
  return lignes
    .map((l) => {
      const gauche = l.caliut ? `${jourDate(l.caliut.jour, lundi)} ${l.caliut.heure} ${l.caliut.salle ?? ""}`.trim() : "—";
      const droite = l.celcat
        ? `${jourDate(l.celcat.jour, lundi)} ${l.celcat.heure ?? ""} ${salles(l.celcat)} (event_id=${l.celcat.event_id})`
        : "—";
      return `${STATUT_LIGNE[l.statut].mot} | ${l.session_id || l.course_code} | cal-iut: ${gauche} | Celcat: ${droite}`;
    })
    .join("\n");
}

/** Le serveur nomme les écarts en clair (« heure », « salle », « jour »…) ;
 * on souligne le morceau correspondant. Un nom inconnu ne souligne rien. */
function differe(ecarts: string[], champ: "jour" | "heure" | "salle"): boolean {
  return ecarts.some((e) => e.toLowerCase().includes(champ));
}

function Cote({
  jour,
  heure,
  salle,
  lundi,
  ecarts,
}: {
  jour: number | null | undefined;
  heure: string | null | undefined;
  salle: string;
  lundi: string | null;
  ecarts: string[];
}) {
  const cls = (champ: "jour" | "heure" | "salle") => (differe(ecarts, champ) ? "celcat-diff" : undefined);
  return (
    <div>
      <span className={cls("jour")}>{jourDate(jour, lundi)}</span> <span className={cls("heure")}>{heure ?? ""}</span>
      {salle ? (
        <div>
          <span className={cls("salle")}>{salle}</span>
        </div>
      ) : null}
    </div>
  );
}

export function DetailComparaisonCelcat({ donnees }: { donnees: CelcatComparaison }) {
  const toutes = donnees.lignes ?? [];
  const aAgir = toutes.filter((l) => l.statut !== "identique" && l.statut !== "hors_celcat");
  const identiques = toutes.filter((l) => l.statut === "identique");
  const horsCelcat = toutes.filter((l) => l.statut === "hors_celcat");
  const [voirIdentiques, setVoirIdentiques] = useState(false);

  useEffect(() => {
    // Réinitialisé à CHAQUE semaine, pas à chaque rafraîchissement : refermer
    // une liste qu'on est en train de lire parce qu'une lecture de Celcat est
    // arrivée serait pire que de la laisser ouverte.
    setVoirIdentiques(false);
  }, [donnees.semaine]);

  if (!donnees.releve_le || toutes.length === 0) return null;

  return (
    <section className="panel celcat-detail" aria-labelledby="celcat-detail-titre" data-testid="comparaison-celcat">
      <div className="celcat-panneau-entete">
        <h2 id="celcat-detail-titre">
          Écarts de la semaine <span className="celcat-compte">{aAgir.length}</span>
        </h2>
        <span className="celcat-sous-texte">sur {pluriel(toutes.length, "séance")} comparées</span>
        {aAgir.length > 0 ? (
          <CopyButton text={() => texteLignes(aAgir, donnees.lundi)} idleLabel="Copier les écarts" />
        ) : null}
      </div>

      {aAgir.length > 0 ? (
        <div className="celcat-table-conteneur" tabIndex={0} aria-label="Écarts, défilable horizontalement">
          <table className="ref celcat-table">
            <caption className="sr-only">
              Écarts entre cal-iut et Celcat, semaine du {donnees.lundi ?? donnees.semaine + 1}
            </caption>
            <thead>
              <tr>
                <th scope="col">Verdict</th>
                <th scope="col">Séance</th>
                <th scope="col">Dans cal-iut</th>
                <th scope="col">Dans Celcat</th>
              </tr>
            </thead>
            <tbody>
              {aAgir.map((l, i) => {
                const statut = STATUT_LIGNE[l.statut];
                return (
                  <tr key={`${l.session_id || l.course_code}-${i}`}>
                    <td data-label="Verdict">
                      <span className={`pill ${statut.ton ? PILULE[statut.ton] : ""}`}>{statut.mot}</span>
                      {l.ecarts.length ? <div className="celcat-sous-texte">{l.ecarts.join(", ")}</div> : null}
                    </td>
                    <th scope="row">
                      <span className="celcat-seance-code">{l.course_code || l.session_id}</span>
                      {l.celcat?.groupe ? <div className="celcat-sous-texte">{l.celcat.groupe}</div> : null}
                      {l.session_id ? <div className="celcat-seance-id">{l.session_id}</div> : null}
                    </th>
                    <td data-label="Dans cal-iut">
                      {l.caliut ? (
                        <Cote
                          jour={l.caliut.jour}
                          heure={l.caliut.heure}
                          salle={l.caliut.salle ?? ""}
                          lundi={donnees.lundi}
                          ecarts={l.ecarts}
                        />
                      ) : (
                        <span className="celcat-absent">absente</span>
                      )}
                    </td>
                    <td data-label="Dans Celcat">
                      {l.celcat ? (
                        <div>
                          <Cote
                            jour={l.celcat.jour}
                            heure={l.celcat.heure}
                            salle={salles(l.celcat)}
                            lundi={donnees.lundi}
                            ecarts={l.ecarts}
                          />
                          {l.celcat.event_id ? (
                            <div className="celcat-seance-id">évènement n° {l.celcat.event_id}</div>
                          ) : null}
                        </div>
                      ) : (
                        <span className="celcat-absent">absente</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="celcat-texte-ok">Aucun écart sur cette semaine.</p>
      )}

      <div className="celcat-detail-pied">
        {identiques.length > 0 ? (
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            aria-expanded={voirIdentiques}
            onClick={() => setVoirIdentiques((v) => !v)}
          >
            {voirIdentiques ? "Masquer" : "Afficher"} {pluriel(identiques.length, "séance identique", "séances identiques")}
          </button>
        ) : null}
        {horsCelcat.length > 0 ? (
          <span className="celcat-sous-texte">
            {pluriel(horsCelcat.length, "séance")} sans équivalent dans Celcat (BU, évènements officiels) : ignorée
            {horsCelcat.length > 1 ? "s" : ""}.
          </span>
        ) : null}
      </div>

      {voirIdentiques ? (
        <ul className="celcat-identiques" data-testid="comparaison-identiques">
          {identiques.map((l, i) => (
            <li key={`${l.session_id}-${i}`}>
              <span className="celcat-seance-id">{l.session_id}</span>
              <span className="celcat-sous-texte">
                {jourDate(l.caliut?.jour, donnees.lundi)} {l.caliut?.heure}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
