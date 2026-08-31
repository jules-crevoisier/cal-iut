import { useMemo } from "react";

import { CopyButton } from "./CopyButton";
import { buildLink } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";

interface TeacherLinksListProps {
  payload: AppPayload;
}

/** Vue simple : un enseignant, une ligne, son lien perso — rien d'autre
 * (retour utilisateur 27/08/2026 : « ajoute moi une vue simple avec tous
 * les lien de tous les prof »). L'annuaire complet (séances, heures, mail,
 * export CSV, + les groupes) reste dans Référentiel → Référence → Liens &
 * partage, pour qui a besoin de plus ; ici, juste la liste à copier vite. */
export function TeacherLinksList({ payload }: TeacherLinksListProps) {
  const teachers = useMemo(
    () =>
      Object.keys(payload.teacherLabels)
        .sort((a, b) => (payload.teacherLabels[a] ?? a).localeCompare(payload.teacherLabels[b] ?? b, "fr"))
        .map((code) => ({
          code,
          label: payload.teacherLabels[code] ?? code,
          link: buildLink({ vue: "prof", prof: code, mode: "prof", t: payload.teacherTokens[code] ?? "" }),
        })),
    [payload.teacherLabels, payload.teacherTokens],
  );

  return (
    <div className="panel">
      <h3>Liens de tous les enseignants</h3>
      <div className="teacherlinks">
        {teachers.map((t) => (
          <div className="teacherlinks-row" key={t.code}>
            <span className="teacherlinks-name">
              {t.label} <span className="mono muted">{t.code}</span>
            </span>
            <input className="teacherlinks-input mono" type="text" readOnly value={t.link} onFocus={(e) => e.currentTarget.select()} />
            <CopyButton text={t.link} idleLabel="Copier" />
          </div>
        ))}
      </div>
    </div>
  );
}
