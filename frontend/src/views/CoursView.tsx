/**
 * Vue Cours — une ressource ou une SAE : sa maquette (volumes par
 * parcours), qui l'enseigne, où, puis sa grille de la semaine et toutes ses
 * séances du semestre. La recherche atterrit ici plutôt que sur une Vue
 * Semaine non filtrée.
 *
 * Refonte du 29/09/2026 : sélecteur de matière (on pouvait arriver ici sans
 * pouvoir en changer), fiche en deux colonnes, et la liste de toutes les
 * séances du semestre — c'est ce que promet le titre de l'onglet.
 */

import { useMemo } from "react";

import { FicheIntrouvable } from "../components/FicheIntrouvable";
import { NavSemaine } from "../components/NavSemaine";
import { PlanningSemaine } from "../components/PlanningSemaine";
import { SemesterAgenda } from "../components/SemesterAgenda";
import { useConsultation } from "../hooks/useConsultation";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { sessionsWithDates } from "../utils/ics";
import { formatHeures, heuresDe, pluriel } from "../utils/planning";

import "./fiches.css";

interface CoursViewProps {
  payload: AppPayload;
  route: Route;
  setRoute: (patch: Partial<Route>) => void;
  onOpenSearch?: () => void;
}

export function CoursView({ payload, route, setRoute, onOpenSearch }: CoursViewProps) {
  const code = route.cours;
  const c = useConsultation(payload, route.sem);
  const codes = useMemo(() => {
    const m = new Map<string, string>();
    for (const e of payload.courses) if (!m.has(e.code)) m.set(e.code, e.name);
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0], "fr"));
  }, [payload.courses]);
  const allItems = useMemo(
    () => sessionsWithDates(payload, payload.rows.filter((r) => r.c === code)),
    [payload, code],
  );

  const choix = (
    <label className="fiche-choix">
      <span>Matière</span>
      <select value={code} onChange={(e) => setRoute({ vue: "cours", cours: e.target.value })}>
        {!code && <option value="">Choisir une matière…</option>}
        {codes.map(([cc, nom]) => (
          <option key={cc} value={cc}>
            {cc} — {nom}
          </option>
        ))}
      </select>
    </label>
  );

  // Onglet ouvert sans matière : proposer d'en choisir une plutôt que
  // « introuvable », réservé à un code demandé mais inconnu.
  if (!code && codes.length) {
    return (
      <section className="view fiche">
        <div className="fiche-entete">{choix}</div>
        <p className="empty-state">Choisissez une matière, ou cherchez-la avec Ctrl+K.</p>
      </section>
    );
  }
  const entrees = payload.courses.filter((e) => e.code === code);
  if (!code || entrees.length === 0) {
    return <FicheIntrouvable libelle="Matière" id={code || "?"} onOpenSearch={onOpenSearch} />;
  }

  const rowsThisWeek = c.solverWeek === null ? [] : allItems.filter((r) => r.w === c.solverWeek);
  const hoursByWeek = new Map<number, number>();
  for (const it of allItems) hoursByWeek.set(it.w, (hoursByWeek.get(it.w) ?? 0) + heuresDe([it]));

  const nom = entrees[0]?.name ?? code;
  const teachers = [...new Set([...entrees.flatMap((e) => e.teachers), ...allItems.flatMap((r) => r.te)])];
  const groupes = [...new Set(allItems.flatMap((r) => r.g))];
  const salles = [...new Set(allItems.map((r) => r.r).filter(Boolean))];
  const manquantes = (payload.seancesNonPlacees ?? []).filter((s) => s.code === code);
  const nPlaced = entrees.reduce((n, e) => n + e.nPlaced, 0);
  const salleParLabel = new Map(payload.rooms.map((r) => [r.label, r.id]));

  return (
    <section className="view fiche">
      <div className="fiche-entete">
        {choix}
        <p className="fiche-identite">
          <strong>{nom}</strong>
          <span>
            {pluriel(nPlaced, "séance placée", "séances placées")} · {formatHeures(heuresDe(allItems))}
          </span>
          {manquantes.length > 0 && (
            <span className="fiche-manque">{pluriel(manquantes.length, "non placée", "non placées")}</span>
          )}
        </p>
      </div>

      <div className="panel fiche-infos">
        <div className="ref-table-wrap">
          <table className="ref">
            <thead>
              <tr>
                <th>Parcours</th>
                <th>Semestre</th>
                <th className="num">CM</th>
                <th className="num">TD</th>
                <th className="num">TP</th>
                <th className="num">Éval</th>
                <th className="num">Placées</th>
                <th>Progression</th>
              </tr>
            </thead>
            <tbody>
              {entrees.map((e) => (
                <tr key={`${e.code}-${e.parcours}`}>
                  <td>{e.parcours || "—"}</td>
                  <td>{e.semestre}</td>
                  <td className="num">{e.nCM}</td>
                  <td className="num">{e.nTD}</td>
                  <td className="num">{e.nTP}</td>
                  <td className="num">{e.nEval}</td>
                  <td className="num">{e.nPlaced}</td>
                  <td>{e.progressionDefined ? "définie" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <dl className="fiche-dl">
          {teachers.length > 0 && (
            <>
              <dt>Enseignants</dt>
              <dd>
                {teachers.map((t, i) => (
                  <span key={t}>
                    {i > 0 ? ", " : null}
                    <button type="button" className="linklike" onClick={() => setRoute({ vue: "prof", prof: t })}>
                      {payload.teacherLabels[t] ?? t}
                    </button>
                  </span>
                ))}
              </dd>
            </>
          )}
          {groupes.length > 0 && (
            <>
              <dt>Groupes</dt>
              <dd>
                {groupes.map((g, i) => (
                  <span key={g}>
                    {i > 0 ? ", " : null}
                    <button type="button" className="linklike" onClick={() => setRoute({ vue: "groupe", groupe: g })}>
                      {payload.groupParcours[g] ? `${payload.groupParcours[g]} ` : ""}
                      {payload.groupLabels[g] ?? g}
                    </button>
                  </span>
                ))}
              </dd>
            </>
          )}
          {salles.length > 0 && (
            <>
              <dt>Salles</dt>
              <dd>
                {salles.map((s, i) => (
                  <span key={s}>
                    {i > 0 ? ", " : null}
                    {salleParLabel.has(s) ? (
                      <button type="button" className="linklike" onClick={() => setRoute({ vue: "salle", salle: salleParLabel.get(s) })}>
                        {s}
                      </button>
                    ) : (
                      s
                    )}
                  </span>
                ))}
              </dd>
            </>
          )}
          {entrees.some((e) => e.ordonnancement.length > 0) && (
            <>
              <dt>Ordonnancement</dt>
              <dd>
                <ul className="cote-liste">
                  {entrees.flatMap((e) =>
                    e.ordonnancement.map((o, i) => (
                      <li key={`${e.parcours}-${i}`}>
                        {e.parcours} : {o.position} → {o.target}
                      </li>
                    )),
                  )}
                </ul>
              </dd>
            </>
          )}
          {manquantes.length > 0 && (
            <>
              <dt className="fiche-manque">Non placées</dt>
              <dd>
                <ul className="cote-liste">
                  {manquantes.map((s) => (
                    <li key={s.id}>
                      {s.type} · {s.groupes.join(", ")} · {s.profs.join(", ")}
                    </li>
                  ))}
                </ul>
              </dd>
            </>
          )}
        </dl>
      </div>

      <NavSemaine
        weekRows={payload.weekRows}
        selected={c.displayWeek}
        onSelect={c.setDisplayWeek}
        countByWeekIndex={hoursByWeek}
        onAujourdhui={c.narrow ? c.jourAujourdhui : undefined}
        resume={c.solverWeek !== null && <strong>{formatHeures(hoursByWeek.get(c.solverWeek) ?? 0)} cette semaine</strong>}
      />

      <div className="fiche-corps">
        <div className="fiche-grille" id="planning">
          <PlanningSemaine
            payload={payload}
            rows={rowsThisWeek}
            displayIndex={c.displayWeek}
            onSelectWeek={c.setDisplayWeek}
            showPromo
            narrow={c.narrow}
            jour={c.jour}
            onJour={c.setJour}
            titreImpression={`${code} — ${nom}`}
            videLibelle="Aucune séance de cette matière cette semaine."
          />
        </div>
      </div>

      <section className="panel fiche-semestre">
        <h3>Toutes les séances du semestre</h3>
        <SemesterAgenda
          payload={payload}
          items={allItems}
          showPromo
          showProfs
          semaineAffichee={c.solverWeek}
          onChoisirSemaine={(w) => c.allerA(w)}
        />
      </section>
    </section>
  );
}
