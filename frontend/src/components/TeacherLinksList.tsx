import { useMemo, useState } from "react";

import { CopyButton } from "./CopyButton";
import { OpenLinkButton } from "./OpenLinkButton";
import { buildLink } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import "./TeacherLinksList.css";

interface TeacherLinksListProps {
  payload: AppPayload;
}

function normaliser(t: string): string {
  return t
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
}

/** Vue simple : un enseignant, une ligne, son lien perso — rien d'autre
 * (retour utilisateur 27/08/2026 : « ajoute moi une vue simple avec tous
 * les lien de tous les prof »). L'annuaire complet (séances, heures, mail,
 * export CSV, + les groupes) reste dans Référence → Liens & partage ; ici,
 * juste la liste à copier vite — filtrable, avec un « tout copier ». */
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
  const q = normaliser(filtre.trim());
  const visibles = q ? teachers.filter((t) => normaliser(`${t.label} ${t.code}`).includes(q)) : teachers;

  return (
    <div className="panel teacherlinks-panel">
      <div className="teacherlinks-tete">
        <h3>Liens de tous les enseignants</h3>
        <input
          type="search"
          placeholder="Filtrer…"
          aria-label="Filtrer les enseignants"
          value={filtre}
          onChange={(e) => setFiltre(e.target.value)}
        />
        <CopyButton
          text={() => visibles.map((t) => `${t.label}\t${t.link}`).join("\n")}
          idleLabel={q ? `Copier ces ${visibles.length} liens` : "Copier tous les liens"}
          className="btn btn--sm"
        />
      </div>
      <div className="teacherlinks">
        {visibles.map((t) => (
          <div className="teacherlinks-row" key={t.code}>
            <span className="teacherlinks-name">
              {t.label} <span className="mono teacherlinks-code">{t.code}</span>
            </span>
            <input
              className="teacherlinks-input mono"
              type="text"
              readOnly
              aria-label={`Lien de ${t.label}`}
              value={t.link}
              onFocus={(e) => e.currentTarget.select()}
            />
            <span className="lien-boutons">
              <CopyButton text={t.link} idleLabel="Copier" />
              <OpenLinkButton href={t.link} />
            </span>
          </div>
        ))}
        {visibles.length === 0 && <p className="teacherlinks-vide">Aucun enseignant ne correspond.</p>}
      </div>
    </div>
  );
}
