/**
 * Accueil — tableau de bord de la semaine (refonte du 29/09/2026).
 *
 * Répond d'abord à « est-ce que tout va bien cette semaine, et sinon, où
 * dois-je aller ? » : le résumé avant le détail. La semaine est celle de la
 * barre supérieure (partagée par toutes les vues). Chaque chiffre, chaque
 * case et chaque ligne mène à l'écran où l'on agit.
 *
 * Aucune donnée nouvelle : tout vient de `/app-state` (déjà chargé), plus les
 * doublons de la semaine et les tâches ouvertes.
 */

import { useEffect, useMemo, useState } from "react";
import { CalendarRange, Link2, Sparkles, SquarePlus } from "lucide-react";

import { fetchDoublons, fetchTaches, type Doublon, type Tache } from "../api/client";
import { useSemaineGlobale } from "../contexts/SemaineGlobale";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { indexSemaineCourante } from "../utils/semaineCourante";
import { buildTodoList, compterATraiter, libelleQuand, statutsSemaines, trierParUrgence } from "../utils/todo";
import { datesSemaine, nomSemaine } from "../components/TopBar";
import { Tuile } from "../components/Tuile";
import "./AccueilView.css";

const JOURS = ["Lun.", "Mar.", "Mer.", "Jeu.", "Ven."];
const HORAIRES = ["8h", "9h30", "11h", "14h", "15h30", "17h"];

interface AccueilViewProps {
  payload: AppPayload | null;
  setRoute: (r: Partial<Route>) => void;
  estAdmin: boolean;
  peutModifier: boolean;
}

export function AccueilView({ payload, setRoute, peutModifier }: AccueilViewProps) {
  const semaineGlobale = useSemaineGlobale();
  const index = semaineGlobale?.index ?? 0;
  const ligne = payload?.weekRows[index];
  const solverWeek = ligne?.weekIndex ?? null;

  const [doublons, setDoublons] = useState<Doublon[] | null>(null);
  const [taches, setTaches] = useState<Tache[] | null>(null);

  useEffect(() => {
    let actif = true;
    fetchDoublons()
      .then((d) => actif && setDoublons(d))
      .catch(() => actif && setDoublons(null));
    fetchTaches()
      .then((t) => actif && setTaches(t))
      .catch(() => actif && setTaches(null));
    return () => {
      actif = false;
    };
  }, [payload]);

  if (!payload) {
    return (
      <div className="view accueil">
        <p className="empty-state">Chargement du planning…</p>
      </div>
    );
  }

  const doublonsSemaine = (doublons ?? []).filter((d) => d.semaine === solverWeek);
  const compte = compterATraiter(payload, doublons?.length ?? 0);
  const seancesSemaine = solverWeek === null ? 0 : payload.rows.filter((r) => r.w === solverWeek).length;
  const seancesPrecedente =
    solverWeek === null || solverWeek === 0 ? null : payload.rows.filter((r) => r.w === solverWeek - 1).length;
  const nonPlacees = payload.seancesNonPlacees?.length ?? 0;
  const tachesOuvertes = (taches ?? []).filter((t) => t.colonne !== "fait");
  const tachesUrgentes = tachesOuvertes.filter((t) => t.priorite === "urgente");

  return (
    <div className="view accueil">
      <section className="accueil-kpis" aria-label="Indicateurs de la semaine">
        <Tuile
          libelle="Séances cette semaine"
          valeur={ligne?.blocked ? "—" : String(seancesSemaine)}
          detail={
            ligne?.blocked
              ? "Semaine sans cours"
              : seancesPrecedente === null
                ? `${nomSemaine(ligne?.label, index)} · ${datesSemaine(ligne?.monday)}`
                : ecart(seancesSemaine, seancesPrecedente)
          }
          onClick={() => setRoute({ vue: "promo", sem: solverWeek })}
          action="Vue Promo"
        />
        <Tuile
          libelle="À corriger"
          valeur={String(compte.aCorriger)}
          detail={`${Math.max(0, compte.total - compte.aCorriger)} autres points à revoir`}
          ton={compte.aCorriger > 0 ? "bad" : "good"}
          onClick={() => setRoute({ vue: "apf" })}
          action="À traiter"
        />
        <Tuile
          libelle="Doublons cette semaine"
          valeur={doublons === null ? "…" : String(doublonsSemaine.length)}
          detail="Salle ou enseignant pris deux fois"
          ton={doublonsSemaine.length > 0 ? "bad" : "good"}
          onClick={() => setRoute({ vue: "apf" })}
          action="Voir"
        />
        <Tuile
          libelle="Séances non placées"
          valeur={String(nonPlacees)}
          detail="Sans créneau dans le planning"
          ton={nonPlacees > 0 ? "warn" : "good"}
          onClick={() => setRoute({ vue: "promo", panel: "aplacer" })}
          action="Placer"
        />
        <Tuile
          libelle="Tâches ouvertes"
          valeur={taches === null ? "…" : String(tachesOuvertes.length)}
          detail={tachesUrgentes.length ? `dont ${tachesUrgentes.length} urgente${tachesUrgentes.length > 1 ? "s" : ""}` : "Aucune urgente"}
          ton={tachesUrgentes.length > 0 ? "warn" : undefined}
          onClick={() => setRoute({ vue: "taches" })}
          action="Tâches"
        />
      </section>

      <div className="accueil-grille">
        <div className="accueil-principal">
          <ChargeParPromo payload={payload} solverWeek={solverWeek} bloquee={!!ligne?.blocked} setRoute={setRoute} />
          <SemainesAVenir payload={payload} index={index} onChoisir={(i) => semaineGlobale?.setIndex(i)} />
        </div>
        <aside className="accueil-cote">
          <Priorites payload={payload} doublons={doublonsSemaine} setRoute={setRoute} />
          <TachesOuvertes taches={tachesOuvertes} chargees={taches !== null} setRoute={setRoute} />
          <section className="panel accueil-raccourcis" aria-labelledby="accueil-raccourcis-titre">
            <h2 id="accueil-raccourcis-titre">Raccourcis</h2>
            <button type="button" onClick={() => setRoute({ vue: "promo", sem: solverWeek })}>
              <CalendarRange size={16} aria-hidden="true" /> Déplacer des séances cette semaine
            </button>
            {peutModifier && (
              <button type="button" onClick={() => setRoute({ vue: "promo", panel: "aplacer" })}>
                <SquarePlus size={16} aria-hidden="true" /> Placer les séances manquantes
              </button>
            )}
            {peutModifier && (
              <button type="button" onClick={() => setRoute({ vue: "promo", sem: solverWeek })} title="Bouton « Lisser une promo… » de la Vue Promo">
                <Sparkles size={16} aria-hidden="true" /> Lisser le planning d'une promo FC
              </button>
            )}
            <button type="button" onClick={() => setRoute({ vue: "reference" })}>
              <Link2 size={16} aria-hidden="true" /> Liens à envoyer aux enseignants
            </button>
          </section>
        </aside>
      </div>
    </div>
  );
}

function ecart(n: number, avant: number): string {
  const d = n - avant;
  if (d === 0) return "autant que la semaine précédente";
  return `${d > 0 ? "+" : "−"}${Math.abs(d)} par rapport à la semaine précédente`;
}

/** Carte de chaleur promo × jour : créneaux occupés par la promo (au moins un
 * de ses groupes en cours), de 0 à 6. Une seule teinte, plus foncé = plus
 * chargé — on repère d'un coup d'œil les journées pleines et les trous. */
function ChargeParPromo({
  payload,
  solverWeek,
  bloquee,
  setRoute,
}: {
  payload: AppPayload;
  solverWeek: number | null;
  bloquee: boolean;
  setRoute: (r: Partial<Route>) => void;
}) {
  const lignes = useMemo(() => {
    const parcours = [...new Set(Object.values(payload.groupParcours))].filter(Boolean).sort();
    const occupe = new Map<string, Set<number>>(); // `${p}|${jour}` -> créneaux
    const seances = new Map<string, number>();
    if (solverWeek !== null) {
      for (const r of payload.rows) {
        if (r.w !== solverWeek) continue;
        const ps = new Set(r.g.map((g) => payload.groupParcours[g]).filter(Boolean));
        for (const p of ps) {
          const cle = `${p}|${r.d}`;
          const set = occupe.get(cle) ?? new Set<number>();
          for (let k = 0; k < Math.max(1, r.dur); k++) set.add(r.s + k);
          occupe.set(cle, set);
          seances.set(p, (seances.get(p) ?? 0) + 1);
        }
      }
    }
    return parcours.map((p) => {
      const jours = [0, 1, 2, 3, 4].map((d) => [...(occupe.get(`${p}|${d}`) ?? new Set<number>())].sort((a, b) => a - b));
      const heures = jours.reduce((s, j) => s + j.length * 1.5, 0);
      return { parcours: p, jours, heures, seances: seances.get(p) ?? 0 };
    });
  }, [payload, solverWeek]);

  return (
    <section className="panel accueil-charge" aria-labelledby="accueil-charge-titre">
      <header className="accueil-section-tete">
        <h2 id="accueil-charge-titre">Charge de la semaine par promo</h2>
        <Legende />
      </header>
      {bloquee ? (
        <p className="muted">Semaine sans cours (vacances ou fermeture).</p>
      ) : (
        <div className="accueil-charge-table">
          <table>
            <thead>
              <tr>
                <th scope="col">Promo</th>
                {JOURS.map((j) => (
                  <th scope="col" key={j}>
                    {j}
                  </th>
                ))}
                <th scope="col" className="num">
                  Heures
                </th>
              </tr>
            </thead>
            <tbody>
              {lignes.map((l) => (
                <tr key={l.parcours}>
                  <th scope="row">{l.parcours}</th>
                  {l.jours.map((slots, d) => (
                    <td key={d}>
                      <button
                        type="button"
                        className={`accueil-case n${slots.length}`}
                        title={
                          slots.length
                            ? `${l.parcours}, ${JOURS[d]} : ${slots.length} créneau${slots.length > 1 ? "x" : ""} (${slots.map((s) => HORAIRES[s]).join(", ")}) — ouvrir dans la Vue Promo`
                            : `${l.parcours}, ${JOURS[d]} : pas de cours`
                        }
                        onClick={() => setRoute({ vue: "promo", sem: solverWeek, jour: d, parcours: l.parcours })}
                      >
                        <span className="accueil-case-barres" aria-hidden="true">
                          {HORAIRES.map((_, s) => (
                            <i key={s} className={slots.includes(s) ? "on" : ""} />
                          ))}
                        </span>
                        <span className="accueil-case-valeur">{slots.length ? `${slots.length * 1.5} h` : "—"}</span>
                      </button>
                    </td>
                  ))}
                  <td className="num">
                    <strong>{l.heures.toLocaleString("fr-FR")} h</strong>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="accueil-note">
        Chaque case montre les six créneaux de la journée (8h → 17h) : une barre pleine est un créneau occupé. Cliquez pour ouvrir ce jour dans la Vue Promo, filtré sur la promo.
      </p>
    </section>
  );
}

function Legende() {
  return (
    <span className="accueil-legende" aria-label="Légende : de 0 à 6 créneaux occupés">
      0
      {[0, 1, 2, 3, 4, 5, 6].map((n) => (
        <i key={n} className={`accueil-case n${n}`} aria-hidden="true" />
      ))}
      6 créneaux
    </span>
  );
}

/** Séances par semaine, de la semaine affichée aux huit suivantes. Une seule
 * série : la semaine affichée ressort, les autres restent en retrait. */
function SemainesAVenir({
  payload,
  index,
  onChoisir,
}: {
  payload: AppPayload;
  index: number;
  onChoisir: (i: number) => void;
}) {
  const courante = indexSemaineCourante(payload.weekRows);
  const debut = Math.max(0, Math.min(index - 1, payload.weekRows.length - 10));
  const fenetre = payload.weekRows.slice(debut, debut + 10).map((r, k) => {
    const i = debut + k;
    const n = r.weekIndex === null ? 0 : payload.rows.filter((x) => x.w === r.weekIndex).length;
    return { i, r, n };
  });
  const max = Math.max(1, ...fenetre.map((f) => f.n));
  const H = 120;

  return (
    <section className="panel accueil-semaines" aria-labelledby="accueil-semaines-titre">
      <header className="accueil-section-tete">
        <h2 id="accueil-semaines-titre">Séances par semaine</h2>
        <span className="muted small">toutes promos · cliquez une barre pour changer de semaine</span>
      </header>
      <div className="accueil-colonnes" role="list">
        {fenetre.map(({ i, r, n }) => (
          <button
            type="button"
            role="listitem"
            key={r.monday}
            className={`accueil-colonne ${i === index ? "is-choisie" : ""} ${r.blocked ? "is-bloquee" : ""}`}
            onClick={() => onChoisir(i)}
            title={`${nomSemaine(r.label, i)} · ${datesSemaine(r.monday)} : ${r.blocked ? "pas de cours" : `${n} séances`}`}
            aria-pressed={i === index}
          >
            <span className="accueil-colonne-valeur">{r.blocked ? "" : n}</span>
            <span className="accueil-colonne-piste" style={{ height: H }}>
              <span className="accueil-colonne-barre" style={{ height: r.blocked ? 0 : Math.max(2, (n / max) * H) }} />
            </span>
            <span className="accueil-colonne-nom">{nomSemaine(r.label, i).replace("Semaine ", "S")}</span>
            <span className="accueil-colonne-date">{i === courante ? "cette sem." : datesSemaine(r.monday).split(" – ")[0]}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function Priorites({
  payload,
  doublons,
  setRoute,
}: {
  payload: AppPayload;
  doublons: Doublon[];
  setRoute: (r: Partial<Route>) => void;
}) {
  const statuts = statutsSemaines(payload);
  const points = trierParUrgence(
    buildTodoList(payload).filter((i) => i.sev === "bad" && (i.semaine === null || statuts.get(i.semaine) !== "past")),
    statuts,
  ).slice(0, 6);

  return (
    <section className="panel accueil-liste" aria-labelledby="accueil-priorites-titre">
      <header className="accueil-section-tete">
        <h2 id="accueil-priorites-titre">À corriger en priorité</h2>
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => setRoute({ vue: "apf" })}>
          Tout voir
        </button>
      </header>
      {doublons.length > 0 && (
        <button type="button" className="accueil-ligne is-bad" onClick={() => setRoute({ vue: "apf" })}>
          <span className="accueil-ligne-quand">cette semaine</span>
          <span>
            <strong>
              {doublons.length} doublon{doublons.length > 1 ? "s" : ""} cette semaine
            </strong>
            <span className="muted"> salle ou enseignant pris deux fois</span>
          </span>
        </button>
      )}
      {points.length === 0 && doublons.length === 0 ? (
        <p className="muted accueil-vide">Rien à corriger sur les semaines à venir.</p>
      ) : (
        points.map((p) => (
          <button type="button" key={p.cle} className="accueil-ligne is-bad" onClick={() => setRoute(p.route)}>
            <span className="accueil-ligne-quand">{libelleQuand(payload, p) || "sans date"}</span>
            <span className="accueil-ligne-texte">
              <strong>{p.title}</strong>
              {p.n > 1 && <span className="muted"> ×{p.n}</span>}
              <span className="muted"> {p.sub}</span>
            </span>
          </button>
        ))
      )}
    </section>
  );
}

function TachesOuvertes({
  taches,
  chargees,
  setRoute,
}: {
  taches: Tache[];
  chargees: boolean;
  setRoute: (r: Partial<Route>) => void;
}) {
  const triees = [...taches]
    .sort((a, b) => Number(b.priorite === "urgente") - Number(a.priorite === "urgente") || a.ordre - b.ordre)
    .slice(0, 5);
  return (
    <section className="panel accueil-liste" aria-labelledby="accueil-taches-titre">
      <header className="accueil-section-tete">
        <h2 id="accueil-taches-titre">Tâches de l'équipe</h2>
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => setRoute({ vue: "taches" })}>
          Ouvrir
        </button>
      </header>
      {!chargees ? (
        <p className="muted accueil-vide">Chargement…</p>
      ) : triees.length === 0 ? (
        <p className="muted accueil-vide">Aucune tâche ouverte.</p>
      ) : (
        triees.map((t) => (
          <button
            type="button"
            key={t.id}
            className={`accueil-ligne ${t.priorite === "urgente" ? "is-warn" : ""}`}
            onClick={() => setRoute({ vue: "taches" })}
          >
            <span className="accueil-ligne-quand">{t.colonne === "en_cours" ? "en cours" : "à faire"}</span>
            <span className="accueil-ligne-texte">
              <strong>{t.titre}</strong>
              {t.priorite === "urgente" && <span className="pill warn">Urgent</span>}
              {t.concerne && <span className="muted"> · {t.concerne}</span>}
            </span>
          </button>
        ))
      )}
    </section>
  );
}
