import { useMemo, useState } from "react";

import { CopyButton } from "./CopyButton";
import { OpenLinkButton } from "./OpenLinkButton";
import { buildLink } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";

interface TeacherLinksListProps {
  payload: AppPayload;
}

/** Vue simple : un enseignant, une ligne, son lien perso — rien d'autre
 * (retour utilisateur 27/08/2026 : « ajoute moi une vue simple avec tous
 * les lien de tous les prof »). L'annuaire complet (séances, heures, mail,
 * export CSV, + les groupes) reste dans Référence → Liens & partage ; ici,
 * juste la liste à copier vite — avec un filtre, pour ne pas faire défiler
 * soixante noms pour en trouver un. */
export function TeacherLinksList({ payload }: TeacherLinksListProps) {
  const [filtre, setFiltre] = useState("");
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
  const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const visibles = filtre ? teachers.filter((t) => norm(`${t.label} ${t.code}`).includes(norm(filtre))) : teachers;

  return (
    <div className="panel">
      <div className="teacherlinks-entete">
        <h3>Liens de tous les enseignants</h3>
        <input
          type="search"
          value={filtre}
          onChange={(e) => setFiltre(e.target.value)}
          placeholder="Filtrer par nom ou code"
          aria-label="Filtrer les enseignants"
        />
      </div>
      <div className="teacherlinks">
        {visibles.map((t) => (
          <div className="teacherlinks-row" key={t.code}>
            <span className="teacherlinks-name">
              {t.label} <span className="mono muted">{t.code}</span>
            </span>
            <input className="teacherlinks-input mono" type="text" readOnly value={t.link} onFocus={(e) => e.currentTarget.select()} aria-label={`Lien de ${t.label}`} />
            <span className="lien-boutons">
              <CopyButton text={t.link} idleLabel="Copier" />
              <OpenLinkButton href={t.link} />
            </span>
          </div>
        ))}
        {visibles.length === 0 && <p className="muted">Aucun enseignant ne correspond.</p>}
      </div>
    </div>
  );
}
