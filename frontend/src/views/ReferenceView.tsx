import { useMemo, useState } from "react";

import type { Route } from "../hooks/useHashRoute";
import { buildLink } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { copyToClipboard } from "../utils/clipboard";
import { downloadDirectoryCsv, type CsvRow } from "../utils/csv";
import { downloadIcs, sessionsWithDates } from "../utils/ics";
import { mailtoForTeacher } from "../utils/mailto";

type SubTab = "salles" | "cours" | "calendrier" | "liens";

interface ReferenceViewProps {
  payload: AppPayload;
  setRoute: (patch: Partial<Route>) => void;
}

export function ReferenceView({ payload, setRoute }: ReferenceViewProps) {
  const [sub, setSub] = useState<SubTab>("salles");

  return (
    <section className="view">
      <div className="subtabbar">
        {(["salles", "cours", "calendrier", "liens"] as SubTab[]).map((s) => (
          <button key={s} type="button" className={`subtabbtn ${sub === s ? "active" : ""}`} onClick={() => setSub(s)}>
            {s === "salles" ? "Salles" : s === "cours" ? "Cours" : s === "calendrier" ? "Calendrier" : "Liens & partage"}
          </button>
        ))}
      </div>

      {sub === "salles" && <RoomsTable payload={payload} />}
      {sub === "cours" && <CoursesTable payload={payload} setRoute={setRoute} />}
      {sub === "calendrier" && <CalendarTimeline payload={payload} />}
      {sub === "liens" && <LinksDirectory payload={payload} />}
    </section>
  );
}

function RoomsTable({ payload }: { payload: AppPayload }) {
  return (
    <div className="panel ref-table-wrap">
      <table className="ref">
        <thead>
          <tr>
            <th>Salle</th>
            <th>Capacité</th>
            <th>Type</th>
            <th>Équipement</th>
            <th>Séances</th>
          </tr>
        </thead>
        <tbody>
          {payload.rooms.map((r) => (
            <tr key={r.id}>
              <td>{r.label}</td>
              <td>{r.capacity}</td>
              <td>{r.type}</td>
              <td>{r.equipment.join(", ") || "—"}</td>
              <td>{r.nSessions}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CoursesTable({ payload, setRoute }: { payload: AppPayload; setRoute: (patch: Partial<Route>) => void }) {
  return (
    <div className="panel ref-table-wrap">
      <table className="ref">
        <thead>
          <tr>
            <th>Code</th>
            <th>Nom</th>
            <th>Semestre</th>
            <th>Parcours</th>
            <th>CM</th>
            <th>TD</th>
            <th>TP</th>
            <th>Éval</th>
            <th>Placées</th>
            <th>Enseignants</th>
          </tr>
        </thead>
        <tbody>
          {payload.courses.map((c) => (
            <tr key={`${c.code}-${c.parcours}`}>
              <td>
                <button
                  type="button"
                  className="linklike"
                  onClick={() => setRoute({ vue: "semaine", groupe: "" })}
                  title="Voir en Vue Semaine"
                >
                  {c.code}
                </button>
              </td>
              <td>{c.name}</td>
              <td>{c.semestre}</td>
              <td>{c.parcours}</td>
              <td>{c.nCM}</td>
              <td>{c.nTD}</td>
              <td>{c.nTP}</td>
              <td>{c.nEval}</td>
              <td>{c.nPlaced}</td>
              <td>{c.teachers.map((t) => payload.teacherLabels[t] ?? t).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CalendarTimeline({ payload }: { payload: AppPayload }) {
  return (
    <div className="panel timeline">
      {payload.institutionalCalendar.map((ev) => (
        <div key={`${ev.label}-${ev.start}`} className={`timeline-item ${ev.kind}`}>
          <div className="kind">{ev.kind}</div>
          <div className="label">{ev.label}</div>
          <div className="dates">
            {ev.start === ev.end ? ev.start : `${ev.start} → ${ev.end}`}
          </div>
        </div>
      ))}
    </div>
  );
}

function LinksDirectory({ payload }: { payload: AppPayload }) {
  const teacherCodes = useMemo(
    () =>
      Object.keys(payload.teacherLabels).sort((a, b) =>
        (payload.teacherLabels[a] ?? a).localeCompare(payload.teacherLabels[b] ?? b, "fr"),
      ),
    [payload.teacherLabels],
  );
  const groupIds = useMemo(
    () =>
      Object.keys(payload.groupLabels).sort((a, b) =>
        (payload.groupLabels[a] ?? a).localeCompare(payload.groupLabels[b] ?? b, "fr"),
      ),
    [payload.groupLabels],
  );

  const teacherItems = teacherCodes.map((code) => ({
    code,
    label: payload.teacherLabels[code] ?? code,
    items: sessionsWithDates(payload, payload.rows.filter((r) => r.te.includes(code))),
    link: buildLink({ vue: "prof", prof: code, mode: "prof", t: payload.teacherTokens[code] ?? "" }),
    mail: payload.teacherEmails[code] || "",
  }));
  const groupItems = groupIds.map((gid) => {
    const cohort = new Set(payload.groupCohort[gid] ?? [gid]);
    return {
      code: gid,
      label: payload.groupLabels[gid] ?? gid,
      items: sessionsWithDates(payload, payload.rows.filter((r) => r.g.some((g) => cohort.has(g)))),
      link: buildLink({ vue: "groupe", groupe: gid, mode: "groupe" }),
      mail: "",
    };
  });

  const allRows = (): CsvRow[] =>
    [
      ...teacherItems.map((t) => ({ type: "Enseignant", ...t })),
      ...groupItems.map((g) => ({ type: "Groupe", ...g })),
    ].map((r) => ({
      type: r.type,
      label: r.label,
      code: r.code,
      mail: r.mail,
      count: r.items.length,
      hours: r.items.reduce((n, it) => n + (it.dur || 1), 0) * 1.5,
      link: r.link,
    }));

  const copyAll = async () => {
    const text = [...teacherItems, ...groupItems].map((r) => `${r.label}\t${r.link}`).join("\n");
    await copyToClipboard(text);
  };

  return (
    <div className="panel">
      <p className="muted">
        Un lien par destinataire, à transmettre tel quel : il ouvre le fichier directement sur SON planning, en
        lecture seule. Le bouton <span className="mono">.ics</span> produit un fichier à importer dans son propre
        agenda.
      </p>
      <div className="linkactions">
        <button type="button" className="btn btn--ghost btn--sm" onClick={copyAll}>
          Copier tous les liens
        </button>
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => downloadDirectoryCsv(allRows())}>
          Télécharger l'annuaire (.csv)
        </button>
      </div>

      <h4>Enseignants</h4>
      <div className="ref-table-wrap">
        <table className="ref">
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}>Enseignant</th>
              <th>Séances</th>
              <th>Heures</th>
              <th>Lien</th>
              <th>Agenda</th>
              <th>Mail</th>
            </tr>
          </thead>
          <tbody>
            {teacherItems.map((t) => (
              <DirectoryRow key={t.code} row={t} payload={payload} showMail />
            ))}
          </tbody>
        </table>
      </div>

      <h4>Groupes étudiants</h4>
      <div className="ref-table-wrap">
        <table className="ref">
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}>Groupe</th>
              <th>Séances</th>
              <th>Heures</th>
              <th>Lien</th>
              <th>Agenda</th>
            </tr>
          </thead>
          <tbody>
            {groupItems.map((g) => (
              <DirectoryRow key={g.code} row={g} payload={payload} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DirectoryRow({
  row,
  payload,
  showMail = false,
}: {
  row: { code: string; label: string; items: ReturnType<typeof sessionsWithDates>; link: string; mail: string };
  payload: AppPayload;
  showMail?: boolean;
}) {
  const hours = (row.items.reduce((n, it) => n + (it.dur || 1), 0) * 1.5).toLocaleString("fr-FR");
  return (
    <tr>
      <td style={{ textAlign: "left" }}>
        <strong>{row.label}</strong> <span className="mono muted">{row.code}</span>
      </td>
      <td>{row.items.length}</td>
      <td>{hours} h</td>
      <td>
        <button type="button" className="subtabbtn small" onClick={() => copyToClipboard(row.link)}>
          Copier
        </button>
      </td>
      <td>
        <button
          type="button"
          className="subtabbtn small"
          onClick={() => downloadIcs(row.items, row.label, row.code, payload.groupLabels, payload.teacherLabels)}
        >
          .ics
        </button>
      </td>
      {showMail && (
        <td>
          <a
            className="subtabbtn small"
            href={mailtoForTeacher(payload, row.code, row.items, row.link)}
            title={row.mail || "Adresse inconnue"}
          >
            Écrire{row.mail ? "" : " ⚠"}
          </a>
        </td>
      )}
    </tr>
  );
}
