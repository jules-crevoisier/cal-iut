import { useEffect, useMemo, useState } from "react";

import type { CreerEvenementBody, ModifierSeanceBody } from "../api/client";
import type { Placement } from "../types";
import type { AppPayload, AppRow } from "../types/app";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";
import { creerEvenementAvecConfirmation, modifierSeancePersonnaliseeAvecConfirmation } from "../utils/placement";
import { lireDernierWeekDay } from "../utils/creerSeancePrefs";
import { TeacherPicker } from "./TeacherPicker";
import "./CreerSeanceModal.css";

const RE_HEURE = /^([01]\d|2[0-3]):[0-5]\d$/;

/** Pause méridienne du département : 12h30-14h, même borne que le serveur
 * (`_dans_la_pause_meridienne` : début >= 12h30 et < 14h). */
const PAUSE_DEBUT = "12:30";
const PAUSE_FIN = "14:00";
const CRENEAU_PAUSE = "midi";

function dansLaPause(heure: string): boolean {
  return RE_HEURE.test(heure) && heure >= PAUSE_DEBUT && heure < PAUSE_FIN;
}

/** Évènement déjà créé, à rouvrir pré-rempli (tâche 16). `row` porte ce que
 * le placement seul ne dit pas : semestre, note, horaire libre. */
export interface EvenementExistant {
  placement: Placement;
  row: AppRow;
}

interface CreerEvenementModalProps {
  payload: AppPayload;
  /** Présent = modification de cet évènement ; absent = création. */
  evenementExistant?: EvenementExistant | null;
  /** Pré-remplit semaine/jour depuis ce qui est affiché en Vue Promo au
   * moment du clic (même règle que `CreerSeanceModal`). */
  suggestion?: { week?: number; day?: number } | null;
  onCree: (placement: Placement) => void;
  onCancel: () => void;
  /** Modification seulement : bouton « Supprimer » (absent = pas de bouton). */
  onSupprimer?: () => void;
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
 * méridienne, 12h30-14h), affiché tel quel dans la ligne "pause" des grilles
 * plutôt que menti sur un créneau qui ne correspond pas.
 *
 * Tâche 16 (Kyllian Bresson, 07/10/2026) : mise en page horizontale sur le
 * modèle de « Nouvelle séance » (trois blocs côte à côte au lieu d'une
 * colonne qui défile), « Pause méridienne » proposée directement dans le
 * choix du créneau, et la même fenêtre rouvre un évènement existant pour le
 * modifier (`PATCH /placements/personnalisees`). */
export function CreerEvenementModal({
  payload,
  evenementExistant = null,
  suggestion = null,
  onCree,
  onCancel,
  onSupprimer,
}: CreerEvenementModalProps) {
  const existant = evenementExistant?.placement ?? null;
  const infos = evenementExistant?.row.evt ?? null;

  const [libelle, setLibelle] = useState(existant ? evenementExistant?.row.n || existant.course_name : "");
  const [semestre, setSemestre] = useState(infos?.sem ?? "S1");
  const [groupIds, setGroupIds] = useState<string[]>(existant?.group_ids ?? []);
  const [teacherCodes, setTeacherCodes] = useState<string[]>(existant?.teacher_codes ?? []);
  const [dureeSlots, setDureeSlots] = useState(existant?.duration_slots ?? 1);
  const [note, setNote] = useState(infos?.note ?? "");
  const [week, setWeek] = useState(
    () => existant?.week ?? suggestion?.week ?? lireDernierWeekDay()?.week ?? payload.weekRows[0]?.weekIndex ?? 0,
  );
  const [day, setDay] = useState(() => existant?.day ?? suggestion?.day ?? lireDernierWeekDay()?.day ?? 0);
  const [slot, setSlot] = useState(existant?.slot ?? 0);
  const [roomId, setRoomId] = useState(existant?.room_id ?? "");
  const [heureDebut, setHeureDebut] = useState(infos?.hd ?? "");
  const [heureFin, setHeureFin] = useState(infos?.hf ?? "");
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  const groupesTries = useMemo(
    () => Object.keys(payload.groupLabels).sort((a, b) => (payload.groupLabels[a] ?? a).localeCompare(payload.groupLabels[b] ?? b, "fr")),
    [payload.groupLabels],
  );
  // Rangés par parcours : « TD AB » existe dans plusieurs promos, une liste
  // à plat en alignait trois identiques sans dire lesquels.
  const groupesParParcours = useMemo(() => {
    const rang = (gid: string) => ({ promo: 0, td: 1, tp: 2 })[payload.groupKind[gid] ?? ""] ?? 3;
    const parParcours = new Map<string, string[]>();
    for (const gid of groupesTries) {
      const pc = payload.groupParcours[gid] ?? "Autres";
      parParcours.set(pc, [...(parParcours.get(pc) ?? []), gid]);
    }
    return [...parParcours.entries()]
      .sort(([a], [b]) => a.localeCompare(b, "fr"))
      .map(([pc, gids]) => [pc, [...gids].sort((a, b) => rang(a) - rang(b))] as const);
  }, [groupesTries, payload.groupParcours, payload.groupKind]);
  const semainesDisponibles = useMemo(
    () => payload.weekRows.filter((w): w is typeof w & { weekIndex: number } => w.weekIndex !== null),
    [payload.weekRows],
  );

  const basculerGroupe = (gid: string) => {
    setGroupIds((prev) => (prev.includes(gid) ? prev.filter((g) => g !== gid) : [...prev, gid]));
  };

  // « Pause méridienne » dans la liste des créneaux (tâche 16 : « J'ai créé
  // un évènement de type CM de 13h30 à 14h00, mais celui-ci ne s'est pas
  // correctement placé ») : la choisir pose 12h30-14h, ajustable ensuite ;
  // une heure de début saisie dans la pause la sélectionne d'elle-même.
  const creneauAffiche = dansLaPause(heureDebut) ? CRENEAU_PAUSE : String(slot);
  const changerCreneau = (valeur: string) => {
    if (valeur === CRENEAU_PAUSE) {
      if (!dansLaPause(heureDebut)) {
        setHeureDebut(PAUSE_DEBUT);
        setHeureFin(PAUSE_FIN);
      }
      return;
    }
    setSlot(Number(valeur));
    if (dansLaPause(heureDebut)) {
      setHeureDebut("");
      setHeureFin("");
    }
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
    const horaire = heureDebut && heureFin ? { heure_debut: heureDebut, heure_fin: heureFin } : null;

    if (existant) {
      const corps: ModifierSeanceBody = {
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
        ...(horaire ?? (infos?.hd ? { sans_horaire: true } : {})),
      };
      const resultat = await modifierSeancePersonnaliseeAvecConfirmation(existant.session_id, corps);
      setEnCours(false);
      if (resultat.ok) onCree(resultat.placement);
      else setErreur(resultat.message);
      return;
    }

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
      ...(horaire ?? {}),
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
        className="panel confirmmodal seancemodal evenementmodal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="evenementmodal-titre"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          void valider();
        }}
      >
        <h3 id="evenementmodal-titre">{existant ? "Modifier l'évènement" : "Nouvel évènement"}</h3>
        <p className="muted small">
          Réunion, conférence, présentation... affichée en clair sur l'EDT, sans matière ni progression.
        </p>

        <div className="seancemodal-corps evenementmodal-corps">
          <fieldset className="seancemodal-bloc">
            <legend>Évènement</legend>
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
                Enseignant(s) (optionnel)
                <TeacherPicker selected={teacherCodes} labels={payload.teacherLabels} onChange={setTeacherCodes} />
              </div>

              <label className="newroom-field newroom-field--large">
                Note (optionnel)
                <textarea
                  value={note}
                  maxLength={300}
                  rows={2}
                  placeholder="ex. Échange IA — retour étudiants S1"
                  onChange={(e) => setNote(e.target.value)}
                />
              </label>
            </div>
          </fieldset>

          <fieldset className="seancemodal-bloc">
            <legend>Groupe(s)</legend>
            <div className="newroom-field-groupes evenement-groupes">
              {groupesParParcours.map(([pc, gids]) => (
                <div key={pc} className="evenement-groupes-parcours" role="group" aria-label={pc}>
                  <span className="evenement-groupes-titre" aria-hidden="true">
                    {pc}
                  </span>
                  {gids.map((gid) => (
                    <label key={gid}>
                      <input type="checkbox" checked={groupIds.includes(gid)} onChange={() => basculerGroupe(gid)} />
                      {payload.groupLabels[gid] ?? gid}
                    </label>
                  ))}
                </div>
              ))}
            </div>
          </fieldset>

          <fieldset className="seancemodal-bloc">
            <legend>Quand et où</legend>
            <div className="seancemodal-grille">
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
                <select value={creneauAffiche} onChange={(e) => changerCreneau(e.target.value)}>
                  {SLOT_TIMES.slice(0, 3).map((s, i) => (
                    <option key={s.label} value={i}>
                      {s.label}
                    </option>
                  ))}
                  <option value={CRENEAU_PAUSE}>Pause méridienne</option>
                  {SLOT_TIMES.slice(3).map((s, i) => (
                    <option key={s.label} value={i + 3}>
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
                <input type="time" value={heureDebut} onChange={(e) => setHeureDebut(e.target.value)} />
              </label>

              <label className="newroom-field">
                Heure de fin (optionnel)
                <input type="time" value={heureFin} onChange={(e) => setHeureFin(e.target.value)} />
              </label>

              <p className="muted small newroom-field--large">
                Laisser vide pour utiliser le créneau. Une heure entre 12h30 et 14h place l'évènement dans la pause
                méridienne.
              </p>
            </div>
          </fieldset>
        </div>

        {erreur && <p className="alerte">{erreur}</p>}

        <div className="confirmmodal-actions">
          {existant && onSupprimer && (
            <button
              type="button"
              className="btn btn--danger"
              disabled={enCours}
              onClick={onSupprimer}
            >
              Supprimer
            </button>
          )}
          <button type="button" className="btn btn--ghost" onClick={onCancel}>
            Annuler
          </button>
          <button type="submit" className="btn btn--accent" disabled={enCours}>
            {enCours ? "…" : existant ? "Enregistrer" : "Créer et placer"}
          </button>
        </div>
      </form>
    </div>
  );
}
