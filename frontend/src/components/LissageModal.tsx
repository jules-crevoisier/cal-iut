/**
 * Lissage d'une promo (demande du 29/09/2026 sur la 3e année DEV FC : « on
 * ne veut pas de cours de 8h à 9h30 […] les cours commencent à 9h30 », sans
 * trou, journées équilibrées, en vérifiant bien les autres parcours).
 *
 * Trois temps, jamais d'écriture sans accord :
 *   1. choisir la promo et lancer le calcul (tâche de fond, ~1 min 30) ;
 *   2. relire : indicateurs avant/après par semaine et liste des
 *      déplacements, chacun décochable ;
 *   3. appliquer — par le même chemin qu'un glisser-déposer, donc avec les
 *      mêmes contrôles et la même file Celcat.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import {
  appliquerLissage,
  lancerLissage,
  statutLissage,
  type MesureLissage,
  type PropositionLissage,
  type ResultatLissage,
} from "../api/client";
import { confirmAsync } from "../utils/confirmDialog";
import "./LissageModal.css";

/** Promos traitées : un seul groupe de TD/TP (alternance). Le serveur refuse
 * de lui-même les autres, la liste évite juste de les proposer. */
export const PARCOURS_LISSABLES = ["BUT3-DEV-FC", "BUT3-CREACOM-FC", "BUT2-CREACOM-FC"];

interface LissageModalProps {
  parcoursInitial?: string;
  onFermer: () => void;
  /** Appelé après une application (même partielle) : recharger la grille. */
  onApplique: () => void;
}

type Etape = "choix" | "calcul" | "relecture" | "application" | "fini";

const INDICATEURS: { cle: keyof MesureLissage; libelle: string; aide: string }[] = [
  { cle: "cours_8h", libelle: "8h", aide: "Séances à 8h (à éviter : les cours commencent à 9h30)" },
  { cle: "trous", libelle: "Trous", aide: "Créneaux vides entre deux cours d'une même journée" },
  { cle: "cours_17h", libelle: "17h", aide: "Séances à 17h" },
  { cle: "journees_isolees", libelle: "Journées à 1 cours", aide: "Journées avec une seule séance" },
  { cle: "trous_enseignants", libelle: "Trous enseignants", aide: "Attente entre deux cours d'un même enseignant dans la journée, toutes promos confondues" },
];

function total(mesures: MesureLissage[], cle: keyof MesureLissage): number {
  return mesures.reduce((s, m) => s + (typeof m[cle] === "number" ? (m[cle] as number) : 0), 0);
}

export function LissageModal({ parcoursInitial, onFermer, onApplique }: LissageModalProps) {
  const [parcours, setParcours] = useState(
    parcoursInitial && PARCOURS_LISSABLES.includes(parcoursInitial) ? parcoursInitial : PARCOURS_LISSABLES[0],
  );
  const [entreSemaines, setEntreSemaines] = useState(true);
  const [etape, setEtape] = useState<Etape>("choix");
  const [erreur, setErreur] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [proposition, setProposition] = useState<PropositionLissage | null>(null);
  const [exclus, setExclus] = useState<Set<string>>(new Set());
  const [resultat, setResultat] = useState<ResultatLissage | null>(null);
  const [debut, setDebut] = useState<number>(0);
  const [ecoule, setEcoule] = useState(0);
  const titreRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    titreRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && etape !== "application") {
        e.stopPropagation();
        onFermer();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [etape, onFermer]);

  // Sondage du calcul : toutes les 3 s, arrêté dès que la page est quittée.
  useEffect(() => {
    if (etape !== "calcul" || !jobId) return;
    let actif = true;
    const minuteur = window.setInterval(() => {
      setEcoule(Math.round((Date.now() - debut) / 1000));
      statutLissage(jobId)
        .then((s) => {
          if (!actif) return;
          if (s.status === "done" && s.proposition) {
            setProposition(s.proposition);
            setEtape("relecture");
          } else if (s.status === "error") {
            setErreur(s.error ?? "Le calcul a échoué.");
            setEtape("choix");
          }
        })
        .catch(() => {
          /* un sondage raté n'arrête rien : le suivant réessaie */
        });
    }, 3000);
    return () => {
      actif = false;
      window.clearInterval(minuteur);
    };
  }, [etape, jobId, debut]);

  const lancer = async () => {
    setErreur(null);
    try {
      const { job_id } = await lancerLissage(parcours, entreSemaines);
      setJobId(job_id);
      setDebut(Date.now());
      setEcoule(0);
      setEtape("calcul");
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Lancement impossible.");
    }
  };

  const retenus = useMemo(
    () => (proposition?.deplacements ?? []).filter((d) => !exclus.has(d.session_id)),
    [proposition, exclus],
  );

  const appliquer = async () => {
    if (!jobId || !proposition) return;
    const ok = await confirmAsync(
      "Chaque déplacement passe par les mêmes contrôles qu'un glisser-déposer. S'il y a une incompatibilité " +
        "(le planning a changé depuis le calcul), l'application s'arrête là : ce qui est déjà passé reste valide.\n\n" +
        "Les corrections partent ensuite vers Celcat comme d'habitude.",
      { title: `Appliquer ${retenus.length} déplacement${retenus.length > 1 ? "s" : ""} ?`, confirmLabel: "Appliquer" },
    );
    if (!ok) return;
    setEtape("application");
    try {
      const r = await appliquerLissage(jobId, [...exclus]);
      setResultat(r);
      setEtape("fini");
      onApplique();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Application impossible.");
      setEtape("relecture");
    }
  };

  const basculer = (sid: string) =>
    setExclus((prev) => {
      const suivant = new Set(prev);
      if (suivant.has(sid)) suivant.delete(sid);
      else suivant.add(sid);
      return suivant;
    });

  return (
    <div className="confirmmodal-overlay" role="presentation" onClick={etape === "application" ? undefined : onFermer}>
      <div
        className="panel confirmmodal lissage"
        role="dialog"
        aria-modal="true"
        aria-labelledby="lissage-titre"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="lissage-tete">
          <h3 id="lissage-titre" tabIndex={-1} ref={titreRef}>
            Lisser le planning d'une promo
          </h3>
          <button type="button" className="btn btn--ghost btn--sm" onClick={onFermer} disabled={etape === "application"}>
            Fermer
          </button>
        </header>

        {erreur && (
          <p className="lissage-erreur" role="alert">
            {erreur}
          </p>
        )}

        {etape === "choix" && (
          <>
            <p className="muted">
              Réorganise les séances <strong>à venir</strong> de la promo : pas de cours à 8h (on commence à 9h30), pas
              de trou dans la journée, des journées de charge égale, peu de 17h, et le moins de changements possible.
              Seule cette promo bouge : enseignants, salles et règles de toutes les autres promos sont respectés. Rien
              n'est écrit avant votre accord.
            </p>
            <div className="lissage-choix">
              <label>
                Promo
                <select value={parcours} onChange={(e) => setParcours(e.target.value)}>
                  {PARCOURS_LISSABLES.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </label>
              <label className="lissage-case">
                <input type="checkbox" checked={entreSemaines} onChange={(e) => setEntreSemaines(e.target.checked)} />
                Autoriser une ressource à changer de semaine (jamais une SAE)
              </label>
            </div>
            <div className="confirmmodal-actions">
              <button type="button" className="btn" onClick={onFermer}>
                Annuler
              </button>
              <button type="button" className="btn btn--primary" onClick={() => void lancer()}>
                Calculer une proposition
              </button>
            </div>
          </>
        )}

        {etape === "calcul" && (
          <div className="lissage-attente" role="status" aria-live="polite">
            <p>
              Calcul en cours pour <strong>{parcours}</strong>… <span className="muted">{ecoule} s</span>
            </p>
            <p className="muted small">Environ une minute et demie. Vous pouvez laisser cette fenêtre ouverte.</p>
          </div>
        )}

        {(etape === "relecture" || etape === "application") && proposition && (
          <Relecture
            proposition={proposition}
            exclus={exclus}
            onBasculer={basculer}
            onToutCocher={() => setExclus(new Set())}
            onToutDecocher={() => setExclus(new Set(proposition.deplacements.map((d) => d.session_id)))}
          />
        )}

        {(etape === "relecture" || etape === "application") && proposition && (
          <div className="confirmmodal-actions">
            <button type="button" className="btn" onClick={() => setEtape("choix")} disabled={etape === "application"}>
              Recommencer
            </button>
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => void appliquer()}
              disabled={etape === "application" || retenus.length === 0 || proposition.verification.length > 0}
            >
              {etape === "application"
                ? "Application…"
                : `Appliquer ${retenus.length} déplacement${retenus.length > 1 ? "s" : ""}`}
            </button>
          </div>
        )}

        {etape === "fini" && resultat && (
          <div role="status" aria-live="polite">
            {resultat.echec ? (
              <p className="lissage-erreur">
                {resultat.appliques.length} déplacement(s) appliqué(s), puis arrêt sur{" "}
                <span className="mono">{resultat.echec.session_id}</span> : le planning a changé depuis le calcul.{" "}
                {resultat.restants.length} non appliqué(s) — relancez un calcul pour repartir de l'état actuel.
              </p>
            ) : (
              <p>
                <strong>{resultat.appliques.length} déplacement(s) appliqué(s).</strong> Les corrections partent vers
                Celcat comme pour un déplacement à la main.
              </p>
            )}
            <div className="confirmmodal-actions">
              <button type="button" className="btn btn--primary" onClick={onFermer}>
                Fermer
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Relecture({
  proposition,
  exclus,
  onBasculer,
  onToutCocher,
  onToutDecocher,
}: {
  proposition: PropositionLissage;
  exclus: Set<string>;
  onBasculer: (sid: string) => void;
  onToutCocher: () => void;
  onToutDecocher: () => void;
}) {
  const parSemaine = useMemo(() => {
    const m = new Map<number, typeof proposition.deplacements>();
    for (const d of proposition.deplacements) {
      const w = d.vers[0];
      m.set(w, [...(m.get(w) ?? []), d]);
    }
    return m;
  }, [proposition]);
  const apresPar = new Map(proposition.apres.map((m) => [m.semaine, m]));

  return (
    <div className="lissage-relecture">
      <p className="lissage-resume">
        <strong>{proposition.deplacements.length} déplacement(s) proposé(s)</strong> pour {proposition.parcours}
        {proposition.statut === "FEASIBLE" && <span className="muted"> · meilleure solution trouvée dans le temps imparti</span>}
      </p>

      {proposition.verification.length > 0 && (
        <div className="lissage-erreur" role="alert">
          <p>La contre-vérification a trouvé des conflits — proposition non applicable :</p>
          <ul>
            {proposition.verification.map((v) => (
              <li key={v}>{v}</li>
            ))}
          </ul>
        </div>
      )}

      <table className="ref lissage-totaux">
        <thead>
          <tr>
            <th>Sur les semaines à venir</th>
            {INDICATEURS.map((i) => (
              <th key={i.cle} className="num" title={i.aide}>
                {i.libelle}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Avant</td>
            {INDICATEURS.map((i) => (
              <td key={i.cle} className="num">
                {total(proposition.avant, i.cle)}
              </td>
            ))}
          </tr>
          <tr>
            <td>
              <strong>Après</strong>
            </td>
            {INDICATEURS.map((i) => {
              const a = total(proposition.avant, i.cle);
              const b = total(proposition.apres, i.cle);
              return (
                <td key={i.cle} className={`num ${b < a ? "lissage-mieux" : b > a ? "lissage-moins" : ""}`}>
                  <strong>{b}</strong>
                </td>
              );
            })}
          </tr>
        </tbody>
      </table>

      <div className="lissage-outils">
        <span className="muted small">Décochez un déplacement pour le laisser tel quel.</span>
        <button type="button" className="btn btn--ghost btn--sm" onClick={onToutCocher}>
          Tout cocher
        </button>
        <button type="button" className="btn btn--ghost btn--sm" onClick={onToutDecocher}>
          Tout décocher
        </button>
      </div>

      <div className="lissage-liste">
        {proposition.avant.map((avant) => {
          const deps = parSemaine.get(avant.semaine) ?? [];
          const apres = apresPar.get(avant.semaine);
          return (
            <section key={avant.semaine} className="lissage-semaine">
              <h4>
                {avant.libelle}
                <span className="muted small">
                  {" "}
                  · charge/jour {avant.charges.join("·")} → {apres?.charges.join("·") ?? "—"}
                  {apres && apres.seances !== avant.seances ? ` · ${avant.seances} → ${apres.seances} séances` : ""}
                </span>
              </h4>
              {deps.length === 0 ? (
                <p className="muted small">Aucun changement.</p>
              ) : (
                <ul>
                  {deps.map((d) => (
                    <li key={d.session_id} className={exclus.has(d.session_id) ? "lissage-exclu" : ""}>
                      <label>
                        <input
                          type="checkbox"
                          checked={!exclus.has(d.session_id)}
                          onChange={() => onBasculer(d.session_id)}
                        />
                        <span className="mono lissage-code">{d.course_code}</span>
                        <span className="lissage-de">{d.libelle_de}</span>
                        <span aria-hidden="true">→</span>
                        <span className="sr-only">vers</span>
                        <strong className="lissage-vers">{d.libelle_vers}</strong>
                        <span className="muted small">
                          {d.enseignants.join(", ")}
                          {d.salle ? ` · ${d.salle}` : ""}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
