/**
 * Le planning d'UNE semaine, tel qu'il se lit selon l'écran :
 *
 * - ordinateur : la grille 5 jours × 6 créneaux (`SessionGrid`) ;
 * - téléphone : jour par jour, une liste de cartes lisibles au pouce
 *   (heure, cours, SALLE en gros), avec des onglets de jours qui disent
 *   combien de cours chaque jour contient. La grille réduite à une colonne,
 *   utilisée jusqu'ici, montrait six cases dont la moitié vides pour deux
 *   cours, et obligeait à lire l'heure dans la marge.
 *
 * Une semaine sans cours (vacances) dit pourquoi et propose d'aller à la
 * reprise, au lieu d'un « Semaine bloquée » sec.
 */

import { useRef } from "react";

import type { AppPayload, AppRow } from "../types/app";
import { couleursMatiere } from "../utils/couleursMatiere";
import {
  decouperLibelleSemaine,
  horaireSeance,
  jourAujourdhuiDansSemaine,
  periodeBloquee,
  pluriel,
  semaineDeReprise,
} from "../utils/planning";
import { usePreferences } from "../utils/preferences";
import { DAY_LABELS } from "../utils/slots";
import { dateForWeekDay } from "../utils/weekDates";
import { groupLabelWithParcours } from "../utils/years";
import { SessionGrid } from "./SessionGrid";

import "./Planning.css";

interface PlanningSemaineProps {
  payload: AppPayload;
  /** Séances de la semaine affichée (déjà filtrées). */
  rows: AppRow[];
  /** Index d'AFFICHAGE de la semaine (dans `weekRows`). */
  displayIndex: number;
  onSelectWeek: (displayIndex: number) => void;
  parcours?: string | string[];
  showPac?: boolean;
  split?: [string, string];
  showPromo?: boolean;
  /** Lecture jour par jour (téléphone). */
  narrow: boolean;
  jour: number;
  onJour: (jour: number) => void;
  /** Titre imprimé au-dessus de la grille (nom + semaine). */
  titreImpression: string;
  /** Message quand la semaine n'a aucune séance (ex. « Aucun cours »). */
  videLibelle?: string;
  /** Enseignant à ne pas répéter sur chaque carte (c'est son planning). */
  exclureProf?: string;
}

export function PlanningSemaine({
  payload,
  rows,
  displayIndex,
  onSelectWeek,
  parcours = "",
  showPac = false,
  split,
  showPromo = false,
  narrow,
  jour,
  onJour,
  titreImpression,
  videLibelle = "Aucun cours cette semaine.",
  exclureProf,
}: PlanningSemaineProps) {
  const semaine = payload.weekRows[displayIndex];
  const week = semaine?.weekIndex ?? null;
  const { titre, dates } = decouperLibelleSemaine(semaine?.label ?? "");

  if (week === null) {
    const periode = periodeBloquee(semaine, payload.institutionalCalendar);
    const reprise = semaineDeReprise(payload.weekRows, displayIndex);
    return (
      <div className="planning-bloque" role="status">
        <p className="planning-bloque-titre">Pas de cours cette semaine</p>
        <p className="muted">
          {periode ? periode.label : "Semaine bloquée (vacances ou fermeture)"}
          {reprise !== null && ` — reprise ${decouperLibelleSemaine(payload.weekRows[reprise].label).titre.toLowerCase()}`}
        </p>
        {reprise !== null && (
          <button type="button" className="btn btn--sm" onClick={() => onSelectWeek(reprise)}>
            Aller à la reprise
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="planning-semaine">
      <p className="print-only planning-print-titre">
        {titreImpression} — {titre}
        {dates ? ` (${dates})` : ""}
      </p>
      {rows.length === 0 && !narrow && <p className="planning-vide muted">{videLibelle}</p>}
      {narrow ? (
        <ListeJours
          payload={payload}
          rows={rows}
          week={week}
          parcours={parcours}
          showPac={showPac}
          showPromo={showPromo}
          exclureProf={exclureProf}
          jour={jour}
          onJour={onJour}
        />
      ) : (
        <SessionGrid
          payload={payload}
          rows={rows}
          week={week}
          parcours={parcours}
          showPac={showPac}
          split={split}
          showPromo={showPromo}
        />
      )}
    </div>
  );
}

interface ListeJoursProps {
  payload: AppPayload;
  rows: AppRow[];
  week: number;
  parcours: string | string[];
  showPac: boolean;
  showPromo: boolean;
  exclureProf?: string;
  jour: number;
  onJour: (jour: number) => void;
}

const JOUR_LONG = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long" });

/** Lecture jour par jour, sur téléphone. */
export function ListeJours({ payload, rows, week, parcours, showPac, showPromo, exclureProf, jour, onJour }: ListeJoursProps) {
  const couleursParMatiere = usePreferences().couleursParMatiere;
  const aujourdhui = jourAujourdhuiDansSemaine(payload, week, new Date());
  const toucher = useRef<{ x: number; y: number } | null>(null);
  const parJour = [0, 1, 2, 3, 4].map((d) => rows.filter((r) => r.d === d).sort((a, b) => a.s - b.s));
  const parcoursVus = (Array.isArray(parcours) ? parcours : [parcours]).filter(Boolean);

  const duJour = parJour[jour] ?? [];
  const date = dateForWeekDay(payload, week, jour);
  const ferie = payload.holidayRows.find((h) => h.w === week && h.d === jour);
  const sae = payload.saeRows
    .filter((s) => s.w === week && s.d === jour && (!parcoursVus.length || parcoursVus.includes(s.p)))
    .flatMap((s) => s.codes);
  const evenements = Array.from(
    new Set(
      payload.eventSlotRows
        .filter(
          (e) =>
            e.w === week &&
            e.d === jour &&
            (!e.parcours.length || !parcoursVus.length || e.parcours.some((p) => parcoursVus.includes(p))),
        )
        .map((e) => e.label),
    ),
  );
  const evenementsJour = payload.eventRows.filter((e) => e.w === week && e.d === jour).flatMap((e) => e.labels);
  const matin = duJour.filter((r) => r.s < 3);
  const apresMidi = duJour.filter((r) => r.s >= 3);
  const prochainJourAvecCours = [1, 2, 3, 4].map((k) => jour + k).find((d) => d <= 4 && parJour[d].length > 0);

  const carte = (r: AppRow) => {
    const h = horaireSeance(r);
    const groupes = showPromo
      ? groupLabelWithParcours(r.g, payload.groupLabels, payload.groupParcours)
      : r.g.map((g) => payload.groupLabels[g] ?? g).join(", ");
    const profs = r.te
      .filter((t) => t !== exclureProf)
      .map((t) => payload.teacherLabels[t] ?? t)
      .join(", ");
    return (
      <li
        key={r.id}
        className={`jour-seance type-${r.t.toLowerCase()}${r.ev ? " eval" : ""}`}
        style={couleursMatiere(r.c) as React.CSSProperties}
      >
        <span className="jour-heure">
          <strong>{h.debut}</strong>
          <span>{h.fin}</span>
        </span>
        <span className="jour-corps">
          <span className="jour-nom">{r.n || r.c}</span>
          <span className="jour-meta">
            <span className="mono">{r.c}</span> · {r.t}
            {r.ev ? " · Éval" : ""}
            {groupes ? ` · ${groupes}` : ""}
          </span>
          {profs && <span className="jour-meta">{profs}</span>}
        </span>
        <span className={`jour-salle${r.r ? "" : " jour-salle--absente"}`}>{r.r || "salle à définir"}</span>
      </li>
    );
  };

  return (
    <div
      className={`listejours${couleursParMatiere ? " couleurs-matiere" : ""}`}
      // Glisser horizontalement change de jour — le geste qu'on fait
      // naturellement sur un téléphone. Les onglets restent pour qui ne le
      // connaît pas.
      onTouchStart={(e) => {
        const t = e.touches[0];
        toucher.current = { x: t.clientX, y: t.clientY };
      }}
      onTouchEnd={(e) => {
        const debut = toucher.current;
        toucher.current = null;
        if (!debut) return;
        const t = e.changedTouches[0];
        const dx = t.clientX - debut.x;
        if (Math.abs(dx) < 60 || Math.abs(t.clientY - debut.y) > Math.abs(dx)) return;
        if (dx < 0 && jour < 4) onJour(jour + 1);
        if (dx > 0 && jour > 0) onJour(jour - 1);
      }}
    >
      <div className="jours-onglets" role="tablist" aria-label="Jour">
        {DAY_LABELS.map((label, d) => {
          const dt = dateForWeekDay(payload, week, d);
          const n = parJour[d].length;
          return (
            <button
              key={label}
              type="button"
              role="tab"
              aria-selected={d === jour}
              aria-current={d === aujourdhui ? "date" : undefined}
              className={`jour-onglet${d === jour ? " is-active" : ""}${d === aujourdhui ? " is-today" : ""}`}
              onClick={() => onJour(d)}
            >
              <span className="jour-onglet-nom">{label.slice(0, 3)}</span>
              <span className="jour-onglet-date">{dt ? dt.getDate() : ""}</span>
              <span className="jour-onglet-n" aria-label={pluriel(n, "cours", "cours")}>
                {n > 0 ? "•".repeat(Math.min(n, 4)) : " "}
              </span>
            </button>
          );
        })}
      </div>

      <div className="jour-panneau" role="tabpanel">
        <p className="jour-titre">
          {date ? JOUR_LONG.format(date) : DAY_LABELS[jour]}
          {jour === aujourdhui && <span className="jour-titre-auj">aujourd'hui</span>}
          <span className="jour-titre-n">{duJour.length ? pluriel(duJour.length, "cours", "cours") : ""}</span>
        </p>

        {ferie && (
          <p className="jour-bande">
            <strong>{ferie.kind === "vacances" ? "Vacances" : "Férié"}</strong> — {ferie.label}
          </p>
        )}
        {sae.length > 0 && (
          <p className="jour-bande">
            <strong>Journée SAE</strong> — {sae.join(", ")}
          </p>
        )}
        {[...evenementsJour, ...evenements].map((e) => (
          <p key={e} className="jour-bande">
            {e}
          </p>
        ))}

        {duJour.length === 0 && !ferie ? (
          <div className="jour-vide">
            <p>{rows.length ? "Pas de cours ce jour-là." : "Aucun cours cette semaine."}</p>
            {prochainJourAvecCours !== undefined && (
              <button type="button" className="btn btn--sm" onClick={() => onJour(prochainJourAvecCours)}>
                Voir {DAY_LABELS[prochainJourAvecCours].toLowerCase()}
              </button>
            )}
          </div>
        ) : (
          <>
            {matin.length > 0 && <ul className="jour-liste">{matin.map(carte)}</ul>}
            {matin.length > 0 && apresMidi.length > 0 && <p className="jour-pause">Pause déjeuner</p>}
            {apresMidi.length > 0 && <ul className="jour-liste">{apresMidi.map(carte)}</ul>}
          </>
        )}
        {showPac && jour === 3 && <p className="jour-bande">Jeudi après-midi : PAC</p>}
      </div>
    </div>
  );
}
