import { useEffect, useMemo, useState } from "react";

import type { CreerSeanceBody } from "../api/client";
import { modifierSeancePersonnalisee } from "../api/client";
import type { Placement } from "../types";
import type { AppPayload } from "../types/app";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";
import { creerSeanceAvecConfirmation } from "../utils/placement";

const TYPES = ["CM", "TD", "TP", "PTUT"] as const;
const DUREES = [
  { slots: 1, label: "1h30" },
  { slots: 2, label: "3h" },
];

interface CreerSeanceModalProps {
  payload: AppPayload;
  /** Présent = édition d'une séance personnalisée existante ; absent =
   * création. Les deux partagent le même formulaire — retour utilisateur
   * 31/08/2026 : « création + suppression + modification complète ». */
  seanceExistante?: Placement | null;
  /** Matière/groupe(s) déjà connus quand on ouvre depuis une ligne précise
   * (ex. Vue Promo, colonne d'un groupe) — pré-remplit sans forcer. */
  suggestion?: { courseCode?: string; groupId?: string; week?: number; day?: number } | null;
  onCree: (placement: Placement) => void;
  onCancel: () => void;
}

/** Créer, ou modifier, une séance ajoutée à une matière existante — retour
 * utilisateur 31/08/2026 : « il va falloir créer un système où l'on peut
 * créer des cours pour une matière [...] imaginons dans une matière on
 * veuille rajouter un CM éval ou un TD, il faut pouvoir le faire ».
 *
 * Un seul écran choisit TOUT, y compris le créneau (décision explicite de
 * l'utilisateur plutôt qu'un placement différé par clic sur la grille) :
 * matière, type, groupe(s), enseignant(s), durée, éval, note, et la
 * position (semaine/jour/créneau/salle). La salle reste optionnelle —
 * "Automatique" laisse le serveur la résoudre, comme partout ailleurs. */
export function CreerSeanceModal({
  payload,
  seanceExistante = null,
  suggestion = null,
  onCree,
  onCancel,
}: CreerSeanceModalProps) {
  const coursTries = useMemo(
    () => [...payload.courses].sort((a, b) => a.code.localeCompare(b.code, "fr")),
    [payload.courses],
  );

  const coursInitial = seanceExistante
    ? coursTries.find((c) => c.code === seanceExistante.course_code)
    : suggestion?.courseCode
      ? coursTries.find((c) => c.code === suggestion.courseCode)
      : null;

  const [courseCode, setCourseCode] = useState(coursInitial?.code ?? coursTries[0]?.code ?? "");
  const courseChoisi = coursTries.find((c) => c.code === courseCode) ?? coursTries[0];

  const [sessionType, setSessionType] = useState<string>(seanceExistante?.session_type ?? "TD");
  const [groupIds, setGroupIds] = useState<string[]>(
    seanceExistante?.group_ids ?? (suggestion?.groupId ? [suggestion.groupId] : []),
  );
  const [teacherCodes, setTeacherCodes] = useState(
    (seanceExistante?.teacher_codes ?? []).join(", "),
  );
  const [dureeSlots, setDureeSlots] = useState(seanceExistante?.duration_slots ?? 1);
  const [isEval, setIsEval] = useState(seanceExistante?.is_eval ?? false);
  const [note, setNote] = useState("");
  const [week, setWeek] = useState(seanceExistante?.week ?? suggestion?.week ?? payload.weekRows[0]?.weekIndex ?? 0);
  const [day, setDay] = useState(seanceExistante?.day ?? suggestion?.day ?? 0);
  const [slot, setSlot] = useState(seanceExistante?.slot ?? 0);
  const [roomId, setRoomId] = useState(seanceExistante?.room_id ?? "");
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  // Les groupes cochables se limitent au parcours de la matière choisie —
  // cocher un groupe hors sujet n'aurait aucun sens et compliquerait la
  // liste pour rien.
  const groupesDuParcours = useMemo(() => {
    if (!courseChoisi) return [];
    return Object.keys(payload.groupLabels)
      .filter((gid) => payload.groupParcours[gid] === courseChoisi.parcours)
      .sort((a, b) => (payload.groupLabels[a] ?? a).localeCompare(payload.groupLabels[b] ?? b, "fr"));
  }, [courseChoisi, payload.groupLabels, payload.groupParcours]);

  const semainesDisponibles = useMemo(
    () => payload.weekRows.filter((w): w is typeof w & { weekIndex: number } => w.weekIndex !== null),
    [payload.weekRows],
  );

  const basculerGroupe = (gid: string) => {
    setGroupIds((prev) => (prev.includes(gid) ? prev.filter((g) => g !== gid) : [...prev, gid]));
  };

  const valider = async () => {
    if (!courseChoisi) {
      setErreur("Choisissez une matière.");
      return;
    }
    if (groupIds.length === 0) {
      setErreur("Cochez au moins un groupe.");
      return;
    }
    setEnCours(true);
    setErreur(null);

    const enseignants = teacherCodes
      .split(",")
      .map((t) => t.trim().toUpperCase())
      .filter(Boolean);

    if (seanceExistante) {
      try {
        const placement = await modifierSeancePersonnalisee(seanceExistante.session_id, {
          session_type: sessionType,
          group_ids: groupIds,
          teacher_codes: enseignants,
          duration_slots: dureeSlots,
          is_eval: isEval,
          note,
          week,
          day,
          slot,
          room_id: roomId || null,
        });
        onCree(placement);
      } catch (e) {
        setErreur(e instanceof Error ? e.message : "Modification impossible");
      } finally {
        setEnCours(false);
      }
      return;
    }

    const corps: CreerSeanceBody = {
      course_code: courseChoisi.code,
      session_type: sessionType,
      group_ids: groupIds,
      teacher_codes: enseignants,
      duration_slots: dureeSlots,
      is_eval: isEval,
      note,
      week,
      day,
      slot,
      room_id: roomId || null,
    };
    const resultat = await creerSeanceAvecConfirmation(corps);
    setEnCours(false);
    if (resultat.ok) {
      onCree(resultat.placement);
    } else {
      setErreur(resultat.message);
    }
  };

  return (
    <div className="confirmmodal-overlay" role="presentation" onClick={onCancel}>
      <form
        className="panel confirmmodal seancemodal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="seancemodal-titre"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          void valider();
        }}
      >
        <h3 id="seancemodal-titre">{seanceExistante ? "Modifier la séance" : "Nouvelle séance"}</h3>
        <p className="muted small">
          {seanceExistante
            ? "Cette séance a été ajoutée manuellement — elle reste modifiable et supprimable ici."
            : "Ajoute une heure à une matière existante et la place directement, comme un déplacement manuel."}
        </p>

        <div className="seancemodal-grille">
          <label className="newroom-field newroom-field--large">
            Matière
            <select value={courseCode} disabled={!!seanceExistante} onChange={(e) => setCourseCode(e.target.value)}>
              {coursTries.map((c) => (
                <option key={`${c.code}-${c.parcours}`} value={c.code}>
                  {c.code} — {c.name} ({c.parcours})
                </option>
              ))}
            </select>
          </label>

          <label className="newroom-field">
            Type
            <select value={sessionType} onChange={(e) => setSessionType(e.target.value)}>
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>

          <label className="newroom-field">
            Durée
            <select value={dureeSlots} onChange={(e) => setDureeSlots(Number(e.target.value))}>
              {DUREES.map((d) => (
                <option key={d.slots} value={d.slots}>
                  {d.label}
                </option>
              ))}
            </select>
          </label>

          <div className="newroom-field newroom-field--large">
            Groupe(s)
            <div className="newroom-field-groupes">
              {groupesDuParcours.length === 0 && <span className="muted small">Aucun groupe pour ce parcours.</span>}
              {groupesDuParcours.map((gid) => (
                <label key={gid}>
                  <input type="checkbox" checked={groupIds.includes(gid)} onChange={() => basculerGroupe(gid)} />
                  {payload.groupLabels[gid] ?? gid}
                </label>
              ))}
            </div>
          </div>

          <label className="newroom-field">
            Enseignant(s)
            <input
              type="text"
              value={teacherCodes}
              placeholder="ex. MRI, JSA"
              onChange={(e) => setTeacherCodes(e.target.value)}
            />
          </label>

          <label className="newroom-field newroom-field--checkbox">
            <input type="checkbox" checked={isEval} onChange={(e) => setIsEval(e.target.checked)} />
            Évaluation
          </label>

          <label className="newroom-field newroom-field--large">
            Note (optionnel)
            <textarea
              value={note}
              maxLength={300}
              placeholder="ex. Rattrapage suite à l'absence du 12/09"
              onChange={(e) => setNote(e.target.value)}
            />
          </label>

          <label className="newroom-field">
            Semaine
            <select value={week} onChange={(e) => setWeek(Number(e.target.value))}>
              {semainesDisponibles.map((w) => (
                <option key={w.weekIndex} value={w.weekIndex}>
                  {w.label}
                </option>
              ))}
            </select>
          </label>

          <label className="newroom-field">
            Jour
            <select value={day} onChange={(e) => setDay(Number(e.target.value))}>
              {DAY_LABELS.map((label, i) => (
                <option key={label} value={i}>
                  {label}
                </option>
              ))}
            </select>
          </label>

          <label className="newroom-field">
            Créneau
            <select value={slot} onChange={(e) => setSlot(Number(e.target.value))}>
              {SLOT_TIMES.map((s, i) => (
                <option key={s.label} value={i}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>

          <label className="newroom-field">
            Salle
            <select value={roomId} onChange={(e) => setRoomId(e.target.value)}>
              <option value="">Automatique</option>
              {payload.rooms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {erreur && <p className="alerte">{erreur}</p>}

        <div className="confirmmodal-actions">
          <button type="button" className="btn btn--ghost" onClick={onCancel}>
            Annuler
          </button>
          <button type="submit" className="btn btn--accent" disabled={enCours}>
            {enCours ? "…" : seanceExistante ? "Enregistrer" : "Créer et placer"}
          </button>
        </div>
      </form>
    </div>
  );
}
