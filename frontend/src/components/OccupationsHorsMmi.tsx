/**
 * Écran Celcat → « Occupations hors MMI » (01/10/2026, demande de Kyllian
 * Bresson : « Lecture de Celcat pour vérifier les disponibilités des salles
 * et des enseignants »).
 *
 * Ce que le sidecar a relevé dans Celcat sur NOS salles et NOS enseignants,
 * hors de nos propres évènements : cours d'autres départements, réunions,
 * réservations administratives. Ces occupations bloquent le générateur et
 * sont signalées au placement. L'écran dit QUAND (un relevé ancien reste
 * appliqué), combien par ressource, et laisse filtrer la liste.
 *
 * Replié par défaut, comme l'activité : c'est une question d'enquête
 * (« pourquoi AFR est-il indisponible lundi ? »). Le résumé porte la date du
 * relevé et le nombre d'occupations.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  fetchOccupationsHorsMmi,
  rafraichirOccupationsHorsMmi,
  type OccupationsHorsMmi as Donnees,
} from "../api/client";
import { ageLisible, dateLisible, pluriel } from "../utils/celcatStatut";

const JOURS = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];

function dateCourte(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  const deux = (n: number) => String(n).padStart(2, "0");
  return `${JOURS[d.getDay()]} ${deux(d.getDate())}/${deux(d.getMonth() + 1)}`;
}

export function OccupationsHorsMmi() {
  const [donnees, setDonnees] = useState<Donnees | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [filtre, setFiltre] = useState("");
  const [type, setType] = useState<"" | "salle" | "enseignant">("");
  const [ressource, setRessource] = useState("");

  const charger = useCallback(async () => {
    try {
      setDonnees(await fetchOccupationsHorsMmi());
      setErreur(null);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Relevé illisible.");
    }
  }, []);

  useEffect(() => {
    void charger();
  }, [charger]);

  const evenements = useMemo(() => {
    const texte = filtre.trim().toLowerCase();
    return (donnees?.evenements ?? []).filter((e) => {
      if (type && e.type !== type) return false;
      if (ressource && e.code.toLowerCase() !== ressource.toLowerCase()) return false;
      if (!texte) return true;
      return [e.code, e.libelle, e.departement, e.departement_nom, e.categorie, e.intitule, ...e.groupes]
        .join(" ")
        .toLowerCase()
        .includes(texte);
    });
  }, [donnees, filtre, type, ressource]);

  const relire = async () => {
    try {
      const r = await rafraichirOccupationsHorsMmi();
      setMessage(r.message);
      await charger();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Demande impossible.");
    }
  };

  const total = donnees?.evenements.length ?? 0;
  const VISIBLES = 300;

  return (
    <details className="panel celcat-repliable celcat-occupations" data-testid="occupations-hors-mmi">
      <summary>
        <h2>Occupations hors MMI</h2>
        <span className="celcat-sous-texte">
          {erreur
            ? `illisible : ${erreur}`
            : !donnees
              ? "chargement…"
              : donnees.absent
                ? "aucun relevé — aucune contrainte externe appliquée"
                : `${pluriel(total, "occupation")} · relevé ${dateLisible(donnees.releveLe)}`}
          {donnees?.perime && !donnees.absent ? (
            <span className="celcat-texte-panne"> · relevé ancien ({ageLisible(donnees.ageSecondes)})</span>
          ) : null}
        </span>
      </summary>

      <p className="celcat-aide">
        Ce que Celcat contient sur nos salles et nos enseignants <strong>en dehors de nos évènements</strong> : cours
        d'un autre département, réunion, réservation de l'administration. Le générateur n'utilise pas ces créneaux ;
        au placement, l'appli prévient{donnees?.strict ? " et refuse" : " (« Forcer » reste possible : le relevé peut avoir quelques heures)"}.
        Relevé par le robot Celcat toutes les 2 h.
      </p>

      <div className="celcat-occupations-outils">
        <button type="button" className="btn btn--sm" onClick={() => void relire()} disabled={donnees?.demandeEnCours}>
          {donnees?.demandeEnCours ? "Relecture demandée…" : "Relire maintenant"}
        </button>
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => void charger()}>
          Actualiser l'écran
        </button>
        {message ? <span className="celcat-sous-texte" role="status">{message}</span> : null}
      </div>

      {donnees?.absent ? (
        <p className="celcat-sous-texte" role="status">
          Aucun relevé n'a encore été déposé par le robot (fichier <code>celcat_occupations_externes.json</code> absent) :
          aucune occupation externe n'est prise en compte. Cliquer sur « Relire maintenant », ou lancer
          <code> cal-iut celcat occupations --ecrire-fichier --vpn</code> dans le conteneur celcat-nuit.
        </p>
      ) : null}
      {donnees?.erreur ? (
        <p className="alerte" role="alert">
          Dernière relecture en échec : {donnees.erreur}
          {donnees.releveLe ? " — le relevé précédent reste appliqué." : ""}
        </p>
      ) : null}
      {(donnees?.erreurs ?? []).map((e) => (
        <p key={e} className="celcat-sous-texte celcat-texte-panne">
          {e}
        </p>
      ))}

      {donnees && !donnees.absent ? (
        <>
          <p className="celcat-sous-texte">
            Relevé {dateLisible(donnees.releveLe)} ({ageLisible(donnees.ageSecondes)})
            {donnees.periode?.du ? ` · du ${donnees.periode.du} au ${donnees.periode.au}` : ""}
            {donnees.base ? ` · base ${donnees.base}` : ""}
            {Object.keys(donnees.ignores ?? {}).length
              ? ` · ignorés : ${Object.entries(donnees.ignores)
                  .map(([m, n]) => `${m} × ${n}`)
                  .join(", ")}`
              : ""}
          </p>

          {donnees.conflits.length ? (
            <section className="celcat-occupations-conflits">
              <h3>
                Séances déjà placées en conflit <span className="pill bad">{donnees.conflits.length}</span>
              </h3>
              <ul>
                {donnees.conflits.map((c) => (
                  <li key={`${c.seance_id}-${c.ressource_type}-${c.ressource}`}>
                    <strong className="mono">{c.course_code}</strong> {c.message}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <h3>Ressources surveillées</h3>
          <div className="celcat-occupations-defile">
            <table className="cote-table celcat-occupations-ressources">
              <thead>
                <tr>
                  <th scope="col">Ressource</th>
                  <th scope="col">Dans Celcat</th>
                  <th scope="col" className="num">
                    Occupations
                  </th>
                </tr>
              </thead>
              <tbody>
                {donnees.ressources.map((r) => (
                  <tr key={`${r.type}-${r.code}`}>
                    <td>
                      <button
                        type="button"
                        className="linklike"
                        onClick={() => {
                          setType(r.type);
                          setRessource(r.code);
                        }}
                      >
                        {r.type === "salle" ? "Salle" : "Enseignant"} {r.libelle}
                      </button>{" "}
                      <span className="mono celcat-sous-texte">{r.code}</span>
                    </td>
                    <td>
                      {r.trouvee ? (
                        <span>
                          « {r.celcat} » <span className="celcat-sous-texte">#{r.celcat_id}</span>
                        </span>
                      ) : (
                        <span className="celcat-texte-panne">introuvable (« {r.celcat} »)</span>
                      )}
                    </td>
                    <td className="num">{r.nombre}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3>Occupations</h3>
          <div className="celcat-occupations-filtres">
            <label>
              <span>Rechercher</span>
              <input
                type="search"
                value={filtre}
                onChange={(e) => setFiltre(e.target.value)}
                placeholder="TC, AFR, Amphi, réunion…"
              />
            </label>
            <label>
              <span>Type</span>
              <select value={type} onChange={(e) => setType(e.target.value as "" | "salle" | "enseignant")}>
                <option value="">Salles et enseignants</option>
                <option value="salle">Salles</option>
                <option value="enseignant">Enseignants</option>
              </select>
            </label>
            {ressource ? (
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => setRessource("")}>
                Toutes les ressources (filtre : {ressource})
              </button>
            ) : null}
          </div>
          <p className="celcat-sous-texte" role="status">
            {pluriel(evenements.length, "occupation")}
            {evenements.length > VISIBLES ? ` — ${VISIBLES} premières affichées` : ""}
          </p>
          <div className="celcat-occupations-defile">
            <table className="cote-table celcat-occupations-liste">
              <thead>
                <tr>
                  <th scope="col">Quand</th>
                  <th scope="col">Ressource</th>
                  <th scope="col">Département</th>
                  <th scope="col">Quoi</th>
                </tr>
              </thead>
              <tbody>
                {evenements.slice(0, VISIBLES).map((e, i) => (
                  <tr key={`${e.event_id}-${e.code}-${e.date}-${i}`}>
                    <td>
                      {dateCourte(e.date)} {e.debut}–{e.fin}
                    </td>
                    <td>
                      {e.libelle} <span className="mono celcat-sous-texte">{e.code}</span>
                    </td>
                    <td>{e.departement || <span className="celcat-sous-texte">administration</span>}</td>
                    <td>
                      {[e.categorie, e.intitule].filter(Boolean).join(" · ")}
                      {e.groupes.length ? <span className="celcat-sous-texte"> · {e.groupes.join(", ")}</span> : null}
                      {e.event_id ? <span className="celcat-sous-texte"> · #{e.event_id}</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </details>
  );
}
