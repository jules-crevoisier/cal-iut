/**
 * Vue Salle — l'occupation d'une salle, semaine par semaine, et sa fiche
 * (type, capacité, équipement, indisponibilités, cours qui y passent).
 * `AppRow.r` est le LIBELLÉ de la salle, pas son id : on filtre sur
 * `room.label`.
 *
 * Refonte du 29/09/2026 : sélecteur et navigation de semaine en tête, la
 * grille d'abord, la fiche dans une colonne à droite — on vient ici pour
 * savoir quand la salle est prise, pas pour relire sa capacité.
 */

import { useEffect, useMemo, useState } from "react";

import { FicheIntrouvable } from "../components/FicheIntrouvable";
import { NavSemaine } from "../components/NavSemaine";
import { PlanningSemaine } from "../components/PlanningSemaine";
import { RoomPlacementAutoField } from "../components/RoomPlacementAutoField";
import { useConsultation } from "../hooks/useConsultation";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { sessionsWithDates } from "../utils/ics";
import { jourCourt, pluriel } from "../utils/planning";
import { SLOT_TIMES } from "../utils/slots";

import "./fiches.css";

interface SalleViewProps {
  payload: AppPayload;
  route: Route;
  setRoute: (patch: Partial<Route>) => void;
  onOpenSearch?: () => void;
}

const CRENEAUX_SEMAINE = 30;

export function SalleView({ payload, route, setRoute, onOpenSearch }: SalleViewProps) {
  // Ouverte depuis le menu, la route ne porte AUCUNE salle : on ouvre sur la
  // première du catalogue (signalement du 22/09/2026 en production, la fiche
  // affichait « Salle « ? » introuvable »). « Introuvable » reste réservé à
  // une salle DEMANDÉE mais inconnue.
  const sallesTriees = useMemo(
    () => [...payload.rooms].sort((a, b) => a.label.localeCompare(b.label, "fr")),
    [payload.rooms],
  );
  const id = route.salle || sallesTriees[0]?.id || "";
  const room = payload.rooms.find((r) => r.id === id) ?? payload.rooms.find((r) => r.label === id);
  const c = useConsultation(payload, route.sem);
  // Reflète tout de suite une modification de `placementAuto` (PATCH
  // /rooms/{id}) sans attendre le rechargement complet du payload.
  const [placementAutoLocal, setPlacementAutoLocal] = useState<boolean | null>(null);

  useEffect(() => {
    setPlacementAutoLocal(null);
  }, [id]);

  const label = room?.label ?? id;
  const allItems = useMemo(
    () => sessionsWithDates(payload, payload.rows.filter((r) => r.r === label)),
    [payload, label],
  );

  if (!id || !room) {
    return <FicheIntrouvable libelle="Salle" id={route.salle || "?"} onOpenSearch={onOpenSearch} />;
  }

  const rowsThisWeek = c.solverWeek === null ? [] : allItems.filter((r) => r.w === c.solverWeek);
  const creneauxParSemaine = new Map<number, number>();
  for (const it of allItems) creneauxParSemaine.set(it.w, (creneauxParSemaine.get(it.w) ?? 0) + Math.max(1, it.dur || 1));
  const occupes = c.solverWeek === null ? 0 : (creneauxParSemaine.get(c.solverWeek) ?? 0);

  const indispos = payload.exceptions.filter(
    (e) => e.kind === "room_unavailable" && e.active && e.room_id === room.id,
  );
  const placementAuto = placementAutoLocal ?? room.placementAuto;
  const cours = [...new Set(allItems.map((r) => r.c))].sort((a, b) => a.localeCompare(b, "fr"));

  return (
    <section className="view fiche">
      <div className="fiche-entete">
        <label className="fiche-choix">
          <span>Salle</span>
          <select value={room.id} onChange={(e) => setRoute({ vue: "salle", salle: e.target.value })}>
            {sallesTriees.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label} — {r.capacity} places
              </option>
            ))}
          </select>
        </label>
        <p className="fiche-identite">
          <span>
            {room.type} · {room.capacity} places
          </span>
          {/* Marqueur TEXTE, pas seulement couleur (retour utilisateur
              22/09/2026) : une salle hors placement automatique reste
              choisissable à la main. */}
          {!placementAuto && <span className="badge">hors auto</span>}
          <span>{pluriel(room.nSessions, "séance placée", "séances placées")} au semestre</span>
        </p>
      </div>

      <NavSemaine
        weekRows={payload.weekRows}
        selected={c.displayWeek}
        onSelect={c.setDisplayWeek}
        countByWeekIndex={creneauxParSemaine}
        unit="creneaux"
        onAujourdhui={c.narrow ? c.jourAujourdhui : undefined}
        resume={
          c.solverWeek !== null && (
            <strong>
              {occupes} / {CRENEAUX_SEMAINE} créneaux occupés
            </strong>
          )
        }
      />

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
            titreImpression={`Salle ${room.label}`}
            videLibelle="Salle libre toute la semaine."
          />
        </div>
        <aside className="fiche-cote" aria-label="Fiche de la salle">
          <section className="panel cote-bloc">
            <h3>{room.label}</h3>
            {room.id !== room.label && <p className="muted mono">{room.id}</p>}
            <RoomPlacementAutoField
              roomId={room.id}
              placementAuto={placementAuto}
              onSaved={(v) => setPlacementAutoLocal(v)}
            />
            {room.equipment.length > 0 && (
              <>
                <h4>Équipement</h4>
                <p>{room.equipment.join(" · ")}</p>
              </>
            )}
            {indispos.length > 0 && (
              <>
                <h4>Indisponibilités</h4>
                <ul className="cote-liste">
                  {indispos.map((e) => (
                    <li key={e.id}>
                      {jourCourt(new Date(`${e.exception_date}T00:00:00`))}
                      {e.slots ? ` · ${e.slots.map((s) => SLOT_TIMES[s]?.label ?? s).join(", ")}` : " · journée"}
                      {e.reason ? ` — ${e.reason}` : ""}
                    </li>
                  ))}
                </ul>
              </>
            )}
            {cours.length > 0 && (
              <>
                <h4>Cours qui y passent</h4>
                <p className="cote-liens">
                  {cours.map((cc) => (
                    <button key={cc} type="button" className="linklike mono" onClick={() => setRoute({ vue: "cours", cours: cc })}>
                      {cc}
                    </button>
                  ))}
                </p>
              </>
            )}
          </section>
        </aside>
      </div>
    </section>
  );
}
