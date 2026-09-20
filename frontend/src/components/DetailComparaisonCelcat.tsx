/**
 * Le détail séance par séance, pour qui veut vérifier ligne à ligne.
 *
 * Le rapprochement est fait PAR LE SERVEUR (`celcat/comparaison.py`) : ses
 * règles — matière, groupe, jour, et l'heure avec son décalage de 9'21" dû
 * au fuseau historique de Paris — y sont écrites et testées. Ce composant ne
 * juge rien, il affiche.
 *
 * Replié sous le verdict : il répond à « lesquelles ? », pas à « est-ce que
 * ça va ? ». Il s'ouvre de lui-même quand il y a des écarts, parce qu'alors
 * c'est précisément la question suivante.
 *
 * Chaque verdict porte son MOT dans une pastille distincte. Le liseré de
 * couleur à gauche des lignes, seul à distinguer « à modifier » de « en
 * trop », a disparu : la couleur ne dit jamais seule ce qui se passe.
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

export function DetailComparaisonCelcat({ donnees }: { donnees: CelcatComparaison }) {
  const toutes = donnees.lignes ?? [];
  const aAgir = toutes.filter((l) => l.statut !== "identique" && l.statut !== "hors_celcat");
  const identiques = toutes.filter((l) => l.statut === "identique");
  const horsCelcat = toutes.filter((l) => l.statut === "hors_celcat");
  const [ouvert, setOuvert] = useState(aAgir.length > 0);
  const [voirIdentiques, setVoirIdentiques] = useState(false);

  useEffect(() => {
    setOuvert(aAgir.length > 0);
    setVoirIdentiques(false);
    // Réinitialisé à CHAQUE semaine, pas à chaque rafraîchissement : refermer
    // un détail qu'on est en train de lire parce qu'un relevé est arrivé
    // serait pire que de le laisser ouvert.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [donnees.semaine]);

  if (!donnees.releve_le || toutes.length === 0) return null;

  return (
    <details
      className="panel celcat-detail"
      open={ouvert}
      onToggle={(e) => setOuvert((e.currentTarget as HTMLDetailsElement).open)}
      data-testid="comparaison-celcat"
    >
      <summary>
        <h2>Détail séance par séance</h2>
        <span className="celcat-sous-texte">
          {pluriel(aAgir.length, "écart")} sur {pluriel(toutes.length, "séance")}
        </span>
      </summary>

      {aAgir.length > 0 ? (
        <>
          <div className="celcat-actions">
            <CopyButton text={() => texteLignes(aAgir, donnees.lundi)} idleLabel="Copier les écarts" />
          </div>
          <div className="celcat-table-conteneur" tabIndex={0} aria-label="Écarts, défilable horizontalement">
            <table className="comparaison-table">
              <caption className="sr-only">
                Écarts entre cal-iut et Celcat, semaine du {donnees.lundi ?? donnees.semaine + 1}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Séance</th>
                  <th scope="col">Verdict</th>
                  <th scope="col">cal-iut</th>
                  <th scope="col">Celcat</th>
                </tr>
              </thead>
              <tbody>
                {aAgir.map((l, i) => {
                  const statut = STATUT_LIGNE[l.statut];
                  return (
                    <tr key={`${l.session_id || l.course_code}-${i}`}>
                      <th scope="row">{l.session_id || l.course_code}</th>
                      <td>
                        <span className={`pill ${statut.ton ? PILULE[statut.ton] : ""}`}>{statut.mot}</span>
                        {l.ecarts.length ? <span className="celcat-sous-texte"> {l.ecarts.join(", ")}</span> : null}
                      </td>
                      <td>
                        {l.caliut
                          ? `${jourDate(l.caliut.jour, donnees.lundi)} ${l.caliut.heure}${l.caliut.salle ? ` — ${l.caliut.salle}` : ""}`
                          : "—"}
                      </td>
                      <td>
                        {l.celcat
                          ? `${jourDate(l.celcat.jour, donnees.lundi)} ${l.celcat.heure ?? ""}${salles(l.celcat) ? ` — ${salles(l.celcat)}` : ""}`
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="celcat-sous-texte">Aucun écart sur cette semaine.</p>
      )}

      {horsCelcat.length > 0 ? (
        <p className="celcat-sous-texte">
          {pluriel(horsCelcat.length, "séance")} sans équivalent dans Celcat (BU, évènements officiels) : ignorée
          {horsCelcat.length > 1 ? "s" : ""}.
        </p>
      ) : null}

      {identiques.length > 0 ? (
        <>
          <button
            type="button"
            className="btn btn--ghost"
            aria-expanded={voirIdentiques}
            onClick={() => setVoirIdentiques((v) => !v)}
          >
            {voirIdentiques ? "Masquer" : "Afficher"} {pluriel(identiques.length, "séance identique", "séances identiques")}
          </button>
          {voirIdentiques ? (
            <ul className="celcat-liste" data-testid="comparaison-identiques">
              {identiques.map((l, i) => (
                <li key={`${l.session_id}-${i}`} className="celcat-liste-ligne">
                  <span>{l.session_id}</span>
                  <span className="celcat-sous-texte">
                    {jourDate(l.caliut?.jour, donnees.lundi)} {l.caliut?.heure}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </details>
  );
}
