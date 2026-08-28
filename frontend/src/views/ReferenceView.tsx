import { useMemo, useState } from "react";

import { sendTeacherMails } from "../api/client";
import { SendTeacherMailsModal } from "../components/SendTeacherMailsModal";
import type { Route } from "../hooks/useHashRoute";
import { buildLink } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { copyToClipboard } from "../utils/clipboard";
import { confirmAsync } from "../utils/confirmDialog";
import { downloadDirectoryCsv, type CsvRow } from "../utils/csv";
import { downloadIcs, sessionsWithDates } from "../utils/ics";

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
  const [showMailModal, setShowMailModal] = useState(false);
  const teacherCodes = useMemo(
    () =>
      Object.keys(payload.teacherLabels).sort((a, b) =>
        (payload.teacherLabels[a] ?? a).localeCompare(payload.teacherLabels[b] ?? b, "fr"),
      ),
    [payload.teacherLabels],
  );
  // Groupes "promo" (CM seul) écartés de l'annuaire — retour utilisateur
  // 28/08/2026 : « clean up les groupes étudiant... les promo, les groupe à
  // 0h... on peut enlever ». Un TD/TP a déjà les séances CM de sa promo
  // fusionnées dans son propre lien (`groupCohort`, cf. GroupeView) : la
  // ligne "promo" à part ne montre qu'un SOUS-ENSEMBLE de ce que n'importe
  // quel TD/TP de la même cohorte affiche déjà — jamais le lien le plus
  // utile à partager. Les groupes à 0 séance (cohortes FC à groupe unique,
  // ex. BUT3-DEV-FC : tout est émis côté TD, le "TP" qui les porte pour le
  // solveur reste vide côté planning) sont écartés séparément, une fois les
  // séances effectivement comptées ci-dessous.
  const groupIds = useMemo(
    () =>
      Object.keys(payload.groupLabels)
        .filter((gid) => payload.groupKind[gid] !== "promo")
        .sort((a, b) => {
          const pa = payload.groupParcours[a] ?? "";
          const pb = payload.groupParcours[b] ?? "";
          return pa !== pb
            ? pa.localeCompare(pb, "fr")
            : (payload.groupLabels[a] ?? a).localeCompare(payload.groupLabels[b] ?? b, "fr");
        }),
    [payload.groupLabels, payload.groupKind, payload.groupParcours],
  );

  const teacherItems = teacherCodes.map((code) => ({
    code,
    label: payload.teacherLabels[code] ?? code,
    items: sessionsWithDates(payload, payload.rows.filter((r) => r.te.includes(code))),
    link: buildLink({ vue: "prof", prof: code, mode: "prof", t: payload.teacherTokens[code] ?? "" }),
    mail: payload.teacherEmails[code] || "",
  }));
  const groupItems = groupIds
    .map((gid) => {
      const cohort = new Set(payload.groupCohort[gid] ?? [gid]);
      const parcours = payload.groupParcours[gid];
      return {
        code: gid,
        // "TD GH" seul existe en double (BUT2-CREACOM-FC ET BUT3-CREACOM-FC,
        // labels identiques sinon) — le parcours en préfixe désambiguïse
        // partout où cette liste s'affiche à plat.
        label: parcours ? `${parcours} · ${payload.groupLabels[gid] ?? gid}` : (payload.groupLabels[gid] ?? gid),
        items: sessionsWithDates(payload, payload.rows.filter((r) => r.g.some((g) => cohort.has(g)))),
        link: buildLink({ vue: "groupe", groupe: gid, mode: "groupe" }),
        mail: "",
      };
    })
    .filter((g) => g.items.length > 0);

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
        <button type="button" className="btn btn--accent btn--sm" onClick={() => setShowMailModal(true)}>
          Envoyer les liens par mail
        </button>
      </div>
      {showMailModal && <SendTeacherMailsModal onClose={() => setShowMailModal(false)} />}

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
  // Envoi ciblé à CETTE seule personne — retour utilisateur 28/08/2026 :
  // « remplacer le bouton mail écrire par un bouton qui envoie le mail à la
  // personne avec son lien, au cas où on veuille envoyer le lien à une
  // seule personne ». Réutilise le même endpoint que l'envoi groupé
  // (`SendTeacherMailsModal`), juste avec UN code au lieu de la sélection
  // entière — remplace le brouillon `mailto:` (qui n'envoyait rien tout
  // seul) par un vrai envoi.
  const [etatEnvoi, setEtatEnvoi] = useState<"repos" | "envoi" | "ok" | "echec">("repos");
  const [erreurEnvoi, setErreurEnvoi] = useState<string | null>(null);

  const envoyer = async () => {
    // Vraie popup de confirmation AVANT l'envoi (retour utilisateur
    // 28/08/2026 : « je veux des vrais popup de confirmation ») — une
    // modale interne (`confirmAsync`), pas `window.confirm` (peut être
    // désactivé par un bloqueur de popups, cf. utils/confirmDialog.ts).
    const confirme = await confirmAsync(`Envoyer l'emploi du temps à ${row.label} (${row.mail}) ?`, {
      title: "Confirmer l'envoi",
      confirmLabel: "Envoyer",
      cancelLabel: "Annuler",
    });
    if (!confirme) return;

    setEtatEnvoi("envoi");
    setErreurEnvoi(null);
    try {
      const { results } = await sendTeacherMails([row.code]);
      const resultat = results[0];
      if (resultat?.ok) {
        setEtatEnvoi("ok");
      } else {
        setEtatEnvoi("echec");
        setErreurEnvoi(resultat?.error ?? "Échec de l'envoi.");
      }
    } catch (e) {
      setEtatEnvoi("echec");
      setErreurEnvoi(e instanceof Error ? e.message : "Échec de l'envoi.");
    }
  };

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
          <button
            type="button"
            className="subtabbtn small"
            onClick={envoyer}
            disabled={!row.mail || etatEnvoi === "envoi"}
            title={row.mail || "Adresse inconnue — à compléter dans data/config/teacher_contacts.yaml"}
          >
            {etatEnvoi === "envoi"
              ? "Envoi…"
              : etatEnvoi === "ok"
                ? "Envoyé ✓"
                : etatEnvoi === "echec"
                  ? "Échec ✗"
                  : `Envoyer${row.mail ? "" : " ⚠"}`}
          </button>
          {erreurEnvoi && <div className="alerte small">{erreurEnvoi}</div>}
        </td>
      )}
    </tr>
  );
}
