/**
 * Régénération ciblée d'UNE semaine + exceptions ponctuelles — portage de la
 * section "ONGLET SEMAINE" de `export/templates/timetable.html`
 * (`renderExceptionList` + le handler `regenBtn`), jamais câblée côté React
 * jusqu'ici (retour utilisateur 11/08/2026 : le bouton "Régénérer" de la
 * Toolbar relance TOUT le solveur au lieu de cette régénération ciblée — cf.
 * docs/DATA.md).
 *
 * Recalcule UNIQUEMENT la semaine affichée (+ la suivante si coché), en
 * tenant compte des exceptions ci-dessous — jamais tout le semestre, jamais
 * une semaine passée/en cours (`week_status`, même garde-fou que le
 * glisser-déposer).
 */

import { useEffect, useState } from "react";

import {
  createException,
  deleteException,
  fetchRegenStatus,
  listExceptions,
  regenWeek,
} from "../api/client";
import type { Placement, RoomMeta } from "../types";
import type { AppException, WeekStatusRow } from "../types/app";

interface RegenPanelProps {
  week: number; // semaine solveur affichée (0-indexée)
  weekLabel: string;
  weekStatus: WeekStatusRow[];
  teacherCodes: string[];
  teacherLabels: Record<string, string>;
  rooms: RoomMeta[];
  onRegenerated: (placements: Placement[]) => void;
  onNotice: (msg: string) => void;
}

export function RegenPanel({
  week,
  weekLabel,
  weekStatus,
  teacherCodes,
  teacherLabels,
  rooms,
  onRegenerated,
  onNotice,
}: RegenPanelProps) {
  const [exceptions, setExceptions] = useState<AppException[]>([]);
  const [extendNext, setExtendNext] = useState(false);
  const [regenStatus, setRegenStatus] = useState("");
  const [regenBusy, setRegenBusy] = useState(false);

  const [excKind, setExcKind] = useState<"teacher_absence" | "room_unavailable">("teacher_absence");
  const [excDate, setExcDate] = useState("");
  const [excTeacher, setExcTeacher] = useState(teacherCodes[0] ?? "");
  const [excRoom, setExcRoom] = useState(rooms[0]?.id ?? "");
  const [excReason, setExcReason] = useState("");
  const [excBusy, setExcBusy] = useState(false);

  const editable = weekStatus.find((w) => w.week === week)?.status === "future";

  const refreshExceptions = () => {
    listExceptions()
      .then(setExceptions)
      .catch(() => {});
  };

  useEffect(refreshExceptions, []);

  const handleDeleteException = async (id: number) => {
    await deleteException(id).catch(() => {});
    setExceptions((prev) => prev.filter((e) => e.id !== id));
  };

  const handleSubmitException = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!excDate) return;
    setExcBusy(true);
    try {
      const created = await createException({
        kind: excKind,
        exception_date: excDate,
        teacher_code: excKind === "teacher_absence" ? excTeacher || null : null,
        room_id: excKind === "room_unavailable" ? excRoom || null : null,
        reason: excReason || null,
      });
      setExceptions((prev) => [...prev, created]);
      setExcDate("");
      setExcReason("");
    } catch (err) {
      onNotice(err instanceof Error ? err.message : "Erreur lors de la création de l'exception.");
    } finally {
      setExcBusy(false);
    }
  };

  const handleRegen = async () => {
    setRegenBusy(true);
    setRegenStatus("Lancement…");
    let jobId: string;
    try {
      const started = await regenWeek(week, extendNext);
      jobId = started.job_id;
    } catch (err) {
      setRegenStatus(err instanceof Error ? err.message : "Erreur réseau.");
      setRegenBusy(false);
      return;
    }
    setRegenStatus("Régénération en cours…");
    const poll = async () => {
      let st;
      try {
        st = await fetchRegenStatus(jobId);
      } catch {
        setTimeout(poll, 4000); // réessaiera au prochain sondage
        return;
      }
      if (st.status === "running") {
        setTimeout(poll, 4000);
        return;
      }
      setRegenBusy(false);
      if (st.status === "error") {
        setRegenStatus(`Échec : ${st.error}`);
        return;
      }
      const result = st.result;
      if (result.status !== "OPTIMAL" && result.status !== "FEASIBLE") {
        setRegenStatus(`Échec (${result.status}) — rien n'a été modifié.`);
        return;
      }
      onRegenerated(result.placements);
      setRegenStatus(`Terminé — ${result.placements.length} séance(s) mise(s) à jour.`);
    };
    setTimeout(poll, 4000);
  };

  return (
    <div className="panel">
      <h3>Régénération ciblée</h3>
      <p className="muted" style={{ fontSize: "0.82rem", margin: "0 0 10px" }}>
        Recalcule uniquement {weekLabel} (ou + la suivante), en tenant compte des exceptions ci-dessous. Les autres
        semaines ne sont jamais touchées.
      </p>
      {!editable && (
        <p className="muted" style={{ fontSize: "0.82rem", margin: "0 0 10px" }}>
          Semaine passée ou en cours — lecture seule, non régénérable.
        </p>
      )}
      <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.86rem", marginBottom: 10 }}>
        <input type="checkbox" checked={extendNext} onChange={(e) => setExtendNext(e.target.checked)} />
        + semaine suivante (pour mieux réagencer)
      </label>
      <button
        type="button"
        className="btn btn--accent"
        style={{ width: "100%" }}
        disabled={!editable || regenBusy}
        onClick={handleRegen}
      >
        {regenBusy ? "Régénération…" : "Régénérer cette semaine"}
      </button>
      {regenStatus && (
        <div className="muted" style={{ marginTop: 8, fontSize: "0.84rem" }}>
          {regenStatus}
        </div>
      )}

      <h4>Exceptions ponctuelles</h4>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 12 }}>
        {exceptions.length === 0 ? (
          <p className="muted" style={{ fontSize: "0.84rem" }}>
            Aucune exception active.
          </p>
        ) : (
          exceptions.map((e) => (
            <div key={e.id} className="teacher-card">
              <header>
                <h4 style={{ fontSize: "0.86rem", margin: 0 }}>
                  {e.kind === "teacher_absence" ? "Absence" : "Salle indispo"} — {e.exception_date}
                </h4>
                <button type="button" className="subtabbtn small" onClick={() => handleDeleteException(e.id)}>
                  Supprimer
                </button>
              </header>
              <div className="muted" style={{ fontSize: "0.82rem" }}>
                {e.kind === "teacher_absence"
                  ? teacherLabels[e.teacher_code ?? ""] ?? e.teacher_code
                  : rooms.find((r) => r.id === e.room_id)?.label ?? e.room_id ?? "—"}
                {e.reason ? ` — ${e.reason}` : ""}
              </div>
            </div>
          ))
        )}
      </div>

      <form onSubmit={handleSubmitException} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <select value={excKind} onChange={(e) => setExcKind(e.target.value as typeof excKind)}>
          <option value="teacher_absence">Enseignant absent</option>
          <option value="room_unavailable">Salle indisponible</option>
        </select>
        <input type="date" required value={excDate} onChange={(e) => setExcDate(e.target.value)} />
        {excKind === "teacher_absence" ? (
          <select value={excTeacher} onChange={(e) => setExcTeacher(e.target.value)}>
            {teacherCodes.map((code) => (
              <option key={code} value={code}>
                {teacherLabels[code] ?? code}
              </option>
            ))}
          </select>
        ) : (
          <select value={excRoom} onChange={(e) => setExcRoom(e.target.value)}>
            {rooms.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label}
              </option>
            ))}
          </select>
        )}
        <input
          type="text"
          placeholder="Motif (optionnel)"
          value={excReason}
          onChange={(e) => setExcReason(e.target.value)}
        />
        <button type="submit" className="subtabbtn" disabled={excBusy}>
          Ajouter l'exception
        </button>
      </form>
    </div>
  );
}
