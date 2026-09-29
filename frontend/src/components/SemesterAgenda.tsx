/**
 * Toutes les séances du semestre, semaine par semaine — portage de
 * `renderTeacherAgenda` (page HTML/JS historique), pour les enseignants, les
 * groupes et les matières.
 *
 * Refonte du 29/09/2026 : une LIGNE par séance, colonnes alignées (jour,
 * heure, cours, groupes, salle), au lieu d'un nuage d'étiquettes où chaque
 * information changeait de place d'une étiquette à l'autre. Plus :
 * - filtre par matière (« toutes mes heures de WR107 ») et « à venir
 *   seulement », avec le total d'heures recalculé ;
 * - le titre de chaque semaine ouvre cette semaine dans la grille au-dessus ;
 * - les séances passées sont atténuées, la semaine en cours repérée.
 */

import { useMemo, useState } from "react";

import type { AppPayload } from "../types/app";
import type { IcsSession } from "../utils/ics";
import { couleursMatiere } from "../utils/couleursMatiere";
import { bornesSeance, decouperLibelleSemaine, formatHeures, heuresDe, horaireSeance, jourCourt, pluriel } from "../utils/planning";
import { usePreferences } from "../utils/preferences";
import { DAY_LABELS } from "../utils/slots";
import { groupLabelWithParcours } from "../utils/years";

import "./SemesterAgenda.css";

interface SemesterAgendaProps {
  payload: AppPayload;
  items: IcsSession[];
  /** Préfixe chaque groupe de sa promotion — vrai en Vue Enseignant, où le
   *  même libellé de groupe existe dans plusieurs promotions. */
  showPromo?: boolean;
  /** Ajoute la colonne enseignant (vues Cours et Salle). */
  showProfs?: boolean;
  /** Masque les groupes (vue TD/TP : ce sont les siens). */
  sansGroupes?: boolean;
  /** Clic sur le titre d'une semaine : l'ouvrir dans la grille. */
  onChoisirSemaine?: (solverWeek: number) => void;
  /** Semaine solveur affichée dans la grille, repérée dans la liste. */
  semaineAffichee?: number | null;
  /** Pour les tests : l'heure « actuelle ». */
  maintenant?: Date;
}

export function SemesterAgenda({
  payload,
  items,
  showPromo = false,
  showProfs = false,
  sansGroupes = false,
  onChoisirSemaine,
  semaineAffichee = null,
  maintenant,
}: SemesterAgendaProps) {
  const couleursParMatiere = usePreferences().couleursParMatiere;
  const [matiere, setMatiere] = useState("");
  const [aVenir, setAVenir] = useState(false);
  const now = maintenant ?? new Date();

  const matieres = useMemo(() => {
    const m = new Map<string, { nom: string; n: number; h: number }>();
    for (const it of items) {
      const cur = m.get(it.c) ?? { nom: it.n || it.c, n: 0, h: 0 };
      cur.n += 1;
      cur.h += heuresDe([it]);
      m.set(it.c, cur);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0], "fr"));
  }, [items]);

  if (!items.length) {
    return <p className="muted">Aucune séance placée.</p>;
  }

  const unSeulCours = matieres.length === 1;
  const estPassee = (it: IcsSession) => {
    const b = bornesSeance(it);
    return b ? b.fin <= now : false;
  };
  const visibles = items.filter((it) => (!matiere || it.c === matiere) && (!aVenir || !estPassee(it)));
  const byWeek = new Map<number, IcsSession[]>();
  for (const it of visibles) {
    if (!byWeek.has(it.w)) byWeek.set(it.w, []);
    byWeek.get(it.w)!.push(it);
  }

  return (
    <div className="agenda">
      <div className="agenda-outils">
        <p className="agenda-resume" aria-live="polite">
          <strong>{pluriel(visibles.length, "séance")}</strong> · <strong>{formatHeures(heuresDe(visibles))}</strong> ·{" "}
          {pluriel(byWeek.size, "semaine")}
          {(matiere || aVenir) && <span className="muted"> (sur {formatHeures(heuresDe(items))} au total)</span>}
        </p>
        {matieres.length > 1 && (
          <label className="agenda-filtre">
            <span>Matière</span>
            <select value={matiere} onChange={(e) => setMatiere(e.target.value)}>
              <option value="">Toutes</option>
              {matieres.map(([code, m]) => (
                <option key={code} value={code}>
                  {code} — {m.nom} ({formatHeures(m.h)})
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="agenda-case">
          <input type="checkbox" checked={aVenir} onChange={(e) => setAVenir(e.target.checked)} />À venir seulement
        </label>
      </div>

      {byWeek.size === 0 && <p className="muted">Aucune séance ne correspond.</p>}

      {[...byWeek.entries()]
        .sort((a, b) => a[0] - b[0])
        .map(([w, list]) => {
          const { titre, dates } = decouperLibelleSemaine(payload.weekLabels[w] ?? `Semaine ${w + 1}`);
          const courante = w === semaineAffichee;
          return (
            <section key={w} className={`agenda-semaine${courante ? " is-shown" : ""}`}>
              <h4 className="agenda-semaine-titre">
                {onChoisirSemaine ? (
                  <button
                    type="button"
                    className="agenda-semaine-lien"
                    onClick={() => onChoisirSemaine(w)}
                    title="Afficher cette semaine dans la grille"
                  >
                    {titre}
                    {dates && <span className="agenda-semaine-dates"> · {dates}</span>}
                  </button>
                ) : (
                  <span>
                    {titre}
                    {dates && <span className="agenda-semaine-dates"> · {dates}</span>}
                  </span>
                )}
                {courante && <span className="agenda-semaine-tag">affichée</span>}
                <span className="agenda-semaine-h">{formatHeures(heuresDe(list))}</span>
              </h4>
              <ul
                className={`agenda-lignes${couleursParMatiere ? " couleurs-matiere" : ""}${unSeulCours ? " agenda-lignes--un-cours" : ""}`}
              >
                {list.map((it) => {
                  const groupes = sansGroupes
                    ? ""
                    : showPromo
                      ? groupLabelWithParcours(it.g, payload.groupLabels, payload.groupParcours)
                      : it.g.map((g) => payload.groupLabels[g] ?? g).join(", ");
                  const profs = showProfs ? it.te.map((t) => payload.teacherLabels[t] ?? t).join(", ") : "";
                  return (
                    <li
                      key={it.id}
                      className={`agenda-ligne type-${it.t.toLowerCase()}${it.ev ? " eval" : ""}${estPassee(it) ? " is-past" : ""}`}
                      style={couleursMatiere(it.c) as React.CSSProperties}
                    >
                      <span className="agenda-jour">{it.date ? jourCourt(it.date) : DAY_LABELS[it.d]}</span>
                      <span className="agenda-heure">{horaireSeance(it).libelle}</span>
                      <span className="agenda-cours">
                        {/* Une seule matière (Vue Cours) : son nom répété
                            sur chaque ligne n'apprend rien, le type suffit. */}
                        {unSeulCours ? (
                          <span className="agenda-nom">
                            {it.t}
                            {it.ev ? " · Éval" : ""}
                          </span>
                        ) : (
                          <>
                            <span className="agenda-nom">{it.n || it.c}</span>{" "}
                            <span className="agenda-code">
                              {it.c} · {it.t}
                              {it.ev ? " · Éval" : ""}
                            </span>
                          </>
                        )}
                      </span>
                      <span className="agenda-qui">{[groupes, profs].filter(Boolean).join(" · ")}</span>
                      <span className={`agenda-salle${it.r ? "" : " agenda-salle--absente"}`}>{it.r || "salle à définir"}</span>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}
    </div>
  );
}
