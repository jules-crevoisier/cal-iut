/**
 * Vue Salle — l'occupation d'une salle, semaine par semaine, et sa fiche
 * (type, capacité, équipement, indisponibilités, cours qui y passent).
 * `AppRow.r` est le LIBELLÉ de la salle, pas son id : on filtre sur
 * `room.label`.
 *
 * Refonte v2 du 29/09/2026 (cf. docs/DESIGN.md « Gabarit de page ») : sans
 * salle choisie, l'annuaire des salles avec leur taux d'occupation de la
 * semaine partagée (la plus chargée d'abord) — avant, la vue ouvrait la
 * première salle de l'alphabet, ce qui ne répondait à aucune question. La
 * fiche suit le gabarit commun ; son nom n'est plus répété dans la colonne.
 */

import { useEffect, useMemo, useState } from "react";

import { FicheIdentite, FicheOutils } from "../components/FicheEntete";
import { FicheIntrouvable } from "../components/FicheIntrouvable";
import { NavSemaine } from "../components/NavSemaine";
import { PlanningSemaine } from "../components/PlanningSemaine";
import { ProchainCours } from "../components/ProchainCours";
import { RoomPlacementAutoField } from "../components/RoomPlacementAutoField";
import { useConsultation } from "../hooks/useConsultation";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { annuaireSalles, CRENEAUX_SEMAINE, libelleTypeSalle } from "../utils/annuaires";
import { sessionsWithDates } from "../utils/ics";
import { decouperLibelleSemaine, formatHeures, heuresDe, jourCourt, pluriel } from "../utils/planning";
import { SLOT_TIMES } from "../utils/slots";
import { AnnuaireSalles, SEUIL_SATUREE } from "./Annuaires";

import "./fiches.css";

interface SalleViewProps {
  payload: AppPayload;
  route: Route;
  setRoute: (patch: Partial<Route>) => void;
  onOpenSearch?: () => void;
}

/** Au-delà, la liste « Cours qui y passent » se replie. */
const COURS_VISIBLES = 10;

export function SalleView({ payload, route, setRoute, onOpenSearch }: SalleViewProps) {
  const sallesTriees = useMemo(
    () => [...payload.rooms].sort((a, b) => a.label.localeCompare(b.label, "fr")),
    [payload.rooms],
  );
  const id = route.salle;
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
  // Occupation de la semaine : même calcul que l'annuaire et « Salles
  // libres » (fusions et réservations comprises).
  const ligne = useMemo(
    () => (room ? annuaireSalles(payload, c.solverWeek).find((l) => l.id === room.id) : undefined),
    [payload, c.solverWeek, room],
  );

  // Ouverte depuis le menu, la route ne porte AUCUNE salle : l'annuaire.
  // « Introuvable » reste réservé à une salle DEMANDÉE mais inconnue
  // (signalement du 22/09/2026 en production).
  if (!id) {
    return (
      <section className="view fiche fiche--annuaire">
        <AnnuaireSalles
          payload={payload}
          displayWeek={c.displayWeek}
          actions={
            <button type="button" className="btn" onClick={() => setRoute({ vue: "salles-libres" })}>
              Salles libres par créneau
            </button>
          }
          onOuvrir={(sid) => setRoute({ vue: "salle", salle: sid })}
        />
      </section>
    );
  }
  if (!room) {
    return <FicheIntrouvable libelle="Salle" id={id} onOpenSearch={onOpenSearch} />;
  }

  const rowsThisWeek = c.solverWeek === null ? [] : allItems.filter((r) => r.w === c.solverWeek);
  const creneauxParSemaine = new Map<number, number>();
  for (const it of allItems) creneauxParSemaine.set(it.w, (creneauxParSemaine.get(it.w) ?? 0) + Math.max(1, it.dur || 1));
  const occupes = ligne?.creneauxOccupes ?? 0;
  const saturee = (ligne?.taux ?? 0) >= SEUIL_SATUREE;
  const titreSemaine = decouperLibelleSemaine(payload.weekRows[c.displayWeek]?.label ?? "").titre;

  const indispos = payload.exceptions.filter(
    (e) => e.kind === "room_unavailable" && e.active && e.room_id === room.id,
  );
  const placementAuto = placementAutoLocal ?? room.placementAuto;
  // Les cours qui l'occupent le plus d'abord, avec leurs heures.
  const parCours = new Map<string, { nom: string; h: number }>();
  for (const it of allItems) {
    const cur = parCours.get(it.c) ?? { nom: it.n || it.c, h: 0 };
    cur.h += heuresDe([it]);
    parCours.set(it.c, cur);
  }
  const cours = [...parCours.entries()].sort((a, b) => b[1].h - a[1].h || a[0].localeCompare(b[0], "fr"));
  const ligneCours = ([cc, v]: [string, { nom: string; h: number }]) => (
    <tr key={cc}>
      <td>
        <button type="button" className="linklike mono" onClick={() => setRoute({ vue: "cours", cours: cc })}>
          {cc}
        </button>
        <span className="cote-sous">{v.nom}</span>
      </td>
      <td className="num">{formatHeures(v.h)}</td>
    </tr>
  );

  return (
    <section className="view fiche">
      <FicheOutils
        libelle="Salle"
        valeur={room.id}
        options={sallesTriees.map((r) => ({ value: r.id, label: `${r.label} — ${r.capacity} places` }))}
        onChoisir={(sid) => setRoute({ vue: "salle", salle: sid })}
        onAnnuaire={() => setRoute({ vue: "salle", salle: "" })}
        actions={
          <button type="button" className="btn" onClick={() => setRoute({ vue: "salles-libres" })}>
            Salles libres par créneau
          </button>
        }
      />

      <FicheIdentite
        titre={room.label}
        faits={[
          room.id !== room.label && <span className="mono">{room.id}</span>,
          `${libelleTypeSalle(room.type)} · ${room.capacity} places`,
          // Marqueur TEXTE, pas seulement couleur (retour utilisateur
          // 22/09/2026) : une salle hors placement automatique reste
          // choisissable à la main.
          !placementAuto && <span className="pill">hors auto</span>,
          c.solverWeek !== null && (
            <>
              <strong className={saturee ? "fiche-manque" : undefined}>
                {occupes} / {CRENEAUX_SEMAINE} créneaux
              </strong>{" "}
              occupés en {titreSemaine.toLowerCase()}
              {saturee && <span className="fiche-manque"> · saturée</span>}
            </>
          ),
          pluriel(room.nSessions, "séance placée", "séances placées") + " au semestre",
        ]}
      />

      <NavSemaine
        weekRows={payload.weekRows}
        selected={c.displayWeek}
        onSelect={c.setDisplayWeek}
        countByWeekIndex={creneauxParSemaine}
        unit="creneaux"
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
            titreImpression={`Salle ${room.label}`}
            videLibelle="Salle libre toute la semaine."
          />
        </div>
        <aside className="fiche-cote" aria-label="Fiche de la salle">
          <section className="panel cote-bloc">
            <h3>Réglages et équipement</h3>
            <RoomPlacementAutoField
              roomId={room.id}
              placementAuto={placementAuto}
              onSaved={(v) => setPlacementAutoLocal(v)}
            />
            <h4>Équipement</h4>
            <p>{room.equipment.length ? room.equipment.join(" · ") : <span className="muted">Aucun équipement déclaré.</span>}</p>
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
          </section>
          {cours.length > 0 && (
            <section className="panel cote-bloc">
              <h3>Cours qui y passent</h3>
              <table className="cote-table">
                <tbody>{cours.slice(0, COURS_VISIBLES).map(ligneCours)}</tbody>
              </table>
              {cours.length > COURS_VISIBLES && (
                <details className="cote-details">
                  <summary>{pluriel(cours.length - COURS_VISIBLES, "autre cours", "autres cours")}</summary>
                  <table className="cote-table">
                    <tbody>{cours.slice(COURS_VISIBLES).map(ligneCours)}</tbody>
                  </table>
                </details>
              )}
            </section>
          )}
        </aside>
      </div>
    </section>
  );
}
