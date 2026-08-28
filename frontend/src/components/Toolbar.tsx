import type { ViewMode, YearMeta } from "../types";
import type { GroupMeta, RoomMeta } from "../types";
import type { WeekRow } from "../types/app";
import { WeekBar } from "./WeekBar";
import { DEFAULT_YEARS, yearFromSemestre } from "../utils/years";

interface ToolbarProps {
  year: number;
  parcours: string;
  semestre: string;
  years: YearMeta[];
  parcoursList: string[];
  displayWeek: number;
  maxWeeks: number;
  weekRows: WeekRow[];
  weekCounts: Map<number, number>;
  viewMode: ViewMode;
  groupId: string;
  teacherCode: string;
  roomId: string;
  groups: GroupMeta[];
  teachers: string[];
  rooms: RoomMeta[];
  loading: boolean;
  onYearChange: (v: number) => void;
  onParcoursChange: (v: string) => void;
  onSemestreChange: (v: string) => void;
  onWeekChange: (v: number) => void;
  onViewModeChange: (v: ViewMode) => void;
  onGroupChange: (v: string) => void;
  onTeacherChange: (v: string) => void;
  onRoomChange: (v: string) => void;
}

function groupOptionLabel(g: GroupMeta, all: GroupMeta[]): string {
  if (g.kind === "td" && g.related_ids.length) {
    const tpLabels = g.related_ids
      .map((id) => all.find((x) => x.id === id)?.label ?? id)
      .join(", ");
    return `${g.label} — inclut ${tpLabels} + CM`;
  }
  if (g.kind === "promo") {
    return `${g.label} (CM uniquement)`;
  }
  return `${g.label} (${g.kind.toUpperCase()})`;
}

export function Toolbar(props: ToolbarProps) {
  const years = props.years.length ? props.years : DEFAULT_YEARS;
  const yearMeta = years.find((y) => y.id === props.year) ?? years[0];
  const semestres = yearMeta?.semestres ?? ["S1", "S2"];
  const parcoursForYear = yearMeta?.parcours?.length
    ? yearMeta.parcours
    : props.parcoursList.filter(
        (p) => p === `BUT${props.year}` || p.startsWith(`BUT${props.year}-`),
      );

  const filteredGroups = props.groups
    .filter((g) => g.parcours === props.parcours)
    .filter((g) => g.kind === "td" || g.kind === "promo")
    .sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === "td" ? -1 : 1;
      return a.label.localeCompare(b.label, "fr");
    });

  return (
    // Pas de marque "cal-iut" ici : le titre vit désormais dans `PageHeader`
    // (§54), au même endroit que le HTML — la répéter ici aurait été le
    // "superflu" exactement pointé par le retour utilisateur du 11/08/2026
    // (cf. docs/DATA.md §55).
    <header className="toolbar">
      <div className="toolbar-controls">
        <label>
          Année
          <select
            value={props.year}
            onChange={(e) => props.onYearChange(Number(e.target.value))}
            disabled={props.loading}
          >
            {years.map((y) => (
              <option key={y.id} value={y.id}>
                {y.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          Parcours
          <select
            value={props.parcours}
            onChange={(e) => props.onParcoursChange(e.target.value)}
            disabled={props.loading}
          >
            {parcoursForYear.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>

        <label>
          Semestre
          <select
            value={props.semestre}
            onChange={(e) => props.onSemestreChange(e.target.value)}
            disabled={props.loading}
          >
            {semestres.map((s) => (
              <option key={s} value={s}>
                {s} (année {yearFromSemestre(s)})
              </option>
            ))}
          </select>
        </label>

        {props.weekRows.length > 0 ? (
          <label className="weekfield">
            Semaine
            <WeekBar
              weekRows={props.weekRows}
              countByWeekIndex={props.weekCounts}
              selected={props.displayWeek}
              onSelect={props.onWeekChange}
            />
          </label>
        ) : (
          // Repli avant le premier chargement de `/app-state` (pas encore de
          // `weekRows` — la `WeekBar` n'aurait rien à afficher).
          <label>
            Semaine
            <select
              value={props.displayWeek}
              onChange={(e) => props.onWeekChange(Number(e.target.value))}
            >
              {Array.from({ length: props.maxWeeks }, (_, i) => (
                <option key={i} value={i}>
                  Semaine {i + 1}
                </option>
              ))}
            </select>
          </label>
        )}

        <label>
          Vue
          <select
            value={props.viewMode}
            onChange={(e) => props.onViewModeChange(e.target.value as ViewMode)}
          >
            <option value="group">Par groupe TD</option>
            <option value="teacher">Par enseignant</option>
            <option value="room">Par salle</option>
          </select>
        </label>

        {props.viewMode === "group" && (
          <label>
            Groupe étudiant
            <select value={props.groupId} onChange={(e) => props.onGroupChange(e.target.value)}>
              <option value="">Tous</option>
              {filteredGroups.map((g) => (
                <option key={g.id} value={g.id}>
                  {groupOptionLabel(g, props.groups)}
                </option>
              ))}
            </select>
          </label>
        )}

        {props.viewMode === "teacher" && (
          <label>
            Enseignant
            <select value={props.teacherCode} onChange={(e) => props.onTeacherChange(e.target.value)}>
              <option value="">Tous</option>
              {props.teachers.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
        )}

        {props.viewMode === "room" && (
          <label>
            Salle
            <select value={props.roomId} onChange={(e) => props.onRoomChange(e.target.value)}>
              <option value="">Toutes</option>
              {props.rooms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {/* "Charger données" / "Générer" / "Recalculer tout" retirés (retour
          utilisateur 27/08/2026 : génération toujours faite en CLI —
          `cal-iut solve` / `cal-iut load-run` — ces boutons ne servaient
          plus depuis le navigateur). La régénération CIBLÉE d'une semaine
          (`RegenPanel`, panneau latéral) reste : elle fait autre chose
          (re-solve d'UNE semaine, pas tout le semestre) et n'a pas été
          demandée à la suppression. */}
    </header>
  );
}
