import { useMemo, useState } from "react";

import type { CreerEvenementBody } from "../api/client";
import type { Placement } from "../types";
import type { AppPayload } from "../types/app";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";
import { creerEvenementAvecConfirmation } from "../utils/placement";
import { lireDernierWeekDay } from "../utils/creerSeancePrefs";
import { TeacherPicker } from "./TeacherPicker";

const RE_HEURE = /^([01]\d|2[0-3]):[0-5]\d$/;

interface CreerEvenementModalProps {
  payload: AppPayload;
  /** Pré-remplit semaine/jour depuis ce qui est affiché en Vue Promo au
   * moment du clic (même règle que `CreerSeanceModal`). */
  suggestion?: { week?: number; day?: number } | null;
  onCree: (placement: Placement) => void;
  onCancel: () => void;
}

/** Crée un évènement hors maquette (réunion, conférence...) affiché en
 * clair sur l'EDT — retour utilisateur 07/09/2026, étendu le 23/09/2026
 * (Kyllian Bresson : « m'ajouter une séance évènement en CM H.018 pour
 * tout le monde demain (jeudi) à 13h15 jusqu'à 14h [...] sans mettre
 * d'enseignant. Histoire de l'afficher proprement »).
 *
 * `libelle` invente son propre code (`POST /placements/evenements`),
 * jamais besoin d'une matière déjà connue — à la différence de
 * `CreerSeanceModal`. « Heure de début »/« Heure de fin » sont optionnels :
 * ils permettent un horaire RÉEL hors des six créneaux fixes (ex. la pause
 * méridienne, 12h30-14h), affiché tel quel dans la ligne "pause" de Vue
 * Promo plutôt que menti sur un créneau qui ne correspond pas. */
export function CreerEvenementModal({ payload, suggestion = null, onCree, onCancel }: CreerEvenementModalProps) {
  const [libelle, setLibelle] = useState("");
  const [semestre, setSemestre] = useState("S1");
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [teacherCodes, setTeacherCodes] = useState<string[]>([]);
  const [dureeSlots, setDureeSlots] = useState(1);
  const [note, setNote] = useState("");
  const [week, setWeek] = useState(
    () => suggestion?.week ?? lireDernierWeekDay()?.week ?? payload.weekRows[0]?.weekIndex ?? 0,
  );
  const [day, setDay] = useState(() => suggestion?.day ?? lireDernierWeekDay()?.day ?? 0);
  const [slot, setSlot] = useState(0);
  const [roomId, setRoomId] = useState("");
  const [heureDebut, setHeureDebut] = useState("");
  const [heureFin, setHeureFin] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const groupesTries = useMemo(
    () => Object.keys(payload.groupLabels).sort((a, b) => (payload.groupLabels[a] ?? a).localeCompare(payload.groupLabels[b] ?? b, "fr")),
    [payload.groupLabels],
  );
  const semainesDisponibles = useMemo(
    () => payload.weekRows.filter((w): w is typeof w & { weekIndex: number } => w.weekIndex !== null),
    [payload.weekRows],
  );

  const basculerGroupe = (gid: string) => {
    setGroupIds((prev) => (prev.includes(gid) ? prev.filter((g) => g !== gid) : [...prev, gid]));
  };

  const horaireValide = (): string | null => {
    // Les deux vont toujours ensemble — même règle que le serveur
    // (`_valider_horaire_libre`), vérifiée ici pour un message immédiat
    // plutôt qu'un aller-retour réseau.
    if (!heureDebut && !heureFin) return null;
    if (!heureDebut || !heureFin) {
      return "« Heure de début » et « Heure de fin » vont ensemble : remplissez les deux, ou laissez les deux vides.";
    }
    if (!RE_HEURE.test(heureDebut) || !RE_HEURE.test(heureFin)) {
      return "Heure invalide — format attendu HH:MM.";
    }
    if (heureFin <= heureDebut) {
      return "« Heure de fin » doit être après « Heure de début ».";
    }
    return null;
  };

  const valider = async () => {
    if (!libelle.trim()) {
      setErreur("Donnez un libellé à l'évènement.");
      return;
    }
    if (!semestre.trim()) {
      setErreur("Indiquez le semestre concerné.");
      return;
    }
    if (groupIds.length === 0) {
      setErreur("Cochez au moins un groupe.");
      return;
    }
    const erreurHoraire = horaireValide();
    if (erreurHoraire) {
      setErreur(erreurHoraire);
      return;
    }
    setEnCours(true);
    setErreur(null);

    const corps: CreerEvenementBody = {
      libelle: libelle.trim(),
      semestre: semestre.trim(),
      group_ids: groupIds,
      teacher_codes: teacherCodes,
      duration_slots: dureeSlots,
      note,
      week,
      day,
      slot,
      room_id: roomId || null,
      ...(heureDebut && heureFin ? { heure_debut: heureDebut, heure_fin: heureFin } : {}),
    };
    const resultat = await creerEvenementAvecConfirmation(corps);
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
        aria-labelledby="evenementmodal-titre"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          void valider();
        }}
      >
        <h3 id="evenementmodal-titre">Nouvel évènement</h3>
        <p className="muted small">
          Réunion, conférence, présentation... affichée en clair sur l'EDT, sans matière ni progression.
        </p>

        <div className="seancemodal-grille">
          <label className="newroom-field newroom-field--large">
            Libellé
            <input
              type="text"
              value={libelle}
              maxLength={120}
              placeholder="ex. Présentation PAC"
              onChange={(e) => setLibelle(e.target.value)}
            />
          </label>

          <label className="newroom-field">
            Semestre
            <input
              type="text"
              value={semestre}
              maxLength={10}
              placeholder="ex. S1"
              onChange={(e) => setSemestre(e.target.value)}
            />
          </label>

          <label className="newroom-field">
            Durée
            <select value={dureeSlots} onChange={(e) => setDureeSlots(Number(e.target.value))}>
              <option value={1}>1h30</option>
              <option value={2}>3h</option>
            </select>
          </label>

          <div className="newroom-field newroom-field--large">
            Groupe(s)
            <div className="newroom-field-groupes">
              {groupesTries.map((gid) => (
                <label key={gid}>
                  <input type="checkbox" checked={groupIds.includes(gid)} onChange={() => basculerGroupe(gid)} />
                  {payload.groupLabels[gid] ?? gid}
                </label>
              ))}
            </div>
          </div>

          <div className="newroom-field newroom-field--large">
            Enseignant(s) (optionnel)
            <TeacherPicker selected={teacherCodes} labels={payload.teacherLabels} onChange={setTeacherCodes} />
          </div>

          <label className="newroom-field newroom-field--large">
            Note (optionnel)
            <textarea
              value={note}
              maxLength={300}
              placeholder="ex. Échange IA — retour étudiants S1"
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

          <label className="newroom-field">
            Heure de début (optionnel)
            <input
              type="time"
              value={heureDebut}
              onChange={(e) => setHeureDebut(e.target.value)}
            />
          </label>

          <label className="newroom-field">
            Heure de fin (optionnel)
            <input type="time" value={heureFin} onChange={(e) => setHeureFin(e.target.value)} />
          </label>

          <p className="muted small newroom-field--large">
            Laisser vide pour utiliser le créneau. Une heure entre 12h30 et 14h s'affiche dans la pause méridienne.
          </p>
        </div>

        {erreur && <p className="alerte">{erreur}</p>}

        <div className="confirmmodal-actions">
          <button type="button" className="btn btn--ghost" onClick={onCancel}>
            Annuler
          </button>
          <button type="submit" className="btn btn--accent" disabled={enCours}>
            {enCours ? "…" : "Créer et placer"}
          </button>
        </div>
      </form>
    </div>
  );
}
