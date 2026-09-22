/**
 * Vue « Salles libres » (todo département 22/09/2026, Kyllian Bresson :
 * « donner accès aux enseignants de consulter le planning d'une ressource en
 * particulier [...] » — ici sa question inverse : « quelles salles sont
 * libres sur ce créneau ? »). Lecture seule, ouverte à tous les rôles
 * connectés (y compris `read_only`) — même garde que `SalleView`
 * (`!readOnlyTarget`, cf. `App.tsx`), qui ne concerne que les LIENS publics
 * personnels, jamais le rôle de compte.
 *
 * Mobile d'abord (320px) : sélecteur de créneau + liste des salles libres à
 * ce créneau. À partir de 768px (`useNarrowScreen`, cf. `SalleView`) : en
 * plus, une grille salles × 6 créneaux pour tout voir d'un coup.
 */

import { useMemo, useState } from "react";

import "./SallesLibresView.css";

import type { Route } from "../hooks/useHashRoute";
import { useNarrowScreen } from "../hooks/useNarrowScreen";
import type { AppPayload } from "../types/app";
import { indexSemaineCourante, jourOuvreAujourdhui } from "../utils/semaineCourante";
import { occupationSalles, sallesLibresAuCreneau } from "../utils/sallesLibres";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";
import { displayIndexForSolverWeek } from "../utils/weekDisplay";
import { WeekBar } from "../components/WeekBar";

interface SallesLibresViewProps {
  payload: AppPayload;
  route: Route;
  setRoute: (patch: Partial<Route>) => void;
}

export function SallesLibresView({ payload, route, setRoute }: SallesLibresViewProps) {
  const narrow = useNarrowScreen();

  const [displayWeek, setDisplayWeek] = useState(() =>
    route.sem !== null && route.sem !== undefined
      ? displayIndexForSolverWeek(payload, route.sem)
      : indexSemaineCourante(payload.weekRows),
  );
  const [day, setDay] = useState(() => (route.jour !== null && route.jour !== undefined ? route.jour : jourOuvreAujourdhui()));
  const [slot, setSlot] = useState(0);

  const [capaciteMinSaisie, setCapaciteMinSaisie] = useState("");
  const [typeSalle, setTypeSalle] = useState("");
  // Décoché par défaut (retour utilisateur 22/09/2026) : une salle hors
  // placement automatique reste choisissable à la main, mais ne doit pas
  // polluer la liste par défaut — cf. `RoomCatalogEntry.placementAuto`.
  const [inclureHorsAuto, setInclureHorsAuto] = useState(false);

  const capaciteMin = capaciteMinSaisie === "" ? 0 : Math.max(0, Number(capaciteMinSaisie) || 0);

  const typesDisponibles = useMemo(
    () => Array.from(new Set(payload.rooms.map((r) => r.type))).sort((a, b) => a.localeCompare(b, "fr")),
    [payload.rooms],
  );

  // Histogramme de la WeekBar : occupation TOTALE (toutes salles confondues,
  // pondérée par la durée) — même principe que `SalleView` (`hoursByWeek`),
  // élargi à l'ensemble du parc plutôt qu'à une seule salle.
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

  const filtres = { capaciteMin, type: typeSalle || undefined, inclureHorsAuto };

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

  const librestAuCreneau = useMemo(
    () => (solverWeek === null ? [] : sallesLibresAuCreneau(payload, solverWeek, day, slot, filtres)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [payload, solverWeek, day, slot, capaciteMin, typeSalle, inclureHorsAuto],
  );

  return (
    <section className="view salleslibres-view">
      <div className="panel controls">
        <div className="field weekfield">
          <WeekBar weekRows={payload.weekRows} countByWeekIndex={countByWeekIndex} selected={displayWeek} onSelect={setDisplayWeek} />
        </div>
      </div>

      <div className="panel">
        <div className="salleslibres-jours" role="group" aria-label="Jour">
          {DAY_LABELS.map((label, d) => (
            <button
              key={label}
              type="button"
              className={`btn btn--ghost${d === day ? " active" : ""}`}
              aria-pressed={d === day}
              onClick={() => setDay(d)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="panel controls salleslibres-filtres">
        <label>
          Capacité minimum
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
          Type de salle
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

      {solverWeek === null ? (
        <div className="panel">
          <p className="muted" role="status">
            Semaine bloquée (vacances/fermeture).
          </p>
        </div>
      ) : holiday ? (
        <div className="panel">
          <p className="muted" role="status">
            {holiday.kind === "vacances" ? "Vacances" : "Férié"} — {holiday.label}.
          </p>
        </div>
      ) : (
        <>
          <div className="panel">
            <div className="salleslibres-slots" role="group" aria-label="Créneau">
              {SLOT_TIMES.map((s, i) => (
                <button
                  key={s.label}
                  type="button"
                  className={`btn btn--ghost${i === slot ? " active" : ""}`}
                  aria-pressed={i === slot}
                  onClick={() => setSlot(i)}
                >
                  {s.label}
                </button>
              ))}
            </div>

            <p className="muted" role="status">
              {sallesFiltrees.length === 0
                ? "Aucune salle ne correspond aux filtres."
                : librestAuCreneau.length === 0
                  ? "Toutes les salles correspondant aux filtres sont occupées à ce créneau."
                  : `${librestAuCreneau.length} salle(s) libre(s)`}
            </p>

            {librestAuCreneau.length > 0 && (
              <ul className="salleslibres-liste">
                {librestAuCreneau.map((r) => (
                  <li key={r.id} className="salleslibres-item">
                    <span className="salleslibres-item-label">{r.label}</span>
                    <span className="muted">
                      {r.type} · {r.capacity} places
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {!narrow && (
            <div className="panel salleslibres-grille-wrap">
              <h3>Occupation — {DAY_LABELS[day]}</h3>
              {sallesFiltrees.length === 0 ? (
                <p className="muted">Aucune salle ne correspond aux filtres.</p>
              ) : (
                <table className="salleslibres-grille">
                  <thead>
                    <tr>
                      <th>Salle</th>
                      {SLOT_TIMES.map((s) => (
                        <th key={s.label}>{s.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sallesFiltrees.map((room) => (
                      <tr key={room.id}>
                        <td>
                          <button
                            type="button"
                            className="linklike"
                            onClick={() => setRoute({ vue: "salle", salle: room.id, sem: solverWeek })}
                          >
                            {room.label}
                          </button>
                        </td>
                        {SLOT_TIMES.map((_, slotIdx) => {
                          const occ = occupation?.get(room.id)?.[slotIdx];
                          return (
                            <td key={slotIdx} className={`salleslibres-cell${occ ? " occupee" : " libre"}`}>
                              {occ
                                ? occ
                                    .map((e) => (e.groupes.length ? `${e.code} · ${e.groupes.join(", ")}` : e.code))
                                    .join(" ; ")
                                : "Libre"}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
