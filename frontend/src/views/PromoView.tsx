/**
 * Toutes les promos (BUT1→BUT3) sur une seule grille, un jour à la fois —
 * c'est ici qu'on déplace les séances. Portage de `renderPromoTab` /
 * `promoColumnGroups` (`export/templates/timetable.html`), avec trois règles
 * issues du retour utilisateur du 11/08/2026 :
 *
 * 1. Colonnes = groupes TP quand le parcours en a (BUT1 : TP A→H), TD
 *    seulement pour les parcours SANS TP (FC).
 * 2. Un cours « promo » (CM) n'a pas de colonne à part : il apparaît dans
 *    chaque colonne de son parcours, comme un étudiant le vit
 *    (`payload.groupCohort[gid]` : TP + son TD + le CM promo).
 * 3. Ordre des colonnes : année, puis FI avant FC (cf. tri plus bas).
 *
 * Refonte du 29/09/2026 : une seule barre d'outils (semaine, jour, filtres,
 * actions), cartes de séance compactes (`PromoCarte`), raccourcis clavier,
 * filtres mémorisés, retour visible après chaque action avec « Annuler »,
 * zones de dépôt lisibles pendant le glisser-déposer.
 */

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { DragEvent as ReactDragEvent, KeyboardEvent as ReactKeyboardEvent } from "react";

import { indexSemaineCourante, jourOuvreAujourdhui } from "../utils/semaineCourante";
import {
  changerSalle,
  deposerPlacement,
  echangerPlacements,
  supprimerSeancePersonnalisee,
  type SeanceAPlacer,
} from "../api/client";
import type { Placement } from "../types";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload, AppRow } from "../types/app";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";
import { confirmAsync } from "../utils/confirmDialog";
import { detailConflit, placerAvecConfirmation } from "../utils/placement";
import { ParcoursWeekModal } from "../components/ParcoursWeekModal";
import { cleSeances, fusionnerColonnes } from "../utils/fusionColonnes";
import { performMove, performSwap } from "../utils/moveSession";
import {
  teacherBusyByDaySlot,
  teacherBusyLabel,
  teacherBusyOnCell,
  type TeacherBusyHit,
} from "../utils/teacherBusy";
import { usePreferences } from "../utils/preferences";
import { dateForWeekDay, formatShortDate } from "../utils/weekDates";
import { lettresGroupe } from "../utils/years";
import { nomComplet } from "../utils/nomEnseignant";
import { NewRoomModal } from "../components/NewRoomModal";
import { CreerSeanceModal } from "../components/CreerSeanceModal";
import { CreerEvenementModal } from "../components/CreerEvenementModal";
import { WeekBar } from "../components/WeekBar";
import { WeekStepper } from "../components/WeekStepper";
import { APlacerView } from "./APlacerView";
import { PromoCarte } from "./PromoCarte";
import {
  addPark,
  clearPark,
  decideWeekDrop,
  hasParked,
  isHiddenOnGrid,
  removePark,
  selectPark,
  selectedParked,
  type ParkUiState,
} from "../features/park-week-move/parkWeekMove";
import { anneeDepuisParcours, filtrerParcours, listerAnnees, parcoursPourSelect } from "../utils/promoFilters";
import "./PromoView.css";

interface PromoViewProps {
  /** Position demandée par un lien ou par « À traiter » (semaine + jour). */
  route?: Route;
  payload: AppPayload;
  /** Séance choisie dans « À placer », à poser directement sur cette grille. */
  placementActif?: SeanceAPlacer | null;
  onAnnulerPlacement?: () => void;
  onPlaced?: () => void;
  /** Glisser-déposer d'une séance DÉJÀ placée (retour utilisateur
   * 28/08/2026 : possible ici, plus en Vue Semaine). Les trois props vont
   * ensemble ; absentes, la grille reste en lecture seule pour ce qui est
   * déjà au planning. */
  placements?: Placement[];
  onPlacementUpdated?: (p: Placement) => void;
  onError?: (msg: string) => void;
  /** Une séance personnalisée a été créée, modifiée ou supprimée — recharge
   * `payload` et la liste des placements. */
  onSeanceChangee?: () => void;
  setRoute?: (patch: Partial<Route>) => void;
  onAPlacerRefresh?: () => void;
  /** Lien public « Vue Promo » (retour utilisateur 31/08/2026) — coupe
   * TOUTE écriture, même si l'appelant passe les callbacks d'édition. */
  readOnly?: boolean;
}

const JOURS_COURTS = ["lun.", "mar.", "mer.", "jeu.", "ven."];

// Filtres mémorisés sur l'appareil (refonte du 29/09/2026) : qui ne
// travaille que sur les BUT2 n'a plus à les re-choisir à chaque visite. Le
// jour et la semaine, eux, NE sont PAS mémorisés : on arrive toujours sur
// aujourd'hui (retour utilisateur 08/09/2026).
const CLE_FILTRES = "cal-iut:promo:filtres:v1";

interface FiltresMemorises {
  annee: string;
  parcours: string;
  enseignant: string;
}

function lireFiltres(): FiltresMemorises {
  const defaut = { annee: "Tout", parcours: "Tout", enseignant: "" };
  try {
    const brut = window.localStorage.getItem(CLE_FILTRES);
    if (!brut) return defaut;
    const lu = JSON.parse(brut) as Partial<FiltresMemorises>;
    return {
      annee: typeof lu.annee === "string" ? lu.annee : "Tout",
      parcours: typeof lu.parcours === "string" ? lu.parcours : "Tout",
      enseignant: typeof lu.enseignant === "string" ? lu.enseignant : "",
    };
  } catch {
    return defaut;
  }
}

function ecrireFiltres(f: FiltresMemorises): void {
  try {
    window.localStorage.setItem(CLE_FILTRES, JSON.stringify(f));
  } catch {
    // Stockage indisponible (navigation privée) : les filtres restent
    // simplement ceux de la session.
  }
}

/** Retour visible après une action, avec son « Annuler » quand il existe. */
interface Retour {
  texte: string;
  annuler?: () => Promise<void>;
}

/** Cible du clavier : on n'intercepte rien pendant une saisie. */
function saisieEnCours(cible: EventTarget | null): boolean {
  if (!(cible instanceof HTMLElement)) return false;
  return Boolean(cible.closest("input, select, textarea, [contenteditable='true'], [role='dialog'], [role='alertdialog']"));
}

export function PromoView({
  payload,
  route,
  placementActif: placementActifProp = null,
  onAnnulerPlacement,
  onPlaced,
  placements,
  onPlacementUpdated,
  onError,
  onSeanceChangee,
  setRoute,
  onAPlacerRefresh,
  readOnly = false,
}: PromoViewProps) {
  const filtresInitiaux = useMemo(lireFiltres, []);
  const [choixAPlacer, setChoixAPlacer] = useState<SeanceAPlacer | null>(null);
  const [listeMasquee, setListeMasquee] = useState(() => route?.panel !== "aplacer");
  const [park, setPark] = useState<ParkUiState>(() => clearPark());
  const [filtreAnnee, setFiltreAnnee] = useState<string>(filtresInitiaux.annee);
  const [filtreParcoursSel, setFiltreParcoursSel] = useState<string>(filtresInitiaux.parcours);
  const placementActif = readOnly ? null : (placementActifProp ?? choixAPlacer);
  const [displayWeek, setDisplayWeek] = useState(0);
  // Le jour EN COURS plutôt que lundi (retour utilisateur 08/09/2026 : « on
  // veut arriver à la bonne semaine et au bon jour »).
  const [day, setDay] = useState(() => jourOuvreAujourdhui());
  const [teacherFilter, setTeacherFilter] = useState(filtresInitiaux.enseignant);
  const [enCoursPlacement, setEnCoursPlacement] = useState<string | null>(null);
  const [erreurPlacement, setErreurPlacement] = useState<string | null>(null);
  const [retour, setRetour] = useState<Retour | null>(null);
  const [annulationEnCours, setAnnulationEnCours] = useState(false);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  // Séance SURVOLÉE par le glisser en cours : déposer dessus propose un
  // échange plutôt qu'un déplacement (retour utilisateur 29/08/2026).
  const [cibleEchange, setCibleEchange] = useState<string | null>(null);
  // Parcours dont la semaine complète est ouverte en modale — seul endroit
  // où l'on déplace une séance d'un JOUR à un autre.
  const [parcoursOuvert, setParcoursOuvert] = useState<string | null>(null);
  const couleursParMatiere = usePreferences().couleursParMatiere;
  const [dropTarget, setDropTarget] = useState<{ day: number; slot: number } | null>(null);
  const dragEnabled = !readOnly && Boolean(placements && onPlacementUpdated && onError);

  useEffect(() => {
    if (!readOnly && route?.panel === "aplacer") setListeMasquee(false);
  }, [route?.panel, readOnly]);

  useEffect(() => {
    ecrireFiltres({ annee: filtreAnnee, parcours: filtreParcoursSel, enseignant: teacherFilter });
  }, [filtreAnnee, filtreParcoursSel, teacherFilter]);

  const signaler = (texte: string, annuler?: () => Promise<void>) => setRetour({ texte, annuler });

  // Édition de la SALLE seule (retour utilisateur 28/08/2026) — réservée au
  // contexte d'édition, jamais au lien public.
  const [salleEnEdition, setSalleEnEdition] = useState<string | null>(null);
  const [salleEnCours, setSalleEnCours] = useState(false);
  const roomEditEnabled = !readOnly && Boolean(onPlacementUpdated && onError);
  // Séance pour laquelle on crée une salle : la salle créée lui est
  // appliquée directement.
  const [creationSallePour, setCreationSallePour] = useState<string | null>(null);
  const sallesTriees = useMemo(
    () => [...payload.rooms].sort((a, b) => a.label.localeCompare(b.label, "fr")),
    [payload.rooms],
  );

  // Créer / modifier une séance (retour utilisateur 31/08/2026). `"creer"` =
  // formulaire vide ; un `Placement` = édition de cette séance.
  const [modaleSeance, setModaleSeance] = useState<"creer" | Placement | null>(null);
  const seanceModaleEnabled = roomEditEnabled;
  // Évènement hors maquette (réunion, conférence...) — retour utilisateur
  // 07/09/2026, avec horaire réel optionnel depuis le 23/09/2026.
  const [modaleEvenement, setModaleEvenement] = useState(false);

  const appliquerSalle = async (sessionId: string, roomId: string, ancienne?: string | null) => {
    if (!roomId || !onPlacementUpdated || !onError) return;
    setSalleEnCours(true);
    try {
      const maj = await changerSalle(sessionId, { room_id: roomId }).catch(async (e) => {
        const detail = detailConflit(e);
        if (!detail) throw e;
        // Salle occupée et/ou capacité insuffisante, montrés en forçage
        // explicite. Le titre suit ce qui est RÉELLEMENT en cause ; le verrou
        // de semaine (31/08/2026) se dit lui-même.
        const verrou = detail.hard_conflicts.some((m) => m.includes("non modifiable"));
        const titre = verrou
          ? "Semaine déjà en cours"
          : detail.hard_conflicts.length
            ? "Salle déjà occupée"
            : "Attention à la capacité";
        const forcer = await confirmAsync([...detail.hard_conflicts, ...detail.soft_warnings].join("\n"), {
          title: titre,
          confirmLabel: "Mettre quand même cette salle",
        });
        if (!forcer) return null;
        return changerSalle(sessionId, { room_id: roomId, force: true });
      });
      if (maj) {
        onPlacementUpdated(maj);
        setSalleEnEdition(null);
        signaler(
          `${maj.course_code} : salle ${maj.room_label ?? roomId}.`,
          ancienne
            ? async () => {
                const remis = await changerSalle(sessionId, { room_id: ancienne, force: true });
                onPlacementUpdated(remis);
                signaler(`${remis.course_code} : salle ${remis.room_label ?? ancienne} rétablie.`);
              }
            : undefined,
        );
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : "Changement de salle impossible");
    } finally {
      setSalleEnCours(false);
    }
  };

  // Supprimer une séance personnalisée — jamais une séance de la maquette
  // (bouton présent seulement sur `r.custom`).
  const supprimerSeance = async (sessionId: string, libelle: string) => {
    const confirme = await confirmAsync(`Supprimer définitivement « ${libelle} » ?`, {
      title: "Supprimer la séance",
      confirmLabel: "Supprimer",
    });
    if (!confirme) return;
    try {
      await supprimerSeancePersonnalisee(sessionId);
      signaler(`${libelle} supprimée.`);
      onSeanceChangee?.();
    } catch (e) {
      onError?.(e instanceof Error ? e.message : "Suppression impossible");
    }
  };

  // Ouvrir sur la semaine EN COURS (retour utilisateur 08/09/2026). Ici et
  // pas seulement dans `App.tsx` : cette vue tient son propre `displayWeek`.
  // Une seule fois, et jamais quand la route fixe déjà une semaine.
  const semaineRecentree = useRef(false);
  useEffect(() => {
    if (semaineRecentree.current) return;
    if (route?.sem !== null && route?.sem !== undefined) {
      semaineRecentree.current = true;
      return;
    }
    if (!payload.weekRows?.length) return;
    semaineRecentree.current = true;
    setDisplayWeek(indexSemaineCourante(payload.weekRows));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload.weekRows]);

  // Suit la route quand elle change (clic depuis « À traiter »), sans
  // reprendre la main sur la navigation manuelle ensuite.
  useEffect(() => {
    if (route?.sem === null || route?.sem === undefined) return;
    const idx = payload.weekRows.findIndex((w) => w.weekIndex === route.sem);
    if (idx >= 0) setDisplayWeek(idx);
    if (route.jour !== null && route.jour !== undefined) setDay(route.jour);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route?.sem, route?.jour]);

  // Résultat « Promo » de la recherche (retour utilisateur 05/09/2026) :
  // filtre la grille sur ce parcours à l'arrivée.
  useEffect(() => {
    if (!route?.parcours) return;
    setFiltreAnnee(anneeDepuisParcours(route.parcours) ?? "Tout");
    setFiltreParcoursSel(route.parcours);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route?.parcours]);

  const solverWeek = payload.weekRows[displayWeek]?.weekIndex ?? null;
  const indexAujourdhui = indexSemaineCourante(payload.weekRows);
  const jourAujourdhui = jourOuvreAujourdhui();
  // Jour réellement en cours (samedi/dimanche : aucun).
  const jourReel = new Date().getDay();
  const jourReelOuvre = jourReel >= 1 && jourReel <= 5 ? jourReel - 1 : null;

  const teacherBusyMap = useMemo(() => {
    if (solverWeek === null) return new Map<string, TeacherBusyHit>();
    let teachers: string[] = [];
    let excludeId: string | undefined;
    if (draggingId) {
      const row = payload.rows.find((r) => r.id === draggingId);
      teachers = row?.te ?? [];
      excludeId = draggingId;
    } else if (placementActif) {
      teachers = placementActif.teacher_codes;
      excludeId = placementActif.session_id;
    } else {
      const sel = selectedParked(park);
      if (!sel) return new Map<string, TeacherBusyHit>();
      teachers = sel.origin.teacher_codes;
      excludeId = sel.sessionId;
    }
    return teacherBusyByDaySlot(payload.rows, teachers, solverWeek, excludeId);
  }, [draggingId, placementActif, park, payload.rows, solverWeek]);

  // À l'activation d'un placement (arrivée depuis « À placer »), saute sur
  // sa première semaine idéale et remet les filtres sur « Tout » : sinon la
  // colonne de la séance pouvait être filtrée et aucune case n'était
  // cliquable, sans aucun message.
  useEffect(() => {
    if (!placementActif) return;
    const semaineIdeale = placementActif.semaines_possibles[0];
    if (semaineIdeale === undefined) return;
    const idx = payload.weekRows.findIndex((w) => w.weekIndex === semaineIdeale);
    if (idx >= 0) setDisplayWeek(idx);
    setErreurPlacement(null);
    setFiltreAnnee("Tout");
    setFiltreParcoursSel("Tout");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placementActif?.session_id]);

  const teacherCodes = useMemo(
    () =>
      Object.keys(payload.teacherLabels).sort((a, b) =>
        (payload.teacherLabels[a] ?? a).localeCompare(payload.teacherLabels[b] ?? b, "fr"),
      ),
    [payload.teacherLabels],
  );

  const { cols, colGroups, colCohorts, colParcours, anneesDispo, parcoursDispo } = useMemo(() => {
    const allGroupIds = Object.keys(payload.groupLabels);
    const allParcoursList = [...new Set(Object.values(payload.groupParcours))];
    const anneesDispo = listerAnnees(allParcoursList);
    const parcoursDispo = parcoursPourSelect(allParcoursList, filtreAnnee);
    const parcoursVisibles = new Set(filtrerParcours(allParcoursList, filtreAnnee, filtreParcoursSel));

    const groups = allParcoursList
      .filter((pc) => parcoursVisibles.has(pc))
      .map((pc) => {
        const tpIds = allGroupIds.filter((gid) => payload.groupParcours[gid] === pc && payload.groupKind[gid] === "tp");
        const leaf = tpIds.length
          ? tpIds
          : allGroupIds.filter((gid) => payload.groupParcours[gid] === pc && payload.groupKind[gid] !== "promo");
        // Parcours sans TP ni TD : garder une colonne pour pouvoir y poser
        // une séance manquante.
        const cols = leaf.length > 0 ? leaf : allGroupIds.filter((gid) => payload.groupParcours[gid] === pc);
        return {
          parcours: pc,
          cols: cols.sort((a, b) =>
            lettresGroupe(payload.groupLabels[a] ?? a).localeCompare(lettresGroupe(payload.groupLabels[b] ?? b), "fr"),
          ),
        };
      })
      .filter((g) => g.cols.length);

    // Année d'abord, puis LETTRES du premier groupe (retour utilisateur
    // 30/08/2026 : « A, B, EF, GH » et non « A, B, GH, EF ») — garde au
    // passage les FI avant les FC.
    groups.sort((a, b) => {
      const annee = (pc: string) => /^BUT(\d)/.exec(pc)?.[1] ?? "9";
      if (annee(a.parcours) !== annee(b.parcours)) {
        return annee(a.parcours).localeCompare(annee(b.parcours));
      }
      const premiere = (g: typeof a) => lettresGroupe(payload.groupLabels[g.cols[0]] ?? g.cols[0]);
      return premiere(a).localeCompare(premiere(b), "fr") || a.parcours.localeCompare(b.parcours, "fr");
    });

    const flatCols = groups.flatMap((g) => g.cols);
    return {
      cols: flatCols,
      colGroups: groups,
      colCohorts: flatCols.map((c) => new Set(payload.groupCohort[c] ?? [c])),
      colParcours: flatCols.map((c) => payload.groupParcours[c] ?? ""),
      anneesDispo,
      parcoursDispo,
    };
  }, [
    payload.groupLabels,
    payload.groupParcours,
    payload.groupKind,
    payload.groupCohort,
    filtreAnnee,
    filtreParcoursSel,
  ]);

  const colGroupIdx: number[] = [];
  colGroups.forEach((g, gi) => g.cols.forEach(() => colGroupIdx.push(gi)));
  const colClass = (i: number) => {
    const pc = `pc${colGroupIdx[i] % 6}`;
    const isFirst = i === 0 || colGroupIdx[i] !== colGroupIdx[i - 1];
    return isFirst ? `${pc} grp-first` : pc;
  };

  const countByWeek = useMemo(() => {
    const m = new Map<number, number>();
    for (const r of payload.rows) {
      if (cols.some((_, i) => r.g.some((id) => colCohorts[i].has(id)))) {
        m.set(r.w, (m.get(r.w) ?? 0) + 1);
      }
    }
    return m;
  }, [payload.rows, cols, colCohorts]);

  // Repères de la barre des jours : férié / SAE / évènement d'au moins un
  // parcours ce jour-là — dits en toutes lettres, pas par une pastille.
  const dayBadges = useMemo(() => {
    if (solverWeek === null) return DAY_LABELS.map(() => undefined as "sae" | "holiday" | "event" | undefined);
    return DAY_LABELS.map((_, d) => {
      if (payload.holidayRows.some((h) => h.w === solverWeek && h.d === d)) return "holiday" as const;
      if (payload.saeRows.some((s) => s.w === solverWeek && s.d === d)) return "sae" as const;
      if (payload.eventRows.some((e) => e.w === solverWeek && e.d === d)) return "event" as const;
      return undefined;
    });
  }, [payload.holidayRows, payload.saeRows, payload.eventRows, solverWeek]);

  const byColSlot = new Map<string, AppRow[]>();
  // Évènements à horaire libre dans la pause méridienne (`r.midi`, retour
  // Jules 23/09/2026) : rendus dans la ligne « pause », jamais dans la case
  // du créneau 3 où ils sont STOCKÉS (cf. `api/main.py::creer_evenement`).
  const byColPause = new Map<string, AppRow[]>();
  if (solverWeek !== null) {
    for (const r of payload.rows) {
      if (isHiddenOnGrid(park, r.id)) continue;
      if (r.w !== solverWeek || r.d !== day) continue;
      if (r.midi) {
        cols.forEach((_, i) => {
          if (!r.g.some((id) => colCohorts[i].has(id))) return;
          const key = `${i}`;
          if (!byColPause.has(key)) byColPause.set(key, []);
          byColPause.get(key)!.push(r);
        });
        continue;
      }
      const dur = Math.max(1, r.dur || 1);
      cols.forEach((_, i) => {
        if (!r.g.some((id) => colCohorts[i].has(id))) return;
        for (let k = 0; k < dur; k++) {
          const key = `${i}-${r.s + k}`;
          if (!byColSlot.has(key)) byColSlot.set(key, []);
          byColSlot.get(key)!.push(r);
        }
      });
    }
  }

  // Un TD = une case pour ses deux TP, un CM = une case pour la promo
  // (demande du 22/09/2026, cf. `utils/fusionColonnes.ts`).
  const largeursParCreneau = SLOT_TIMES.map((_, s) =>
    fusionnerColonnes(
      cols.length,
      (i) => cleSeances((byColSlot.get(`${i}-${s}`) ?? []).map((r) => r.id)),
      (i) => colParcours[i],
    ),
  );
  const largeursPause = fusionnerColonnes(
    cols.length,
    (i) => cleSeances((byColPause.get(`${i}`) ?? []).map((r) => r.id)),
    (i) => colParcours[i],
  );

  // Pendant un glisser : colonnes de la séance tirée. C'est là qu'elle
  // atterrira (un dépôt change l'HEURE, jamais le groupe) — on y montre la
  // cible et, d'avance, ce qui coincera (groupe déjà pris, enseignant ailleurs).
  const ligneTiree = draggingId ? payload.rows.find((r) => r.id === draggingId) : undefined;
  const colonnesTirees = new Set<number>();
  if (ligneTiree) {
    cols.forEach((_, i) => {
      if (ligneTiree.g.some((id) => colCohorts[i].has(id))) colonnesTirees.add(i);
    });
  }

  const holiday = solverWeek === null ? undefined : payload.holidayRows.find((h) => h.w === solverWeek && h.d === day);
  const dayEvents =
    solverWeek === null ? undefined : payload.eventRows.find((e) => e.w === solverWeek && e.d === day)?.labels;

  /** « mar. 29 sept. 9h30 » */
  const quand = (week: number, d: number, slot: number) => {
    const date = formatShortDate(dateForWeekDay(payload, week, d));
    const debut = SLOT_TIMES[slot]?.label.split("–")[0] ?? "";
    return [JOURS_COURTS[d], date, debut].filter(Boolean).join(" ");
  };

  const idxAffichage = (week: number) => payload.weekRows.findIndex((w) => w.weekIndex === week);

  const allerA = (week: number, d: number) => {
    const idx = idxAffichage(week);
    if (idx >= 0) setDisplayWeek(idx);
    setDay(d);
  };

  const placerIci = async (slot: number) => {
    if (!placementActif || solverWeek === null) return;
    const seance = placementActif;
    const cle = `${solverWeek}-${day}-${slot}`;
    setEnCoursPlacement(cle);
    setErreurPlacement(null);
    const resultat = await placerAvecConfirmation(seance.session_id, { week: solverWeek, day, slot });
    setEnCoursPlacement(null);
    if (resultat.ok) {
      signaler(`${seance.course_code} placée ${quand(solverWeek, day, slot)}.`, async () => {
        await deposerPlacement(seance.session_id);
        signaler(`${seance.course_code} remise dans « À placer ».`);
        onSeanceChangee?.();
        onAPlacerRefresh?.();
      });
      setChoixAPlacer(null);
      onPlaced?.();
      onAPlacerRefresh?.();
    } else {
      setErreurPlacement(resultat.message);
    }
  };

  const restaurerTousParks = () => {
    const originWeek = park.items[0]?.origin.week;
    setPark(clearPark());
    if (originWeek === undefined) return;
    const idx = idxAffichage(originWeek);
    if (idx >= 0) setDisplayWeek(idx);
  };

  const annulerPark = (sessionId: string) => {
    const originWeek = park.items.find((p) => p.sessionId === sessionId)?.origin.week;
    setPark((actuel) => removePark(actuel, sessionId));
    if (originWeek === undefined) return;
    const idx = idxAffichage(originWeek);
    if (idx >= 0) setDisplayWeek(idx);
  };

  /** Déplacement réussi : message + « Annuler » qui remet la séance où elle
   *  était (mêmes contrôles qu'un déplacement normal). */
  const signalerDeplacement = (origine: Placement, cible: { week: number; day: number; slot: number }) => {
    if (!onPlacementUpdated || !onError) return;
    signaler(
      `${origine.course_code} déplacée : ${quand(origine.week, origine.day, origine.slot)} → ${quand(cible.week, cible.day, cible.slot)}.`,
      async () => {
        const ok = await performMove(
          origine.session_id,
          { week: origine.week, day: origine.day, slot: origine.slot },
          origine,
          onPlacementUpdated,
          onError,
        );
        if (ok) signaler(`${origine.course_code} remise ${quand(origine.week, origine.day, origine.slot)}.`);
      },
    );
  };

  const poserParked = async (slot: number) => {
    const sel = selectedParked(park);
    if (!sel || !onPlacementUpdated || !onError || solverWeek === null) return;
    const origin = sel.origin;
    const cle = `${solverWeek}-${day}-${slot}`;
    setEnCoursPlacement(cle);
    const cible = { week: solverWeek, day, slot };
    const ok = await performMove(origin.session_id, cible, origin, onPlacementUpdated, onError);
    setEnCoursPlacement(null);
    if (ok) {
      signalerDeplacement(origin, cible);
      setPark((actuel) => removePark(actuel, sel.sessionId));
    }
  };

  const retirerDuPlanning = async (sessionId: string, courseCode: string) => {
    const ok = await confirmAsync(`Retirer ${courseCode} du planning et le remettre dans « À placer » ?`, {
      title: "Retirer du planning",
      confirmLabel: "Retirer",
      cancelLabel: "Annuler",
    });
    if (!ok) return;
    const avant = placements?.find((p) => p.session_id === sessionId);
    try {
      await deposerPlacement(sessionId);
      signaler(
        `${courseCode} retirée du planning, elle attend dans « À placer ».`,
        avant
          ? async () => {
              const resultat = await placerAvecConfirmation(sessionId, {
                week: avant.week,
                day: avant.day,
                slot: avant.slot,
              });
              if (resultat.ok) {
                signaler(`${courseCode} remise ${quand(avant.week, avant.day, avant.slot)}.`);
                onSeanceChangee?.();
                onAPlacerRefresh?.();
              } else {
                onError?.(resultat.message);
              }
            }
          : undefined,
      );
      onSeanceChangee?.();
      onAPlacerRefresh?.();
    } catch (e) {
      onError?.(e instanceof Error ? e.message : "Retrait impossible");
    }
  };

  // Glisser-déposer d'une séance déjà placée (validation -> confirmation si
  // conflit -> forçage ou non, cf. `utils/moveSession.ts::performMove`).
  const handleDrop = async (targetDay: number, slot: number) => {
    setDropTarget(null);
    const sessionId = draggingId;
    setDraggingId(null);
    if (!sessionId || !placements || !onPlacementUpdated || !onError || solverWeek === null) return;
    const placement = placements.find((p) => p.session_id === sessionId);
    if (!placement || placement.locked) return;
    if (placement.day === targetDay && placement.slot === slot && placement.week === solverWeek) return;
    const cible = { week: solverWeek, day: targetDay, slot };
    const ok = await performMove(sessionId, cible, placement, onPlacementUpdated, onError);
    if (ok) signalerDeplacement(placement, cible);
  };

  const handleDropOnWeek = (displayIndex: number) => {
    const wr = payload.weekRows[displayIndex];
    const sessionId = draggingId;
    setDraggingId(null);
    if (!dragEnabled || !sessionId || !placements) return;
    const placement = placements.find((p) => p.session_id === sessionId);
    const decision = decideWeekDrop({ placement, target: wr, currentSolverWeek: solverWeek });
    if (decision === "refuse") return;
    if (decision === "navigate") {
      setDisplayWeek(displayIndex);
      return;
    }
    if (!placement) return;
    setPark((actuel) => addPark(actuel, placement, displayIndex));
    setChoixAPlacer(null);
    setListeMasquee(false);
    setRoute?.({ panel: "aplacer" });
    setDisplayWeek(displayIndex);
  };

  /** Dépôt SUR une séance : les deux échangent leurs places (un seul appel
   *  serveur, cf. `utils/moveSession.ts::performSwap`). */
  const handleSwap = async (cibleId: string) => {
    setCibleEchange(null);
    const sourceId = draggingId;
    setDraggingId(null);
    if (!sourceId || sourceId === cibleId || !placements || !onPlacementUpdated || !onError) return;
    const source = placements.find((p) => p.session_id === sourceId);
    const cible = placements.find((p) => p.session_id === cibleId);
    if (!source || !cible) return;
    if (source.locked || cible.locked) {
      onError("Séance verrouillée : la déverrouiller avant d'échanger.");
      return;
    }
    const ok = await performSwap(sourceId, cibleId, source.course_code, cible.course_code, onPlacementUpdated, onError);
    if (ok) {
      signaler(`${source.course_code} et ${cible.course_code} ont échangé leurs places.`, async () => {
        try {
          const { placements: remis } = await echangerPlacements(sourceId, cibleId, true);
          remis.forEach(onPlacementUpdated);
          signaler(`${source.course_code} et ${cible.course_code} remises à leur place.`);
        } catch (e) {
          onError(e instanceof Error ? e.message : "Annulation impossible");
        }
      });
    }
  };

  const lancerAnnulation = async () => {
    if (!retour?.annuler || annulationEnCours) return;
    setAnnulationEnCours(true);
    try {
      await retour.annuler();
    } catch (e) {
      onError?.(e instanceof Error ? e.message : "Annulation impossible");
    } finally {
      setAnnulationEnCours(false);
    }
  };

  /** Handlers posés sur la SÉANCE (pas la case) : `stopPropagation` pour que
   *  la case en dessous ne traite pas aussi le dépôt comme un déplacement. */
  const echangeHandlers = (cibleId: string) =>
    dragEnabled && draggingId && draggingId !== cibleId
      ? {
          onDragOver: (e: ReactDragEvent) => {
            e.preventDefault();
            e.stopPropagation();
            if (cibleEchange !== cibleId) setCibleEchange(cibleId);
          },
          onDragLeave: () => setCibleEchange((cur) => (cur === cibleId ? null : cur)),
          onDrop: (e: ReactDragEvent) => {
            e.preventDefault();
            e.stopPropagation();
            void handleSwap(cibleId);
          },
        }
      : {};

  const dropHandlers = (targetDay: number, slot: number) =>
    dragEnabled
      ? {
          onDragOver: (e: ReactDragEvent) => {
            if (!draggingId) return;
            e.preventDefault();
            if (dropTarget?.day !== targetDay || dropTarget?.slot !== slot) setDropTarget({ day: targetDay, slot });
          },
          onDragLeave: () => setDropTarget((cur) => (cur?.day === targetDay && cur?.slot === slot ? null : cur)),
          onDrop: (e: ReactDragEvent) => {
            e.preventDefault();
            void handleDrop(targetDay, slot);
          },
        }
      : {};

  // ── Navigation ──
  const allerJour = (delta: number) => {
    let d = day + delta;
    let w = displayWeek;
    if (d < 0) {
      if (w > 0) {
        w -= 1;
        d = DAY_LABELS.length - 1;
      } else d = 0;
    } else if (d >= DAY_LABELS.length) {
      if (w < payload.weekRows.length - 1) {
        w += 1;
        d = 0;
      } else d = DAY_LABELS.length - 1;
    }
    setDisplayWeek(w);
    setDay(d);
  };
  const allerAujourdhui = () => {
    setDisplayWeek(indexAujourdhui);
    setDay(jourAujourdhui);
  };
  const allerSemaine = (i: number) => setDisplayWeek(Math.max(0, Math.min(payload.weekRows.length - 1, i)));
  const modaleOuverte = Boolean(modaleSeance || modaleEvenement || parcoursOuvert || creationSallePour);

  // Raccourcis clavier (refonte du 29/09/2026). Lus via une référence pour
  // ne s'abonner qu'une fois ; ignorés pendant une saisie ou une modale.
  const clavier = useRef<(e: KeyboardEvent) => void>(() => undefined);
  clavier.current = (e: KeyboardEvent) => {
    if (modaleOuverte || saisieEnCours(e.target) || document.querySelector("[role='dialog'], [role='alertdialog']")) return;
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "z") {
      if (retour?.annuler) {
        e.preventDefault();
        void lancerAnnulation();
      }
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      const sens = e.key === "ArrowLeft" ? -1 : 1;
      if (e.shiftKey) allerSemaine(displayWeek + sens);
      else allerJour(sens);
    } else if (e.key === "t" || e.key === "T") {
      allerAujourdhui();
    } else if (e.key === "Escape") {
      if (placementActif) {
        setChoixAPlacer(null);
        onAnnulerPlacement?.();
      } else if (park.selectedSessionId) {
        setPark((actuel) => ({ ...actuel, selectedSessionId: null }));
      }
    }
  };
  useEffect(() => {
    const ecoute = (e: KeyboardEvent) => clavier.current(e);
    document.addEventListener("keydown", ecoute);
    return () => document.removeEventListener("keydown", ecoute);
  }, []);

  const filtresActifs = filtreAnnee !== "Tout" || filtreParcoursSel !== "Tout" || teacherFilter !== "";
  const portee =
    filtreAnnee === "Tout" && filtreParcoursSel === "Tout"
      ? "Toutes promos"
      : filtreParcoursSel !== "Tout"
        ? filtreParcoursSel
        : filtreAnnee;
  const dateJour = dateForWeekDay(payload, solverWeek ?? -1, day);
  const selPark = selectedParked(park);
  const parkParcours = selPark
    ? selPark.origin.group_ids.map((g) => payload.groupParcours[g]).find((pc): pc is string => Boolean(pc))
    : undefined;

  return (
    <section className="view promo">
      <div className="promo-avec-aplacer">
        {!readOnly && !listeMasquee && (
          <APlacerView
            variante="panneau"
            payload={payload}
            onPlacement={() => onAPlacerRefresh?.()}
            onChoisirSurPromo={(seance) => {
              setChoixAPlacer(seance);
              setPark((actuel) => (actuel.selectedSessionId ? { ...actuel, selectedSessionId: null } : actuel));
            }}
            onFermer={() => {
              if (hasParked(park)) restaurerTousParks();
              setListeMasquee(true);
              setChoixAPlacer(null);
              setRoute?.({ panel: "" });
            }}
            park={park}
            onSelectPark={(sessionId) => {
              setChoixAPlacer(null);
              setPark((actuel) => selectPark(actuel, sessionId));
            }}
            onAnnulerPark={annulerPark}
          />
        )}
        <div className="promo-principal">
          <div className="panel promo-barre">
            <div className="promo-barre-ligne">
              <WeekStepper
                weekRows={payload.weekRows}
                selected={displayWeek}
                onSelect={allerSemaine}
                onToday={allerAujourdhui}
                estAujourdhui={displayWeek === indexAujourdhui && day === jourAujourdhui}
                raccourcis
              />
              <div className="promo-weekbar">
                <WeekBar
                  weekRows={payload.weekRows}
                  countByWeekIndex={countByWeek}
                  selected={displayWeek}
                  onSelect={setDisplayWeek}
                  dropEnabled={dragEnabled && Boolean(draggingId)}
                  onDropWeek={dragEnabled ? handleDropOnWeek : undefined}
                />
              </div>
            </div>
            <div className="promo-barre-ligne">
              <div className="promo-jours" role="group" aria-label="Jour affiché">
                {DAY_LABELS.map((label, d) => {
                  const badge = dayBadges[d];
                  const date = formatShortDate(dateForWeekDay(payload, solverWeek ?? -1, d));
                  const estAujourdhui = displayWeek === indexAujourdhui && d === jourReelOuvre;
                  const repere =
                    badge === "holiday" ? "férié" : badge === "sae" ? "SAE" : badge === "event" ? "évènement" : "";
                  return (
                    <button
                      key={label}
                      type="button"
                      className={`promo-jour${d === day ? " active" : ""}${estAujourdhui ? " aujourdhui" : ""}`}
                      aria-pressed={d === day}
                      aria-current={estAujourdhui ? "date" : undefined}
                      title={estAujourdhui ? "Aujourd'hui" : undefined}
                      onClick={() => setDay(d)}
                    >
                      <span className="promo-jour-nom">
                        <span className="long">{label}</span>
                        <span className="court">{label.slice(0, 3)}</span>
                      </span>
                      {date && <span className="promo-jour-date">{date}</span>}
                      {repere && <span className={`promo-jour-repere ${badge}`}>{repere}</span>}
                    </button>
                  );
                })}
              </div>
              <div className="promo-filtres" role="group" aria-label="Filtrer la grille">
                <label className="promo-filtre">
                  <span>Année</span>
                  <select
                    value={filtreAnnee}
                    className={filtreAnnee !== "Tout" ? "is-filtre" : undefined}
                    onChange={(e) => {
                      setFiltreAnnee(e.target.value);
                      setFiltreParcoursSel("Tout");
                    }}
                  >
                    <option value="Tout">Tout</option>
                    {anneesDispo.map((a) => (
                      <option key={a} value={a}>
                        {a}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="promo-filtre">
                  <span>Parcours</span>
                  <select
                    value={filtreParcoursSel}
                    className={filtreParcoursSel !== "Tout" ? "is-filtre" : undefined}
                    onChange={(e) => setFiltreParcoursSel(e.target.value)}
                  >
                    <option value="Tout">Tout</option>
                    {parcoursDispo.map((pc) => (
                      <option key={pc} value={pc}>
                        {pc}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="promo-filtre">
                  <span>Enseignant</span>
                  <select
                    value={teacherFilter}
                    className={teacherFilter ? "is-filtre" : undefined}
                    onChange={(e) => setTeacherFilter(e.target.value)}
                  >
                    <option value="">Tous</option>
                    {teacherCodes.map((c) => (
                      <option key={c} value={c}>
                        {nomComplet(payload.teacherLabels[c] ?? c)}
                      </option>
                    ))}
                  </select>
                </label>
                {filtresActifs && (
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={() => {
                      setFiltreAnnee("Tout");
                      setFiltreParcoursSel("Tout");
                      setTeacherFilter("");
                    }}
                  >
                    Tout afficher
                  </button>
                )}
              </div>
              {!readOnly && (
                <div className="promo-actions">
                  <button
                    type="button"
                    className="btn btn--sm"
                    aria-pressed={!listeMasquee}
                    onClick={() => {
                      if (listeMasquee) {
                        setListeMasquee(false);
                        setRoute?.({ panel: "aplacer" });
                      } else {
                        if (hasParked(park)) restaurerTousParks();
                        setListeMasquee(true);
                        setChoixAPlacer(null);
                        setRoute?.({ panel: "" });
                      }
                    }}
                  >
                    Séances à placer
                  </button>
                  {seanceModaleEnabled && (
                    <button type="button" className="btn btn--sm" onClick={() => setModaleEvenement(true)}>
                      Nouvel évènement
                    </button>
                  )}
                  {seanceModaleEnabled && (
                    <button type="button" className="btn btn--primary btn--sm" onClick={() => setModaleSeance("creer")}>
                      Nouvelle séance
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>

          {placementActif && (
            <div className="promo-bandeau promo-bandeau--placement" role="status">
              <p>
                <strong>Placement de {placementActif.course_code}</strong>{" "}
                <span className="muted">
                  {placementActif.session_type} · {placementActif.groupes_libelles.join(", ")} — cliquez une case
                  encadrée dans les colonnes {placementActif.parcours}.
                </span>
              </p>
              <button
                type="button"
                className="btn btn--sm"
                title="Échap"
                onClick={() => {
                  setChoixAPlacer(null);
                  onAnnulerPlacement?.();
                }}
              >
                Annuler
              </button>
            </div>
          )}
          {selPark && !placementActif && (
            <div className="promo-bandeau promo-bandeau--placement">
              <p>
                <strong>Déplacement de {selPark.origin.course_code}</strong>{" "}
                <span className="muted">— choisissez le jour, puis cliquez une case encadrée.</span>
              </p>
            </div>
          )}
          {erreurPlacement && (
            <div className="promo-bandeau promo-bandeau--erreur" role="alert">
              <p>{erreurPlacement}</p>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => setErreurPlacement(null)}>
                Fermer
              </button>
            </div>
          )}
          {/* Retour après chaque action, avec « Annuler » quand c'est possible
              — toujours dans le DOM : une région `aria-live` doit exister
              avant que son texte change pour être annoncée. */}
          <div className={`promo-retour${retour ? " visible" : ""}`} role="status" aria-live="polite">
            {retour && (
              <>
                <span>{retour.texte}</span>
                {retour.annuler && (
                  <button
                    type="button"
                    className="btn btn--sm"
                    disabled={annulationEnCours}
                    title="Ctrl + Z"
                    onClick={() => void lancerAnnulation()}
                  >
                    {annulationEnCours ? "Annulation…" : "Annuler"}
                  </button>
                )}
                <button
                  type="button"
                  className="btn btn--ghost btn--icon btn--sm promo-retour-fermer"
                  aria-label="Masquer ce message"
                  onClick={() => setRetour(null)}
                >
                  <span aria-hidden="true">×</span>
                </button>
              </>
            )}
          </div>

          {modaleEvenement && (
            <CreerEvenementModal
              payload={payload}
              suggestion={{ week: solverWeek ?? undefined, day }}
              onCancel={() => setModaleEvenement(false)}
              onCree={(placement) => {
                setModaleEvenement(false);
                signaler(`${placement.course_code} créé ${quand(placement.week, placement.day, placement.slot)}.`);
                allerA(placement.week, placement.day);
                onPlacementUpdated?.(placement);
                onSeanceChangee?.();
              }}
            />
          )}

          {modaleSeance && (
            <CreerSeanceModal
              payload={payload}
              mode={
                modaleSeance !== "creer" &&
                !payload.rows.some((row) => row.id === modaleSeance.session_id && row.custom)
                  ? "maquette"
                  : undefined
              }
              seanceExistante={modaleSeance === "creer" ? null : modaleSeance}
              // Pré-remplit semaine/jour depuis ce qui est AFFICHÉ (retour
              // Kyllian Bresson : « rester sur la semaine à saisir, sur le
              // jour à saisir ») — à la création seulement.
              suggestion={modaleSeance === "creer" ? { week: solverWeek ?? undefined, day } : null}
              onCancel={() => setModaleSeance(null)}
              onCree={(placement, options) => {
                // « Créer et en ajouter une autre » : la modale reste ouverte
                // et affiche sa propre confirmation.
                if (options?.garderOuverte) {
                  onPlacementUpdated?.(placement);
                  onSeanceChangee?.();
                  return;
                }
                setModaleSeance(null);
                signaler(
                  modaleSeance === "creer"
                    ? `${placement.course_code} créée ${quand(placement.week, placement.day, placement.slot)}.`
                    : `${placement.course_code} modifiée.`,
                );
                // On suit la séance là où elle a été posée, pour la voir.
                allerA(placement.week, placement.day);
                onPlacementUpdated?.(placement);
                onSeanceChangee?.();
              }}
              onRetiree={(sessionId) => {
                const courseCode = modaleSeance !== "creer" ? modaleSeance?.course_code : undefined;
                setModaleSeance(null);
                signaler(`${courseCode ?? sessionId} retirée du planning, elle attend dans « À placer ».`);
                onSeanceChangee?.();
              }}
            />
          )}

          <div className="panel promo-grille">
            <div className="promo-grille-entete">
              <h3>
                {portee} — {DAY_LABELS[day]}
                {dateJour ? ` ${formatShortDate(dateJour)}` : ""}
              </h3>
              {!couleursParMatiere && (
                <ul className="promo-legende" aria-label="Types de séance">
                  <li className="cm">CM</li>
                  <li className="td">TD</li>
                  <li className="tp">TP</li>
                  <li className="eval">Évaluation</li>
                </ul>
              )}
            </div>
            {solverWeek === null ? (
              <p className="promo-vide">Semaine fermée (vacances). Choisissez une autre semaine.</p>
            ) : colGroups.length === 0 ? (
              <p className="promo-vide">Aucun parcours pour ce filtre.</p>
            ) : (
              <div className="promo-grille-defil">
                <table
                  className={`promo-grid${teacherFilter ? " teacher-filter" : ""}${couleursParMatiere ? " couleurs-matiere" : ""}${draggingId ? " promo-grid--glisser" : ""}`}
                >
                  <thead>
                    <tr>
                      <th className="timecol" rowSpan={2}>
                        <span className="sr-only">Créneau</span>
                      </th>
                      {colGroups.map((g, gi) => (
                        <th key={g.parcours} colSpan={g.cols.length} className={`grp-band pc${gi % 6}`}>
                          {/* Cliquable seulement en édition : en lecture seule,
                              la modale n'aurait rien à proposer. */}
                          {dragEnabled ? (
                            <button
                              type="button"
                              className="grp-band-btn"
                              onClick={() => setParcoursOuvert(g.parcours)}
                              title={`Ouvrir la semaine complète de ${g.parcours} (pour changer une séance de jour)`}
                            >
                              {g.parcours}
                              <span className="grp-band-hint" aria-hidden="true">
                                semaine
                              </span>
                            </button>
                          ) : (
                            <span className="grp-band-libelle">{g.parcours}</span>
                          )}
                        </th>
                      ))}
                    </tr>
                    <tr>
                      {cols.map((c, i) => (
                        <th key={c} className={`grp-col ${colClass(i)}`}>
                          {payload.groupLabels[c] ?? c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {SLOT_TIMES.map((slot, s) => (
                      <Fragment key={s}>
                        {s === 3 && (
                          <tr className="pause">
                            <td className="timecell" />
                            {cols.map((c, i) => {
                              const largeur = largeursPause[i];
                              if (largeur === 0) return null;
                              const entries = byColPause.get(`${i}`) ?? [];
                              if (!entries.length) {
                                return <td key={c} className={colClass(i)} />;
                              }
                              return (
                                <td
                                  key={c}
                                  colSpan={largeur > 1 ? largeur : undefined}
                                  className={`promocell pause-cell ${colClass(i)}${largeur > 1 ? " promocell--fusion" : ""}`}
                                >
                                  {entries.map((r) => (
                                    <div
                                      key={r.id}
                                      className="promo-chip promo-chip--midi"
                                      title={`${r.n || r.c} — pause méridienne, hors des six créneaux fixes`}
                                    >
                                      <div className="promo-chip__l1">
                                        <span className="code">{r.n || r.c}</span>
                                      </div>
                                      <div className="promo-chip__l2">
                                        <span className="ty">
                                          {r.hor ?? ""}
                                          {r.r ? ` · ${r.r}` : ""}
                                        </span>
                                      </div>
                                    </div>
                                  ))}
                                </td>
                              );
                            })}
                          </tr>
                        )}
                        <tr>
                          <th scope="row" className="timecell">
                            {slot.label}
                          </th>
                          {cols.map((c, i) => {
                            const largeur = largeursParCreneau[s][i];
                            if (largeur === 0) return null;
                            const entries = byColSlot.get(`${i}-${s}`) ?? [];

                            const sae = payload.saeRows.find(
                              (x) => x.w === solverWeek && x.d === day && x.p === colParcours[i],
                            );
                            const eventsAtSlot = payload.eventSlotRows
                              .filter(
                                (e) =>
                                  e.w === solverWeek &&
                                  e.d === day &&
                                  e.s === s &&
                                  (!e.parcours.length || e.parcours.includes(colParcours[i])),
                              )
                              .map((e) => e.label);

                            // Case cible d'un placement en cours — séance
                            // manquante (son parcours) ou parquée (même règle).
                            const eligiblePark =
                              Boolean(selPark && solverWeek !== null) &&
                              (parkParcours === undefined || colParcours[i] === parkParcours);
                            const eligibleManquante =
                              Boolean(placementActif) && colParcours[i] === placementActif?.parcours;
                            const eligible = eligiblePark || eligibleManquante;
                            const colonneTiree = colonnesTirees.has(i);
                            const busyHit =
                              colonneTiree || eligible ? teacherBusyOnCell(teacherBusyMap, day, s, entries) : null;
                            const busyHint = busyHit ? (
                              <span className="promocell__teacher-busy">{teacherBusyLabel(busyHit)}</span>
                            ) : null;
                            const cleCellule = `${solverWeek}-${day}-${s}`;
                            const placementProps = eligible
                              ? {
                                  role: "button" as const,
                                  tabIndex: 0,
                                  onClick: () => {
                                    if (selPark) void poserParked(s);
                                    else void placerIci(s);
                                  },
                                  onKeyDown: (e: ReactKeyboardEvent) => {
                                    if (e.key === "Enter" || e.key === " ") {
                                      e.preventDefault();
                                      if (selPark) void poserParked(s);
                                      else void placerIci(s);
                                    }
                                  },
                                }
                              : {};

                            // État de dépôt : colonnes de la séance tirée
                            // seulement ; « conflit » si le groupe est déjà
                            // pris à cette heure ou l'enseignant ailleurs.
                            const autresIci = entries.some((r) => r.id !== draggingId);
                            const conflitDepot = colonneTiree && (autresIci || Boolean(busyHit));
                            const survolDepot =
                              dragEnabled &&
                              dropTarget?.day === day &&
                              dropTarget?.slot === s &&
                              (colonneTiree || colonnesTirees.size === 0);
                            const cellClass = [
                              "promocell",
                              colClass(i),
                              largeur > 1 ? "promocell--fusion" : "",
                              eligible ? "promocell--placeable" : "",
                              busyHit ? "promocell--teacher-busy" : "",
                              colonneTiree ? (conflitDepot ? "promocell--cible-conflit" : "promocell--cible") : "",
                              survolDepot ? "dropzone-hover" : "",
                            ]
                              .filter(Boolean)
                              .join(" ");
                            const libellePoser =
                              enCoursPlacement === cleCellule
                                ? "Placement…"
                                : eligiblePark || entries.length
                                  ? "+ poser ici (conflit possible)"
                                  : "+ poser ici";
                            const poser = eligible ? <div className="promocell-poser">{libellePoser}</div> : null;
                            const tdProps = {
                              colSpan: largeur > 1 ? largeur : undefined,
                              className: cellClass,
                              ...placementProps,
                              ...dropHandlers(day, s),
                            };

                            if (entries.length) {
                              return (
                                <td key={c} {...tdProps}>
                                  {poser}
                                  {busyHint}
                                  {entries.map((r) => {
                                    // Clé d'édition de salle UNIQUE PAR CASE : un
                                    // CM est rendu dans toutes les colonnes de sa
                                    // promo, et un `<select autoFocus>` par copie
                                    // se volaient le focus (seuls les TP restaient
                                    // modifiables).
                                    const cleEditionSalle = `${i}-${s}-${r.id}`;
                                    const source = placements?.find((p) => p.session_id === r.id);
                                    const draggableHere = dragEnabled && !!source && !source.locked;
                                    // Salle : l'état VIVANT des placements prime sur
                                    // `payload.rows`, rechargé plus tard (retour
                                    // utilisateur 31/08/2026 : « l'ancienne est
                                    // toujours là »). `payload.rows` reste la
                                    // source quand les deux s'accordent : lui seul
                                    // porte le suffixe « (Évaluation) ».
                                    const salleDuPayload = sallesTriees.find(
                                      (s2) => s2.label === (r.r ?? "").replace(/\s*\([^)]*\)\s*$/, ""),
                                    );
                                    const salleAffichee =
                                      !source || source.room_id === (salleDuPayload?.id ?? null)
                                        ? r.r
                                        : (source.room_label ?? "");
                                    return (
                                      <PromoCarte
                                        key={r.id}
                                        row={r}
                                        source={source}
                                        teacherLabels={payload.teacherLabels}
                                        salles={sallesTriees}
                                        salleAffichee={salleAffichee}
                                        highlighted={Boolean(teacherFilter) && r.te.includes(teacherFilter)}
                                        draggable={draggableHere}
                                        dragging={draggingId === r.id}
                                        swapTarget={cibleEchange === r.id}
                                        actions={seanceModaleEnabled && Boolean(source)}
                                        salleModifiable={roomEditEnabled}
                                        salleEnEdition={salleEnEdition === cleEditionSalle}
                                        salleEnCours={salleEnCours}
                                        salleSelectionnee={source?.room_id ?? salleDuPayload?.id ?? ""}
                                        onDragStart={
                                          draggableHere
                                            ? (e) => {
                                                e.dataTransfer.effectAllowed = "move";
                                                setDraggingId(r.id);
                                                setSalleEnEdition(null);
                                              }
                                            : undefined
                                        }
                                        onDragEnd={
                                          draggableHere
                                            ? () => {
                                                setDraggingId(null);
                                                setCibleEchange(null);
                                                setDropTarget(null);
                                              }
                                            : undefined
                                        }
                                        echangeHandlers={echangeHandlers(r.id)}
                                        onModifier={() => source && setModaleSeance(source)}
                                        onRetirer={() => void retirerDuPlanning(r.id, r.c)}
                                        onSupprimer={() => void supprimerSeance(r.id, `${r.c} (${r.t})`)}
                                        onOuvrirSalle={() => setSalleEnEdition(cleEditionSalle)}
                                        onChoisirSalle={(roomId) => {
                                          if (roomId === "__new__") {
                                            setCreationSallePour(r.id);
                                            setSalleEnEdition(null);
                                            return;
                                          }
                                          void appliquerSalle(r.id, roomId, source?.room_id);
                                        }}
                                        onFermerSalle={() => setSalleEnEdition(null)}
                                      />
                                    );
                                  })}
                                </td>
                              );
                            }
                            if (holiday) {
                              return (
                                <td key={c} {...tdProps}>
                                  {poser}
                                  {busyHint}
                                  <div className="sessiongrid-holiday">
                                    <span className="title">{holiday.kind === "vacances" ? "Vacances" : "Férié"}</span>
                                    <span className="label">{holiday.label}</span>
                                  </div>
                                </td>
                              );
                            }
                            if (sae) {
                              return (
                                <td key={c} {...tdProps}>
                                  {poser}
                                  {busyHint}
                                  <div className="sessiongrid-sae">
                                    <span className="title">SAE</span>
                                    <span className="codes">{sae.codes.join(", ")}</span>
                                  </div>
                                </td>
                              );
                            }
                            const libellesEvenement = eventsAtSlot.length ? eventsAtSlot : dayEvents;
                            if (libellesEvenement) {
                              return (
                                <td key={c} {...tdProps}>
                                  {poser}
                                  {busyHint}
                                  <div className="sessiongrid-event">
                                    {libellesEvenement.map((e) => (
                                      <span key={e} className="label">
                                        {e}
                                      </span>
                                    ))}
                                  </div>
                                </td>
                              );
                            }
                            return (
                              <td key={c} {...tdProps}>
                                {poser}
                                {busyHint}
                              </td>
                            );
                          })}
                        </tr>
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {!readOnly && (
              <p className="promo-raccourcis">
                <kbd>←</kbd> <kbd>→</kbd> jour · <kbd>Maj</kbd>+<kbd>←</kbd> <kbd>→</kbd> semaine · <kbd>T</kbd>{" "}
                aujourd'hui · <kbd>Échap</kbd> abandonner le placement · <kbd>Ctrl</kbd>+<kbd>Z</kbd> annuler
                {dragEnabled ? " · glisser sur une séance : échange · sur une barre de semaine : changer de semaine" : ""}
              </p>
            )}
          </div>

          {parcoursOuvert && placements && onPlacementUpdated && onError && (
            <ParcoursWeekModal
              payload={payload}
              parcours={parcoursOuvert}
              weekIndex={displayWeek}
              placements={placements}
              onClose={() => {
                if (hasParked(park)) restaurerTousParks();
                setParcoursOuvert(null);
              }}
              onPlacementUpdated={onPlacementUpdated}
              onError={onError}
              park={park}
              onParkChange={setPark}
            />
          )}

          {creationSallePour && (
            <NewRoomModal
              onCancel={() => setCreationSallePour(null)}
              onCreated={(salle) => {
                const sessionId = creationSallePour;
                setCreationSallePour(null);
                // Salle neuve : libre par construction, aucun conflit possible.
                void appliquerSalle(sessionId, salle.id);
              }}
            />
          )}
        </div>
      </div>
    </section>
  );
}
