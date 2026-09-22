/**
 * Fiche salle — catalogue + occupation de la semaine.
 * AppRow.r est le libellé, pas l'id : on filtre la grille sur room.label.
 */

import { useEffect, useMemo, useState } from "react";

import { FicheIntrouvable } from "../components/FicheIntrouvable";
import { DayStrip, todayIndex } from "../components/DayStrip";
import { RoomPlacementAutoField } from "../components/RoomPlacementAutoField";
import { SessionGrid } from "../components/SessionGrid";
import { WeekBar } from "../components/WeekBar";
import { useNarrowScreen } from "../hooks/useNarrowScreen";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { sessionsWithDates } from "../utils/ics";
import { displayIndexForSolverWeek } from "../utils/weekDisplay";

interface SalleViewProps {
  payload: AppPayload;
  route: Route;
  setRoute: (patch: Partial<Route>) => void;
  onOpenSearch?: () => void;
}

export function SalleView({ payload, route, setRoute, onOpenSearch }: SalleViewProps) {
  // Ouverte depuis le menu (« Vue Salle », 22/09/2026), la route ne porte
  // AUCUNE salle : la fiche affichait alors « Salle « ? » introuvable »
  // (signalement du 22/09/2026 en production). Comme la Vue Groupe et la Vue
  // Enseignant, on ouvre donc sur une salle par défaut — la première du
  // catalogue — et on laisse choisir avec le sélecteur ci-dessous.
  // « Introuvable » reste réservé à une salle DEMANDÉE mais inconnue (lien
  // périmé, id mal recopié).
  const sallesTriees = [...payload.rooms].sort((a, b) => a.label.localeCompare(b.label, "fr"));
  const id = route.salle || sallesTriees[0]?.id || "";
  const room = payload.rooms.find((r) => r.id === id) ?? payload.rooms.find((r) => r.label === id);
  const [displayWeek, setDisplayWeek] = useState(() => displayIndexForSolverWeek(payload, route.sem));
  const [mobileDay, setMobileDay] = useState(todayIndex());
  const narrow = useNarrowScreen();
  // Reflète immédiatement une modification de `placementAuto` (`PATCH
  // /rooms/{id}`) sans attendre le prochain rechargement complet du payload
  // — retour utilisateur 22/09/2026. `null` = pas encore modifié depuis
  // l'ouverture de la fiche, on affiche alors la valeur du payload.
  const [placementAutoLocal, setPlacementAutoLocal] = useState<boolean | null>(null);

  useEffect(() => {
    if (route.sem !== null) setDisplayWeek(displayIndexForSolverWeek(payload, route.sem));
  }, [payload, route.sem]);

  useEffect(() => {
    setPlacementAutoLocal(null);
  }, [id]);

  const label = room?.label ?? id;
  const allItems = useMemo(
    () => sessionsWithDates(payload, payload.rows.filter((r) => r.r === label)),
    [payload, label],
  );
  const solverWeek = payload.weekRows[displayWeek]?.weekIndex ?? null;
  const rowsThisWeek = solverWeek === null ? [] : allItems.filter((r) => r.w === solverWeek);

  const hoursByWeek = new Map<number, number>();
  for (const it of allItems) hoursByWeek.set(it.w, (hoursByWeek.get(it.w) ?? 0) + (it.dur || 1) * 1.5);

  if (!id || !room) {
    return <FicheIntrouvable libelle="Salle" id={route.salle || "?"} onOpenSearch={onOpenSearch} />;
  }

  const indispos = payload.exceptions.filter(
    (e) => e.kind === "room_unavailable" && e.active && e.room_id === room.id,
  );

  // Cf. `RoomPlacementAutoField` : reflète une modification tout juste
  // sauvegardée sans attendre le prochain chargement complet du payload.
  const placementAuto = placementAutoLocal ?? room.placementAuto;

  return (
    <section className="view">
      <div className="panel">
        <label className="salle-selecteur">
          Salle
          <select
            value={room.id}
            onChange={(e) => setRoute({ vue: "salle", salle: e.target.value })}
          >
            {sallesTriees.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label} — {r.capacity} places
              </option>
            ))}
          </select>
        </label>
        <h3>{room.label}</h3>
        {room.id !== room.label && <p className="muted mono">{room.id}</p>}
        <p className="muted">
          {room.type} · {room.capacity} places · {room.nSessions} séance(s) placée(s)
          {/* Marqueur TEXTE, pas seulement couleur (retour utilisateur
              22/09/2026) — une salle hors placement automatique reste
              choisissable à la main. */}
          {!placementAuto && <span className="badge">hors auto</span>}
        </p>
        <RoomPlacementAutoField
          roomId={room.id}
          placementAuto={placementAuto}
          onSaved={(v) => setPlacementAutoLocal(v)}
        />
        {room.equipment.length > 0 && (
          <>
            <div className="raw-label">Équipement</div>
            <p>{room.equipment.join(" · ")}</p>
          </>
        )}
        {indispos.length > 0 && (
          <>
            <div className="raw-label">Indisponibilités</div>
            <ul>
              {indispos.map((e) => (
                <li key={e.id}>
                  {e.exception_date}
                  {e.slots ? ` · créneaux ${e.slots.join(", ")}` : ""}
                  {e.reason ? ` — ${e.reason}` : ""}
                </li>
              ))}
            </ul>
          </>
        )}
        {allItems.length > 0 && (
          <>
            <div className="raw-label">Cours qui y passent</div>
            <p>
              {[...new Set(allItems.map((r) => r.c))].map((c, i) => (
                <span key={c}>
                  {i > 0 ? " · " : null}
                  <button type="button" className="linklike" onClick={() => setRoute({ vue: "cours", cours: c })}>
                    {c}
                  </button>
                </span>
              ))}
            </p>
          </>
        )}
      </div>

      <div className="panel controls">
        <div className="field weekfield">
          <WeekBar
            weekRows={payload.weekRows}
            countByWeekIndex={hoursByWeek}
            selected={displayWeek}
            onSelect={setDisplayWeek}
            unit="heures"
          />
        </div>
      </div>

      {narrow && <DayStrip selected={mobileDay} onSelect={setMobileDay} />}

      <div className="panel">
        <h3>Occupation — {payload.weekRows[displayWeek]?.label ?? `Semaine ${displayWeek + 1}`}</h3>
        {solverWeek === null ? (
          <p className="muted">Semaine bloquée (vacances/fermeture).</p>
        ) : (
          <SessionGrid payload={payload} rows={rowsThisWeek} week={solverWeek} onlyDay={narrow ? mobileDay : null} showPromo />
        )}
      </div>
    </section>
  );
}
