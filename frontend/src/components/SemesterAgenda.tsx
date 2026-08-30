import type { AppPayload } from "../types/app";
import type { IcsSession } from "../utils/ics";
import { formatSessionDate } from "../utils/weekDates";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";
import { teinteMatiere, varianteMatiere } from "../utils/couleursMatiere";
import { usePreferences } from "../utils/preferences";
import { groupLabelWithParcours } from "../utils/years";

interface SemesterAgendaProps {
  payload: AppPayload;
  items: IcsSession[];
  /** Préfixe chaque groupe de sa promotion — vrai en Vue Enseignant, où le
   *  même libellé de groupe existe dans plusieurs promotions (cf.
   *  `groupLabelWithParcours`). */
  showPromo?: boolean;
}

/** Liste chronologique de toutes les interventions du semestre, groupées par
 * semaine — portage de `renderTeacherAgenda` depuis la page HTML/JS, réutilisé
 * ici pour les enseignants ET les groupes étudiants. */
export function SemesterAgenda({ payload, items, showPromo = false }: SemesterAgendaProps) {
  if (!items.length) {
    return <p className="muted">Aucune séance placée.</p>;
  }

  const couleursParMatiere = usePreferences().couleursParMatiere;
  const byWeek = new Map<number, IcsSession[]>();
  for (const it of items) {
    if (!byWeek.has(it.w)) byWeek.set(it.w, []);
    byWeek.get(it.w)!.push(it);
  }
  const totalSlots = items.reduce((n, it) => n + (it.dur || 1), 0);
  const hours = (totalSlots * 1.5).toLocaleString("fr-FR");

  return (
    <div className="agenda">
      <p className="agenda-summary">
        <strong>{items.length}</strong> séance(s) · <strong>{hours} h</strong> · sur{" "}
        <strong>{byWeek.size}</strong> semaine(s)
      </p>
      {[...byWeek.entries()]
        .sort((a, b) => a[0] - b[0])
        .map(([w, list]) => (
          <div key={w} className="agenda-week">
            <div className="agenda-week-label">{payload.weekLabels[w] ?? `Semaine ${w + 1}`}</div>
            <div className="agenda-chips">
              {list.map((it) => {
                const end = SLOT_TIMES[Math.min(5, it.s + (it.dur || 1) - 1)].label.split("–")[1];
                const groups = showPromo
                  ? groupLabelWithParcours(it.g, payload.groupLabels, payload.groupParcours)
                  : it.g.map((g) => payload.groupLabels[g] ?? g).join(", ");
                return (
                  <span
                    key={it.id}
                    className={`agenda-chip${couleursParMatiere ? " couleurs-matiere" : ""}`}
                    style={{
                      ["--teinte-matiere" as string]: String(teinteMatiere(it.c)),
                      ["--variante-matiere" as string]: String(varianteMatiere(it.c)),
                    }}
                  >
                    {formatSessionDate(it.date, DAY_LABELS[it.d])} {SLOT_TIMES[it.s].label.split("–")[0]}–{end} ·{" "}
                    {it.c}
                    {groups ? ` · ${groups}` : ""}
                    {it.r ? ` · ${it.r}` : ""}
                  </span>
                );
              })}
            </div>
          </div>
        ))}
    </div>
  );
}
