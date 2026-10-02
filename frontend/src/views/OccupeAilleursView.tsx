/**
 * Occupé ailleurs : les salles et les enseignants que Celcat montre pris par
 * d'autres départements ou par l'administration, et les séances MMI déjà
 * placées sur l'une de ces occupations.
 *
 * Née le 02/10/2026 du retour de Jules sur l'écran Celcat → Occupations hors
 * MMI (« illisible, à mettre autre part »). Contrat :
 * `.orchestrator/contract-occupe-ailleurs.md`. Les données viennent de
 * `payload.occupationsExternes` (tous les rôles) ; la carte « Relevé Celcat »,
 * réservée aux administrateurs, charge en plus `fetchOccupationsHorsMmi()`.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";

import {
  fetchOccupationsHorsMmi,
  rafraichirOccupationsHorsMmi,
  type OccupationsHorsMmi,
} from "../api/client";
import { ChampRecherche } from "../components/ChampRecherche";
import { Tuile, Tuiles } from "../components/Tuile";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload, ConflitOccupationExterne, OccupationExterne } from "../types/app";
import { ageLisible, dateLisible, pluriel } from "../utils/celcatStatut";
import {
  annuaireRessources,
  compterDistincts,
  dateCourte,
  filtrerOccupations,
  horaire,
  routeDuConflit,
  trierConflits,
  trierOccupations,
  type LibelleRessource,
  type TypeRessource,
} from "../utils/occupeAilleurs";
import "../styles/outils.css";
import "./OccupeAilleursView.css";

interface OccupeAilleursViewProps {
  payload: AppPayload;
  setRoute: (patch: Partial<Route>) => void;
  estAdmin: boolean;
}

const LIMITE = 200;

type FiltreType = "" | TypeRessource;

interface RessourceChoisie {
  type: TypeRessource;
  code: string;
}

const cleRessource = (r: RessourceChoisie) => `${r.type}:${r.code}`;

export function OccupeAilleursView({ payload, setRoute, estAdmin }: OccupeAilleursViewProps) {
  const externes = payload.occupationsExternes;
  const absent = !externes || externes.absent;
  const occupations = useMemo<OccupationExterne[]>(() => (absent ? [] : externes.occupations), [absent, externes]);
  const conflits = useMemo<ConflitOccupationExterne[]>(
    () => (absent ? [] : trierConflits(externes.conflits)),
    [absent, externes],
  );

  const [texte, setTexte] = useState("");
  const [type, setType] = useState<FiltreType>("");
  const [ressource, setRessource] = useState<RessourceChoisie | null>(null);
  const refConflits = useRef<HTMLElement>(null);

  const libelle = useMemo<LibelleRessource>(() => {
    const salles = new Map(payload.rooms.map((r) => [r.id, r.label]));
    return (t, code) => (t === "salle" ? salles.get(code) : payload.teacherLabels[code]) || code;
  }, [payload.rooms, payload.teacherLabels]);

  const distincts = useMemo(() => compterDistincts(occupations), [occupations]);
  const annuaire = useMemo(() => annuaireRessources(occupations, libelle), [occupations, libelle]);
  const annuaireVisible = annuaire.filter((e) => !type || e.type === type);

  const visibles = useMemo(
    () => trierOccupations(filtrerOccupations(occupations, { type, ressource, texte, libelle })),
    [occupations, type, ressource, texte, libelle],
  );
  const affichees = visibles.slice(0, LIMITE);
  const filtreActif = Boolean(type || ressource || texte.trim());

  const choisirType = (t: FiltreType) => {
    setType(t);
    setRessource(null);
  };
  const basculerType = (t: TypeRessource) => choisirType(type === t ? "" : t);
  const basculerRessource = (r: RessourceChoisie) =>
    setRessource((actuelle) => (actuelle && cleRessource(actuelle) === cleRessource(r) ? null : r));

  const libelleChoisi = ressource ? libelle(ressource.type, ressource.code) : "";

  return (
    <section className="view occupe-ailleurs">
      <Tuiles label="Sommaire des occupations hors MMI">
        <Tuile
          libelle="Séances en conflit"
          valeur={conflits.length}
          detail={conflits.length ? "à déplacer ou à forcer" : "aucune"}
          ton={conflits.length ? "warn" : undefined}
          nul={conflits.length === 0}
          onClick={() => refConflits.current?.scrollIntoView?.({ behavior: "smooth", block: "start" })}
          action="Voir"
        />
        <Tuile
          libelle="Salles prises ailleurs"
          valeur={distincts.salles}
          detail={pluriel(distincts.creneauxSalles, "créneau", "créneaux")}
          nul={distincts.salles === 0}
          onClick={() => basculerType("salle")}
          actif={type === "salle"}
          action={type === "salle" ? "Tout afficher" : "Filtrer"}
        />
        <Tuile
          libelle="Enseignants pris ailleurs"
          valeur={distincts.enseignants}
          detail={pluriel(distincts.creneauxEnseignants, "créneau", "créneaux")}
          nul={distincts.enseignants === 0}
          onClick={() => basculerType("enseignant")}
          actif={type === "enseignant"}
          action={type === "enseignant" ? "Tout afficher" : "Filtrer"}
        />
        <Tuile
          libelle="Dernier relevé Celcat"
          valeur={absent ? "—" : ageLisible(externes.ageSecondes)}
          detail={absent ? "aucun relevé : rien n'est appliqué" : dateLisible(externes.releveLe)}
          ton={!absent && externes.perime ? "warn" : undefined}
        />
      </Tuiles>

      {!absent && externes.perime && (
        <p className="banner banner--info occ-bandeau">
          {`Relevé ancien (${ageLisible(externes.ageSecondes)}) : les occupations restent appliquées telles quelles.`}
        </p>
      )}

      {absent ? (
        <div className="empty-state">
          <p>Aucun relevé Celcat pour l'instant.</p>
          <p>Rien n'est pris en compte.</p>
        </div>
      ) : (
        <>
          <section className="panel carte-tableau occ-panneau" aria-labelledby="occ-conflits" ref={refConflits}>
            <div className="carte-tete">
              <h2 id="occ-conflits">
                Séances placées sur une occupation <span className="carte-tete-nb">{conflits.length}</span>
              </h2>
            </div>
            {conflits.length === 0 ? (
              <p className="carte-vide">Aucune séance placée n'est en conflit avec une occupation hors MMI.</p>
            ) : (
              <table className="ref occ-table">
                <thead>
                  <tr>
                    <th scope="col">Séance</th>
                    <th scope="col">Quand</th>
                    <th scope="col">Bloqué par</th>
                    <th scope="col">Occupé par</th>
                    <th scope="col">
                      <span className="sr-only">Action</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {conflits.map((c) => (
                    <LigneConflit
                      key={`${c.seance_id}-${c.ressource_type}-${c.ressource}`}
                      conflit={c}
                      groupes={c.groupes.map((g) => payload.groupLabels[g] ?? g)}
                      libelle={libelle}
                      ouvrir={() => setRoute(routeDuConflit(c))}
                    />
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="panel carte-tableau carte-tableau--haute occ-panneau" aria-labelledby="occ-pris">
            <div className="carte-tete">
              <h2 id="occ-pris">
                Salles et enseignants pris ailleurs <span className="carte-tete-nb">{visibles.length}</span>
              </h2>
              <div className="pastilles" role="group" aria-label="Type de ressource">
                <button type="button" className="pastille" aria-pressed={type === ""} onClick={() => choisirType("")}>
                  Tout
                </button>
                <button
                  type="button"
                  className="pastille"
                  aria-pressed={type === "salle"}
                  onClick={() => choisirType("salle")}
                >
                  Salles
                </button>
                <button
                  type="button"
                  className="pastille"
                  aria-pressed={type === "enseignant"}
                  onClick={() => choisirType("enseignant")}
                >
                  Enseignants
                </button>
              </div>
              {ressource && (
                <button type="button" className="pastille" aria-pressed="true" onClick={() => setRessource(null)}>
                  {libelleChoisi}
                  <X size={13} aria-hidden="true" />
                  <span className="sr-only">(retirer le filtre)</span>
                </button>
              )}
              <div className="carte-tete-actions">
                <ChampRecherche
                  className="occ-recherche"
                  placeholder="Filtrer : salle, enseignant, département…"
                  libelle="Filtrer les occupations"
                  valeur={texte}
                  onChange={setTexte}
                />
              </div>
            </div>

            <div className="occ-corps">
              <label className="occ-select">
                <span>Ressource</span>
                <select
                  value={ressource ? cleRessource(ressource) : ""}
                  onChange={(e) => {
                    const valeur = e.target.value;
                    if (!valeur) return setRessource(null);
                    const entree = annuaire.find((x) => cleRessource(x) === valeur);
                    if (entree) basculerRessource({ type: entree.type, code: entree.code });
                  }}
                >
                  <option value="">Toutes les ressources</option>
                  {annuaireVisible.map((e) => (
                    <option key={cleRessource(e)} value={cleRessource(e)}>
                      {e.libelle} ({e.nombre})
                    </option>
                  ))}
                </select>
              </label>

              <ul className="occ-annuaire" aria-label="Ressources prises ailleurs">
                {annuaireVisible.map((e) => {
                  const actif = ressource ? cleRessource(ressource) === cleRessource(e) : false;
                  return (
                    <li key={cleRessource(e)}>
                      <button
                        type="button"
                        className="occ-annuaire-ligne"
                        aria-pressed={actif}
                        onClick={() => basculerRessource({ type: e.type, code: e.code })}
                      >
                        <span className="occ-annuaire-nom">
                          {e.libelle} <span className="mono occ-code">{e.code}</span>
                        </span>
                        <span className="occ-annuaire-nb">{e.nombre}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>

              <div className="occ-liste">
                {visibles.length === 0 ? (
                  <p className="carte-vide">
                    {filtreActif
                      ? "Aucune occupation ne correspond à ce filtre."
                      : "Aucune salle ni aucun enseignant n'est pris ailleurs."}
                  </p>
                ) : (
                  <table className="ref occ-table">
                    <thead>
                      <tr>
                        <th scope="col">Date</th>
                        <th scope="col">Horaire</th>
                        {!ressource && <th scope="col">Ressource</th>}
                        <th scope="col">Département</th>
                        <th scope="col">Quoi</th>
                      </tr>
                    </thead>
                    <tbody>
                      {affichees.map((o, i) => (
                        <tr key={`${o.t}-${o.code}-${o.date}-${o.debut}-${i}`}>
                          <td data-label="Date">{dateCourte(o.date)}</td>
                          <td data-label="Horaire">{horaire(o.debut, o.fin)}</td>
                          {!ressource && (
                            <td data-label="Ressource">
                              <span>{libelle(o.t, o.code)}</span> <span className="mono occ-code">{o.code}</span>
                            </td>
                          )}
                          <td data-label="Département">{o.dep || "Administration"}</td>
                          <td data-label="Quoi">{o.lib || o.cat}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {visibles.length > LIMITE && (
                  <p className="carte-note">{LIMITE} premières affichées — préciser le filtre.</p>
                )}
              </div>
            </div>
          </section>
        </>
      )}

      {estAdmin && <CarteReleve />}
    </section>
  );
}

function LigneConflit({
  conflit: c,
  groupes,
  libelle,
  ouvrir,
}: {
  conflit: ConflitOccupationExterne;
  groupes: string[];
  libelle: LibelleRessource;
  ouvrir: () => void;
}) {
  const detailSeance = [c.type, groupes.join(", ")].filter(Boolean).join(" · ");
  const complet = Boolean(c.date && c.debut && c.fin);
  return (
    <tr>
      <td data-label="Séance">
        <span className="mono occ-seance-code">{c.course_code}</span> {c.nom}
        {detailSeance && <span className="occ-doux">{detailSeance}</span>}
      </td>
      {complet ? (
        <>
          <td data-label="Quand">
            <span className="occ-bloc">{dateCourte(c.date ?? "")}</span>
            <span className="occ-bloc">{horaire(c.debut ?? "", c.fin ?? "")}</span>
          </td>
          <td data-label="Bloqué par">
            <span className="pill">{c.ressource_type === "salle" ? "Salle" : "Enseignant"}</span>{" "}
            <span>{c.ressource_libelle || libelle(c.ressource_type, c.ressource)}</span>
          </td>
          <td data-label="Occupé par">
            <span className="occ-bloc">{c.departement || "Administration"}</span>
            <span className="occ-doux">{c.intitule || c.categorie}</span>
          </td>
        </>
      ) : (
        <td colSpan={3} data-label="Occupation">
          {c.message}
        </td>
      )}
      <td className="occ-action">
        <button type="button" className="btn btn--sm" aria-label={`Ouvrir ${c.course_code}`} onClick={ouvrir}>
          Ouvrir
        </button>
      </td>
    </tr>
  );
}

function jourFr(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? "");
  return m ? `${m[3]}/${m[2]}/${m[1]}` : (iso ?? "");
}

/** Carte réservée aux administrateurs : état du relevé, relecture à la
 *  demande, ressources introuvables et motifs d'écart. */
function CarteReleve() {
  const [donnees, setDonnees] = useState<OccupationsHorsMmi | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

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

  const relire = async () => {
    setEnvoi(true);
    try {
      const r = await rafraichirOccupationsHorsMmi();
      setMessage(r.message);
      await charger();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Demande impossible.");
    } finally {
      setEnvoi(false);
    }
  };

  const introuvables = (donnees?.ressources ?? []).filter((r) => !r.trouvee);
  const ecartes = Object.entries(donnees?.ignores ?? {});

  return (
    <section className="panel occ-releve" aria-labelledby="occ-releve">
      <div className="carte-tete">
        <h2 id="occ-releve">Relevé Celcat</h2>
        <div className="carte-tete-actions">
          <button
            type="button"
            className="btn btn--sm"
            onClick={() => void relire()}
            disabled={envoi || donnees?.demandeEnCours || donnees?.lectureActive === false}
          >
            {donnees?.demandeEnCours ? "Relecture demandée…" : "Relire maintenant"}
          </button>
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => void charger()}>
            Actualiser
          </button>
        </div>
      </div>

      <div className="occ-releve-corps">
        {message && (
          <p className="occ-etat" role="status">
            {message}
          </p>
        )}

        {erreur && <p className="banner banner--error occ-bandeau" role="alert">{`Relevé illisible : ${erreur}`}</p>}
        {!donnees && !erreur && <p className="occ-etat">Lecture du relevé…</p>}

        {donnees?.lectureActive === false && (
          <p className="occ-etat" role="status">
            Lecture <strong>coupée</strong> (<code>actif: false</code> dans <code>data/config/celcat_occupations.yaml</code>) :
            le robot ne relève rien. Passer à <code>actif: true</code> et redéployer après les essais
            (docs/A-TESTER-SUR-CELCAT.md).
          </p>
        )}
        {donnees?.absent && (
          <p className="occ-etat" role="status">
            Aucun relevé n'a encore été déposé par le robot (fichier <code>celcat_occupations_externes.json</code> absent) :
            aucune occupation externe n'est prise en compte. Cliquer sur « Relire maintenant », ou lancer{" "}
            <code>cal-iut celcat occupations --ecrire-fichier --vpn</code> dans le conteneur celcat-nuit.
          </p>
        )}
        {donnees?.erreur && (
          <p className="banner banner--error occ-bandeau" role="alert">
            Dernière relecture en échec : {donnees.erreur}
            {donnees.releveLe ? " — le relevé précédent reste appliqué." : ""}
          </p>
        )}
        {(donnees?.erreurs ?? []).map((e) => (
          <p key={e} className="occ-etat">
            {e}
          </p>
        ))}

        {donnees && !donnees.absent && (
          <p className="occ-etat">
            {`Relevé ${dateLisible(donnees.releveLe)} (${ageLisible(donnees.ageSecondes)})`}
            {donnees.periode?.du ? ` · du ${jourFr(donnees.periode.du)} au ${jourFr(donnees.periode.au)}` : ""}
            {donnees.base ? ` · base ${donnees.base}` : ""}
          </p>
        )}

        {introuvables.length > 0 && (
          <div className="occ-bloc-releve">
            <h3>Introuvables dans Celcat</h3>
            <p className="occ-etat">Pas de fiche dans Celcat cette année : leurs occupations ne peuvent pas être lues.</p>
            <ul className="occ-introuvables">
              {introuvables.map((r) => (
                <li key={`${r.type}-${r.code}`}>
                  <strong>{r.libelle}</strong> <span className="mono occ-code">{r.celcat}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {ecartes.length > 0 && (
          <div className="occ-bloc-releve">
            <h3>Écartés du relevé</h3>
            <table className="ref occ-ecartes">
              <thead>
                <tr>
                  <th scope="col">Motif</th>
                  <th scope="col" className="num">
                    Nombre
                  </th>
                </tr>
              </thead>
              <tbody>
                {ecartes.map(([motif, n]) => (
                  <tr key={motif}>
                    <td>{motif}</td>
                    <td className="num">{n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
