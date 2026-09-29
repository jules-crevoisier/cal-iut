/**
 * Vue « Salles libres » (todo département 22/09/2026, Kyllian Bresson :
 * « quelles salles sont libres sur ce créneau ? ») — et son lien public
 * `#mode=salles`.
 *
 * Recentrée sur le seul tableau d'occupation salles × créneaux (retour
 * utilisateur 25/09/2026, Jules, dicté : « on peut garder uniquement dans
 * "Salles libres" le tableau occupation qui est très bien [...] et on met ça
 * en lien public »). `readOnly` coupe le seul lien de navigation (fiche
 * salle), qui sortirait sinon du lien public vers le reste de l'appli.
 *
 * Refonte du 29/09/2026 : navigation de semaine commune aux autres vues
 * (flèches, « Aujourd'hui », ← → T au clavier), jours en une rangée datée
 * avec aujourd'hui repéré, filtres sur une ligne, nombre de salles libres
 * par créneau dans l'en-tête, créneau en cours surligné et « libres
 * maintenant » en tête quand on regarde aujourd'hui. Sur téléphone, le
 * tableau défile dans son conteneur, colonne « Salle » fixée.
 */

import { useEffect, useMemo, useState } from "react";

import "./SallesLibresView.css";

import { NavSemaine } from "../components/NavSemaine";
import { useSemaineGlobale } from "../contexts/SemaineGlobale";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { jourAujourdhuiDansSemaine, pluriel } from "../utils/planning";
import { indexSemaineCourante, jourOuvreAujourdhui } from "../utils/semaineCourante";
import { occupationSalles } from "../utils/sallesLibres";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";
import { dateForWeekDay } from "../utils/weekDates";
import { displayIndexForSolverWeek } from "../utils/weekDisplay";

interface SallesLibresViewProps {
  payload: AppPayload;
  route: Route;
  setRoute: (patch: Partial<Route>) => void;
  readOnly?: boolean;
}

/** Créneau (0-5) contenant l'heure `now`, ou null (pause, soir, nuit). */
function creneauEnCours(now: Date): number | null {
  const minutes = now.getHours() * 60 + now.getMinutes();
  const idx = SLOT_TIMES.findIndex((s) => {
    const [sh, sm] = s.start.split(":").map(Number);
    const [eh, em] = s.end.split(":").map(Number);
    return minutes >= sh * 60 + sm && minutes < eh * 60 + em;
  });
  return idx >= 0 ? idx : null;
}

export function SallesLibresView({ payload, route, setRoute, readOnly }: SallesLibresViewProps) {
  // Application connectée : la semaine de la barre supérieure, partagée par
  // toutes les vues (refonte v2 du 29/09/2026 — avant, cette vue gardait la
  // sienne et ne suivait pas). Lien public : sa propre semaine.
  const globale = useSemaineGlobale();
  const [locale, setLocale] = useState(() =>
    route.sem !== null && route.sem !== undefined
      ? displayIndexForSolverWeek(payload, route.sem)
      : indexSemaineCourante(payload.weekRows),
  );
  const displayWeek = globale ? globale.index : locale;
  const setDisplayWeek = globale ? globale.setIndex : setLocale;
  useEffect(() => {
    if (globale && route.sem !== null && route.sem !== undefined) {
      globale.setIndex(displayIndexForSolverWeek(payload, route.sem));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.sem]);
  const [day, setDay] = useState(() => (route.jour !== null && route.jour !== undefined ? route.jour : jourOuvreAujourdhui()));
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  const [capaciteMinSaisie, setCapaciteMinSaisie] = useState("");
  const [typeSalle, setTypeSalle] = useState("");
  // Décoché par défaut (retour utilisateur 22/09/2026) : une salle hors
  // placement automatique reste choisissable à la main, mais ne doit pas
  // encombrer la liste par défaut.
  const [inclureHorsAuto, setInclureHorsAuto] = useState(false);

  const capaciteMin = capaciteMinSaisie === "" ? 0 : Math.max(0, Number(capaciteMinSaisie) || 0);

  const typesDisponibles = useMemo(
    () => Array.from(new Set(payload.rooms.map((r) => r.type))).sort((a, b) => a.localeCompare(b, "fr")),
    [payload.rooms],
  );

  // Histogramme : occupation TOTALE du parc (créneaux, durée comprise).
  const countByWeekIndex = useMemo(() => {
    const m = new Map<number, number>();
    for (const row of payload.rows) {
      if (!row.r) continue;
      m.set(row.w, (m.get(row.w) ?? 0) + Math.max(1, row.dur || 1));
    }
    return m;
  }, [payload.rows]);

  const weekRow = payload.weekRows[displayWeek];
  const solverWeek = weekRow?.weekIndex ?? null;
  const holiday = solverWeek === null ? undefined : payload.holidayRows.find((h) => h.w === solverWeek && h.d === day);
  const jourAuj = jourAujourdhuiDansSemaine(payload, solverWeek, now);
  const slotMaintenant = jourAuj !== null && jourAuj === day ? creneauEnCours(now) : null;

  const sallesFiltrees = useMemo(
    () =>
      payload.rooms
        .filter((r) => r.capacity >= capaciteMin)
        .filter((r) => !typeSalle || r.type === typeSalle)
        .filter((r) => inclureHorsAuto || r.placementAuto)
        .sort((a, b) => a.capacity - b.capacity || a.label.localeCompare(b.label, "fr")),
    [payload.rooms, capaciteMin, typeSalle, inclureHorsAuto],
  );

  const occupation = useMemo(
    () => (solverWeek === null ? null : occupationSalles(payload, solverWeek, day)),
    [payload, solverWeek, day],
  );
  const libresParCreneau = SLOT_TIMES.map(
    (_, s) => sallesFiltrees.filter((room) => !occupation?.get(room.id)?.[s]).length,
  );
  const libresMaintenant =
    slotMaintenant === null ? [] : sallesFiltrees.filter((room) => !occupation?.get(room.id)?.[slotMaintenant]);

  const navSemaine = (
    <NavSemaine
      weekRows={payload.weekRows}
      selected={displayWeek}
      onSelect={setDisplayWeek}
      countByWeekIndex={countByWeekIndex}
      unit="creneaux"
      legende="Occupation du parc"
      onAujourdhui={() => setDay(jourOuvreAujourdhui())}
    />
  );

  return (
    <section className="view salleslibres-view">
      {/* Lien public : navigation de semaine en tête. Application : la
          semaine est dans la barre supérieure, l'histogramme vient sous la
          barre d'outils. */}
      {!globale && navSemaine}

      <div className="page-outils salleslibres-barre">
        <div className="salleslibres-jours" role="group" aria-label="Jour">
          {DAY_LABELS.map((label, d) => {
            const date = solverWeek === null ? null : dateForWeekDay(payload, solverWeek, d);
            return (
              <button
                key={label}
                type="button"
                className={`salleslibres-jour${d === day ? " is-active" : ""}${d === jourAuj ? " is-today" : ""}`}
                aria-pressed={d === day}
                aria-current={d === jourAuj ? "date" : undefined}
                onClick={() => setDay(d)}
              >
                <span className="jl">{label}</span>
                <span className="jc">{label.slice(0, 3)}</span>
                {date && <span className="jd">{date.getDate()}</span>}
              </button>
            );
          })}
        </div>

        <div className="salleslibres-filtres">
          <label>
            <span>Capacité minimum</span>
            <input
              type="number"
              min={0}
              inputMode="numeric"
              value={capaciteMinSaisie}
              onChange={(e) => setCapaciteMinSaisie(e.target.value)}
              placeholder="0"
            />
          </label>
          <label>
            <span>Type de salle</span>
            <select value={typeSalle} onChange={(e) => setTypeSalle(e.target.value)}>
              <option value="">Tous types</option>
              {typesDisponibles.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label className="salleslibres-checkbox">
            <input type="checkbox" checked={inclureHorsAuto} onChange={(e) => setInclureHorsAuto(e.target.checked)} />
            Inclure les salles hors placement automatique
          </label>
        </div>
      </div>

      {globale && navSemaine}

      {solverWeek === null ? (
        <div className="panel">
          <p className="muted" role="status">
            Semaine bloquée (vacances ou fermeture) : aucune salle n'est réservée.
          </p>
        </div>
      ) : holiday ? (
        <div className="panel">
          <p className="muted" role="status">
            {holiday.kind === "vacances" ? "Vacances" : "Férié"} — {holiday.label}.
          </p>
        </div>
      ) : (
        <div className="panel salleslibres-grille-wrap">
          <div className="salleslibres-grille-header">
            <h3>
              {DAY_LABELS[day]}
              {jourAuj === day && <span className="salleslibres-auj"> · aujourd'hui</span>}
            </h3>
            <p className="muted" role="status">
              {sallesFiltrees.length === 0
                ? "Aucune salle ne correspond aux filtres."
                : pluriel(sallesFiltrees.length, "salle")}
            </p>
          </div>
          {slotMaintenant !== null && sallesFiltrees.length > 0 && (
            <p className="salleslibres-maintenant">
              <strong>Libres maintenant ({SLOT_TIMES[slotMaintenant].label}) :</strong>{" "}
              {libresMaintenant.length ? libresMaintenant.map((r) => r.label).join(", ") : "aucune"}
            </p>
          )}
          {sallesFiltrees.length > 0 && (
            <div className="salleslibres-defile">
              <table className="salleslibres-grille">
                <thead>
                  <tr>
                    <th scope="col">Salle</th>
                    {SLOT_TIMES.map((s, i) => (
                      <th key={s.label} scope="col" className={i === slotMaintenant ? "is-now" : undefined}>
                        {s.label}
                        <span className="salleslibres-nlibres">{pluriel(libresParCreneau[i], "libre")}</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sallesFiltrees.map((room) => (
                    <tr key={room.id}>
                      <th scope="row">
                        {readOnly ? (
                          <span className="salleslibres-nom">{room.label}</span>
                        ) : (
                          <button
                            type="button"
                            className="linklike salleslibres-nom"
                            onClick={() => setRoute({ vue: "salle", salle: room.id, sem: solverWeek })}
                          >
                            {room.label}
                          </button>
                        )}
                        <span className="salleslibres-cap">{room.capacity} pl.</span>
                      </th>
                      {SLOT_TIMES.map((_, slotIdx) => {
                        const occ = occupation?.get(room.id)?.[slotIdx];
                        return (
                          <td
                            key={slotIdx}
                            className={`salleslibres-cell${occ ? " occupee" : " libre"}${slotIdx === slotMaintenant ? " is-now" : ""}`}
                          >
                            {occ ? (
                              occ.map((e, i) => (
                                <span key={i} className="salleslibres-occ">
                                  <span className="salleslibres-code">{e.code}</span>
                                  {e.groupes.length > 0 && <span className="salleslibres-grp">{e.groupes.join(", ")}</span>}
                                </span>
                              ))
                            ) : (
                              <span className="salleslibres-libre">libre</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
