/**
 * Vue Cours — une ressource ou une SAE : sa maquette (volumes par
 * parcours), qui l'enseigne, où, puis sa grille de la semaine et toutes ses
 * séances du semestre. La recherche atterrit ici plutôt que sur une Vue
 * Semaine non filtrée.
 *
 * Refonte v2 du 29/09/2026 (cf. docs/DESIGN.md « Gabarit de page ») : sans
 * matière choisie, l'annuaire des matières par parcours et semestre, avec le
 * volume placé et les heures de la semaine partagée ; la fiche suit le
 * gabarit commun, la maquette et les intervenants passent dans la colonne
 * de contexte à droite de la grille.
 */

import { useMemo } from "react";

import { FicheIdentite, FicheOutils } from "../components/FicheEntete";
import { ModifierIntituleCours } from "../components/ValeursReference";
import { FicheIntrouvable } from "../components/FicheIntrouvable";
import { NavSemaine } from "../components/NavSemaine";
import { PlanningSemaine } from "../components/PlanningSemaine";
import { ProchainCours } from "../components/ProchainCours";
import { SemesterAgenda } from "../components/SemesterAgenda";
import { useConsultation } from "../hooks/useConsultation";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { sessionsWithDates } from "../utils/ics";
import { decouperLibelleSemaine, formatHeures, heuresDe, pluriel } from "../utils/planning";
import { AnnuaireCours } from "./Annuaires";

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
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0], "fr", { numeric: true }));
  }, [payload.courses]);
  const allItems = useMemo(
    () => sessionsWithDates(payload, payload.rows.filter((r) => r.c === code)),
    [payload, code],
  );

  // Onglet ouvert sans matière : l'annuaire ; « introuvable » reste réservé
  // à un code demandé mais inconnu.
  if (!code && codes.length) {
    return (
      <section className="view fiche fiche--annuaire">
        <AnnuaireCours
          payload={payload}
          displayWeek={c.displayWeek}
          onOuvrir={(cc) => setRoute({ vue: "cours", cours: cc })}
        />
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
  const nPrevues = entrees.reduce((n, e) => n + e.nCM + e.nTD + e.nTP + e.nEval, 0);
  const salleParLabel = new Map(payload.rooms.map((r) => [r.label, r.id]));
  const titreSemaine = decouperLibelleSemaine(payload.weekRows[c.displayWeek]?.label ?? "").titre;

  return (
    <section className="view fiche">
      <FicheOutils
        libelle="Matière"
        valeur={code}
        options={codes.map(([cc, n]) => ({ value: cc, label: `${cc} — ${n}` }))}
        onChoisir={(cc) => setRoute({ vue: "cours", cours: cc })}
        onAnnuaire={() => setRoute({ vue: "cours", cours: "" })}
      />

      <FicheIdentite
        titre={nom}
        // Intitulé corrigeable dans l'appli (29/09/2026) — marqué s'il l'est.
        titreAction={
          <ModifierIntituleCours code={code} intitule={nom} surcharge={payload.surchargesReference?.cours?.[code]?.intitule} />
        }
        faits={[
          <span className="mono">{code}</span>,
          [...new Set(entrees.map((e) => [e.parcours, e.semestre].filter(Boolean).join(" · ")))].join(", "),
          c.solverWeek !== null && (
            <>
              <strong>{formatHeures(hoursByWeek.get(c.solverWeek) ?? 0)}</strong> en {titreSemaine.toLowerCase()}
            </>
          ),
          <>
            <strong>
              {nPlaced} / {nPrevues}
            </strong>{" "}
            séances placées · {formatHeures(heuresDe(allItems))}
          </>,
          manquantes.length > 0 && (
            <span className="fiche-manque">{pluriel(manquantes.length, "non placée", "non placées")}</span>
          ),
        ]}
      />

      <NavSemaine
        weekRows={payload.weekRows}
        selected={c.displayWeek}
        onSelect={c.setDisplayWeek}
        countByWeekIndex={hoursByWeek}
        onAujourdhui={c.narrow ? c.jourAujourdhui : undefined}
      />

      <ProchainCours payload={payload} items={allItems} showPromo onVoir={(it) => c.allerA(it.w, it.d)} />

      <div className="fiche-corps avec-cote">
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
        <aside className="fiche-cote" aria-label="Maquette et intervenants">
          <section className="panel cote-bloc">
            <h3>Maquette</h3>
            <table className="cote-table cote-maquette">
              <thead>
                <tr>
                  <th>Parcours</th>
                  <th className="num">CM</th>
                  <th className="num">TD</th>
                  <th className="num">TP</th>
                  <th className="num">Éval</th>
                  <th className="num">Placées</th>
                </tr>
              </thead>
              <tbody>
                {entrees.map((e) => (
                  <tr key={`${e.code}-${e.parcours}`}>
                    <td>
                      {e.parcours || "—"}
                      <span className="cote-sous">
                        {e.semestre}
                        {e.progressionDefined ? " · progression définie" : ""}
                      </span>
                    </td>
                    <td className="num">{e.nCM}</td>
                    <td className="num">{e.nTD}</td>
                    <td className="num">{e.nTP}</td>
                    <td className="num">{e.nEval}</td>
                    <td className="num">{e.nPlaced}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {entrees.some((e) => e.ordonnancement.length > 0) && (
              <>
                <h4>Ordonnancement</h4>
                <ul className="cote-liste">
                  {entrees.flatMap((e) =>
                    e.ordonnancement.map((o, i) => (
                      <li key={`${e.parcours}-${i}`}>
                        {e.parcours} : {o.position} → {o.target}
                      </li>
                    )),
                  )}
                </ul>
              </>
            )}
            {manquantes.length > 0 && (
              <>
                <h4 className="fiche-manque">Non placées</h4>
                <ul className="cote-liste">
                  {manquantes.map((s) => (
                    <li key={s.id}>
                      {s.type} · {s.groupes.join(", ")} · {s.profs.join(", ")}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
          <section className="panel cote-bloc">
            <h3>Intervenants</h3>
            <dl className="fiche-dl">
              <dt>Enseignants</dt>
              <dd>
                {teachers.length ? (
                  <span className="cote-liens">
                    {teachers.map((t) => (
                      <button key={t} type="button" className="linklike" onClick={() => setRoute({ vue: "prof", prof: t })}>
                        {payload.teacherLabels[t] ?? t}
                      </button>
                    ))}
                  </span>
                ) : (
                  <span className="muted">—</span>
                )}
              </dd>
              <dt>Groupes</dt>
              <dd>
                {groupes.length ? (
                  <span className="cote-liens">
                    {groupes.map((g) => (
                      <button key={g} type="button" className="linklike" onClick={() => setRoute({ vue: "groupe", groupe: g })}>
                        {payload.groupParcours[g] ? `${payload.groupParcours[g]} ` : ""}
                        {payload.groupLabels[g] ?? g}
                      </button>
                    ))}
                  </span>
                ) : (
                  <span className="muted">—</span>
                )}
              </dd>
              <dt>Salles</dt>
              <dd>
                {salles.length ? (
                  <span className="cote-liens">
                    {salles.map((s) =>
                      salleParLabel.has(s) ? (
                        <button key={s} type="button" className="linklike" onClick={() => setRoute({ vue: "salle", salle: salleParLabel.get(s) })}>
                          {s}
                        </button>
                      ) : (
                        <span key={s}>{s}</span>
                      ),
                    )}
                  </span>
                ) : (
                  <span className="muted">—</span>
                )}
              </dd>
            </dl>
          </section>
        </aside>
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
