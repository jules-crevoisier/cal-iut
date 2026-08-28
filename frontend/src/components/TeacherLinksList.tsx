import { useMemo, useState } from "react";

import { buildLink } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { copyToClipboard } from "../utils/clipboard";

interface TeacherLinksListProps {
  payload: AppPayload;
}

/** Vue simple : un enseignant, une ligne, son lien perso — rien d'autre
 * (retour utilisateur 27/08/2026 : « ajoute moi une vue simple avec tous
 * les lien de tous les prof »). L'annuaire complet (séances, heures, mail,
 * export CSV, + les groupes) reste dans Référentiel → Référence → Liens &
 * partage, pour qui a besoin de plus ; ici, juste la liste à copier vite. */
export function TeacherLinksList({ payload }: TeacherLinksListProps) {
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  const teachers = useMemo(
    () =>
      Object.keys(payload.teacherLabels)
        .sort((a, b) => (payload.teacherLabels[a] ?? a).localeCompare(payload.teacherLabels[b] ?? b, "fr"))
        .map((code) => ({ code, label: payload.teacherLabels[code] ?? code, link: buildLink({ vue: "prof", prof: code, mode: "prof" }) })),
    [payload.teacherLabels],
  );

  const handleCopy = async (code: string, link: string) => {
    const ok = await copyToClipboard(link);
    if (ok) {
      setCopiedCode(code);
      setTimeout(() => setCopiedCode((c) => (c === code ? null : c)), 1400);
    }
  };

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
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => handleCopy(t.code, t.link)}>
              {copiedCode === t.code ? "Copié ✓" : "Copier"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
