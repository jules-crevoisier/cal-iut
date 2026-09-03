/**
 * Toutes les promos (BUT1→BUT3) sur une seule grille — portage fidèle de
 * `renderPromoTab`/`promoColumnGroups` (`export/templates/timetable.html`),
 * jamais aligné avec le HTML jusqu'ici. Trois écarts corrigés (retour
 * utilisateur 11/08/2026) :
 *
 * 1. Colonnes = groupes TP quand le parcours en a (ex. BUT1 : 8 colonnes
 *    TP A→H), PAS les 4 groupes TD — la version précédente s'arrêtait au
 *    niveau TD, jamais au niveau TP le plus fin ("on veut tous les tp, pas
 *    de BUT1" [en TD seulement]). Fallback TD uniquement pour les parcours
 *    SANS TP (FC, cohortes plus petites).
 * 2. Un cours "promo" (CM à toute la promo) n'est PAS une colonne à part —
 *    il apparaît DANS chaque colonne TP/TD de son parcours, comme un
 *    étudiant le vivrait ("Promo BUT1 si il y a un cours promo alors il
 *    est sur tous les tp/td"). Utilise `payload.groupCohort[gid]`
 *    (calculé côté serveur : TP + son TD + le CM promo), jamais une
 *    correspondance directe `group_ids.includes(colonne)`.
 * 3. Ordre des colonnes : année, puis FI avant FC de la même année, pas
 *    l'alphabétique brut ("les groupe [FC] sont mis après les fi").
 */

import { Fragment, useEffect, useMemo, useState } from "react";
import type { DragEvent as ReactDragEvent, KeyboardEvent as ReactKeyboardEvent } from "react";

import { changerSalle, deposerPlacement, supprimerSeancePersonnalisee, type SeanceAPlacer } from "../api/client";
import type { Placement } from "../types";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload, AppRow } from "../types/app";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";
import { confirmAsync } from "../utils/confirmDialog";
import { detailConflit, placerAvecConfirmation } from "../utils/placement";
import { ParcoursWeekModal } from "../components/ParcoursWeekModal";
import { couleursMatiere } from "../utils/couleursMatiere";
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
import { NewRoomModal } from "../components/NewRoomModal";
import { CreerSeanceModal } from "../components/CreerSeanceModal";
import { WeekBar } from "../components/WeekBar";
import { APlacerView } from "./APlacerView";
import {
  clearPark,
  createPark,
  decideWeekDrop,
  isHiddenOnGrid,
  replacePark,
  selectPark,
  type ParkUiState,
} from "../features/park-week-move/parkWeekMove";

interface PromoViewProps {
  /** Position demandée par un lien ou par « À traiter » (semaine + jour).
   *  Sans elle, une ligne « WR106 — aucune salle, mardi 11h » ouvrait bien
   *  la Vue Promo mais laissait chercher le bon jour à la main. */
  route?: Route;
  payload: AppPayload;
  /** Séance choisie dans « À placer », à poser directement sur cette
   * grille — `undefined`/absent = comportement normal (lecture seule),
   * inchangé (App.tsx ne les passe que depuis cette vue-là, la Vue Promo
   * reste utilisable seule ailleurs si jamais réutilisée). */
  placementActif?: SeanceAPlacer | null;
  onAnnulerPlacement?: () => void;
  onPlaced?: () => void;
  /** Glisser-déposer d'une séance DÉJÀ placée — retour utilisateur
   * 28/08/2026 : « on enlève la possibilité de drag and drop dans vue
   * semaine [...] on veut que cela soit possible dans vue promo ». Les
   * trois props vont ensemble ; absentes (ex. Vue Promo intégrée dans
   * « À placer », qui n'a que `payload`), la grille reste lecture seule
   * pour ce qui est déjà au planning — le placement d'une séance MANQUANTE
   * (`placementActif` ci-dessus) reste, lui, toujours possible. */
  placements?: Placement[];
  onPlacementUpdated?: (p: Placement) => void;
  onError?: (msg: string) => void;
  /** Une séance personnalisée a été créée, modifiée ou supprimée — recharge
   * `payload` (compteurs de la matière, contenu des cases) et la liste des
   * placements. Même garde que `placements`/`onPlacementUpdated` : absent
   * en lecture seule. */
  onSeanceChangee?: () => void;
  setRoute?: (patch: Partial<Route>) => void;
  onAPlacerRefresh?: () => void;
  /** Lien public « Vue Promo » (retour utilisateur 31/08/2026 : « un lien
   * en plus ouvert à tout le monde [...] accès à la vue promo ») — maître
   * absolu, à la différence des props ci-dessus qui ne coupaient QUE
   * glisser-déposer/salle/création. Sans lui, le panneau « Séances à
   * placer » et le clic-pour-placer restaient actifs même sans ces props
   * (ils ne dépendent que de `placementActif`, jamais vérifiés) : un lien
   * public aurait donc pu écrire au planning malgré son intention "lecture
   * seule". `readOnly` coupe tout, sans exception, même si l'appelant
   * passe les callbacks d'édition par erreur. */
  readOnly?: boolean;
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
  const [choixAPlacer, setChoixAPlacer] = useState<SeanceAPlacer | null>(null);
  const [listeMasquee, setListeMasquee] = useState(() => route?.panel !== "aplacer");
  const [park, setPark] = useState<ParkUiState>(() => clearPark());
  const placementActif = readOnly ? null : (placementActifProp ?? choixAPlacer);
  const [displayWeek, setDisplayWeek] = useState(0);
  const [day, setDay] = useState(0);
  const [teacherFilter, setTeacherFilter] = useState("");
  const [enCoursPlacement, setEnCoursPlacement] = useState<string | null>(null);
  const [erreurPlacement, setErreurPlacement] = useState<string | null>(null);
  const [annonce, setAnnonce] = useState("");
  const [draggingId, setDraggingId] = useState<string | null>(null);
  // Séance SURVOLÉE par le glisser en cours : déposer dessus propose un
  // échange plutôt qu'un déplacement (retour utilisateur 29/08/2026).
  const [cibleEchange, setCibleEchange] = useState<string | null>(null);
  // Parcours dont la semaine complète est ouverte en modale — c'est le seul
  // endroit de l'application où l'on peut déplacer une séance d'un JOUR à un
  // autre (la Vue Promo, elle, n'affiche qu'un jour à la fois).
  const [parcoursOuvert, setParcoursOuvert] = useState<string | null>(null);
  const couleursParMatiere = usePreferences().couleursParMatiere;
  const [dropTarget, setDropTarget] = useState<{ day: number; slot: number } | null>(null);
  const dragEnabled = !readOnly && Boolean(placements && onPlacementUpdated && onError);

  useEffect(() => {
    if (!readOnly && route?.panel === "aplacer") setListeMasquee(false);
  }, [route?.panel, readOnly]);

  // Édition de la SALLE seule (retour utilisateur 28/08/2026 : « on va
  // vouloir sur la vue promo modifier uniquement les salles ») — même
  // condition d'activation que le glisser-déposer : réservé au contexte
  // d'édition (onglet Vue Promo), jamais dans la Vue Promo intégrée à
  // « À placer », qui ne reçoit pas ces props.
  const [salleEnEdition, setSalleEnEdition] = useState<string | null>(null);
  const [salleEnCours, setSalleEnCours] = useState(false);
  const roomEditEnabled = !readOnly && Boolean(onPlacementUpdated && onError);
  // Séance pour laquelle on est en train de créer une salle — la salle
  // créée lui est appliquée directement, sans re-sélection manuelle.
  const [creationSallePour, setCreationSallePour] = useState<string | null>(null);
  const sallesTriees = useMemo(
    () => [...payload.rooms].sort((a, b) => a.label.localeCompare(b.label, "fr")),
    [payload.rooms],
  );

  // Créer / modifier une séance personnalisée (retour utilisateur
  // 31/08/2026) — même garde d'activation que le reste de l'édition.
  // `"creer"` = formulaire vide ; un `Placement` = édition de cette séance.
  const [modaleSeance, setModaleSeance] = useState<"creer" | Placement | null>(null);
  const seanceModaleEnabled = roomEditEnabled;

  const appliquerSalle = async (sessionId: string, roomId: string) => {
    if (!roomId || !onPlacementUpdated || !onError) return;
    setSalleEnCours(true);
    try {
      let maj = await changerSalle(sessionId, { room_id: roomId }).catch(async (e) => {
        const detail = detailConflit(e);
        if (!detail) throw e;
        // Salle occupée ET/OU capacité insuffisante : les deux sont montrés,
        // en forçage explicite (modale interne, pas `window.confirm`). Le
        // titre suit ce qui est RÉELLEMENT en cause — annoncer « Salle déjà
        // occupée » pour un simple souci de capacité enverrait chercher un
        // conflit d'occupation qui n'existe pas.
        // Le verrou de semaine arrive par le même canal depuis le 31/08/2026 :
        // il se dit lui-même, il ne s'annonce pas « Salle déjà occupée ».
        const verrou = detail.hard_conflicts.some((m) => m.includes("non modifiable"));
        const titre = verrou
          ? "Semaine déjà en cours"
          : detail.hard_conflicts.length
            ? "Salle déjà occupée"
            : "Attention à la capacité";
        const forcer = await confirmAsync(
          [...detail.hard_conflicts, ...detail.soft_warnings].join("\n"),
          { title: titre, confirmLabel: "Mettre quand même cette salle" },
        );
        if (!forcer) return null;
        return changerSalle(sessionId, { room_id: roomId, force: true });
      });
      if (maj) {
        onPlacementUpdated(maj);
        setAnnonce(`Salle changée : ${maj.room_label ?? roomId}.`);
        setSalleEnEdition(null);
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : "Changement de salle impossible");
    } finally {
      setSalleEnCours(false);
    }
  };

  // Supprimer une séance personnalisée — jamais une séance de la maquette,
  // le bouton n'apparaît d'ailleurs que sur `r.custom` (retour utilisateur
  // 31/08/2026 : « création + suppression + modification complète »).
  const supprimerSeance = async (sessionId: string, libelle: string) => {
    const confirme = await confirmAsync(`Supprimer définitivement « ${libelle} » ?`, {
      title: "Supprimer la séance",
      confirmLabel: "Supprimer",
    });
    if (!confirme) return;
    try {
      await supprimerSeancePersonnalisee(sessionId);
      setAnnonce(`${libelle} supprimée.`);
      onSeanceChangee?.();
    } catch (e) {
      onError?.(e instanceof Error ? e.message : "Suppression impossible");
    }
  };

  // Suit la route quand elle change (clic depuis « À traiter »), sans
  // reprendre la main sur la navigation manuelle ensuite.
  useEffect(() => {
    if (route?.sem === null || route?.sem === undefined) return;
    const idx = payload.weekRows.findIndex((w) => w.weekIndex === route.sem);
    if (idx >= 0) setDisplayWeek(idx);
    if (route.jour !== null && route.jour !== undefined) setDay(route.jour);
    // Volontairement déclenché par la ROUTE seule.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route?.sem, route?.jour]);

  const solverWeek = payload.weekRows[displayWeek]?.weekIndex ?? null;

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
    } else if (park.parked && park.selected) {
      teachers = park.parked.origin.teacher_codes;
      excludeId = park.parked.sessionId;
    } else {
      return new Map<string, TeacherBusyHit>();
    }
    return teacherBusyByDaySlot(payload.rows, teachers, solverWeek, excludeId);
  }, [draggingId, placementActif, park.parked, park.selected, payload.rows, solverWeek]);

  // À l'activation d'un placement (arrivée depuis « À placer »), saute
  // directement sur sa première semaine idéale plutôt que de laisser la
  // personne chercher — la Vue Promo reste sur cette semaine/jour tant
  // qu'elle navigue elle-même ensuite (pas de re-saut à chaque re-rendu).
  useEffect(() => {
    if (!placementActif) return;
    const semaineIdeale = placementActif.semaines_possibles[0];
    if (semaineIdeale === undefined) return;
    const idx = payload.weekRows.findIndex((w) => w.weekIndex === semaineIdeale);
    if (idx >= 0) setDisplayWeek(idx);
    setErreurPlacement(null);
    // Volontairement déclenché seulement par un CHANGEMENT de séance
    // active (nouvelle sélection depuis « À placer »), pas par la
    // navigation ultérieure dans `payload.weekRows`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placementActif?.session_id]);

  const teacherCodes = useMemo(
    () =>
      Object.keys(payload.teacherLabels).sort((a, b) =>
        (payload.teacherLabels[a] ?? a).localeCompare(payload.teacherLabels[b] ?? b, "fr"),
      ),
    [payload.teacherLabels],
  );

  const { cols, colGroups, colCohorts, colParcours } = useMemo(() => {
    const allGroupIds = Object.keys(payload.groupLabels);
    const allParcoursList = [...new Set(Object.values(payload.groupParcours))];

    const groups = allParcoursList
      .map((pc) => {
        const tpIds = allGroupIds.filter((gid) => payload.groupParcours[gid] === pc && payload.groupKind[gid] === "tp");
        const leaf = tpIds.length
          ? tpIds
          : allGroupIds.filter((gid) => payload.groupParcours[gid] === pc && payload.groupKind[gid] !== "promo");
        // Fallback : si un parcours n'a ni TP ni TD (ou seulement promo),
        // garder quand même une colonne pour pouvoir y poser une manquante
        // (bug « clic À placer ne place rien » — colonnes filtrées à vide).
        const cols =
          leaf.length > 0
            ? leaf
            : allGroupIds.filter((gid) => payload.groupParcours[gid] === pc);
        return {
          parcours: pc,
          cols: cols.sort((a, b) =>
            lettresGroupe(payload.groupLabels[a] ?? a).localeCompare(lettresGroupe(payload.groupLabels[b] ?? b), "fr"),
          ),
        };
      })
      .filter((g) => g.cols.length);

    // Année d'abord, puis LETTRES du premier groupe — et non le nom du
    // parcours. Retour utilisateur 30/08/2026 : en BUT3 les colonnes
    // sortaient « A, B, GH, EF », parce que « CREACOM » précède « DEV »
    // alphabétiquement. Trier sur les lettres donne « A, B, EF, GH », qui
    // se lit sans surprise — et garde au passage les FI avant les FC,
    // puisque leurs groupes commencent aux premières lettres.
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
    };
  }, [payload.groupLabels, payload.groupParcours, payload.groupKind, payload.groupCohort]);

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

  // Barre de jours (SAE/férié/événement d'AU MOINS un parcours ce jour-là —
  // même repère visuel que `renderPromoDayBar`).
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
  if (solverWeek !== null) {
    for (const r of payload.rows) {
      if (isHiddenOnGrid(park, r.id)) continue;
      if (r.w !== solverWeek || r.d !== day) continue;
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

  const holiday = solverWeek === null ? undefined : payload.holidayRows.find((h) => h.w === solverWeek && h.d === day);
  const dayEvents =
    solverWeek === null ? undefined : payload.eventRows.find((e) => e.w === solverWeek && e.d === day)?.labels;

  const placerIci = async (slot: number) => {
    if (!placementActif || solverWeek === null) return;
    const cle = `${solverWeek}-${day}-${slot}`;
    setEnCoursPlacement(cle);
    setErreurPlacement(null);
    const resultat = await placerAvecConfirmation(placementActif.session_id, { week: solverWeek, day, slot });
    setEnCoursPlacement(null);
    if (resultat.ok) {
      setAnnonce(`${placementActif.course_code} placé ${DAY_LABELS[day]} ${SLOT_TIMES[slot].label}.`);
      setChoixAPlacer(null);
      onPlaced?.();
      onAPlacerRefresh?.();
    } else {
      setErreurPlacement(resultat.message);
    }
  };

  const restaurerPark = () => {
    const originWeek = park.parked?.origin.week;
    setPark(clearPark());
    if (originWeek === undefined) return;
    const idx = payload.weekRows.findIndex((w) => w.weekIndex === originWeek);
    if (idx >= 0) setDisplayWeek(idx);
  };

  const poserParked = async (slot: number) => {
    if (!park.parked || !park.selected || !onPlacementUpdated || !onError || solverWeek === null) return;
    const origin = park.parked.origin;
    const cle = `${solverWeek}-${day}-${slot}`;
    setEnCoursPlacement(cle);
    const ok = await performMove(
      origin.session_id,
      { week: solverWeek, day, slot },
      origin,
      onPlacementUpdated,
      onError,
    );
    setEnCoursPlacement(null);
    if (ok) {
      setAnnonce(`${origin.course_code} déplacé ${DAY_LABELS[day]} ${SLOT_TIMES[slot].label}.`);
      setPark(clearPark());
    }
  };

  const retirerDuPlanning = async (sessionId: string, courseCode: string) => {
    const ok = await confirmAsync(
      `Retirer ${courseCode} du planning et le remettre dans « À placer » ?`,
      { title: "Retirer du planning", confirmLabel: "Retirer", cancelLabel: "Annuler" },
    );
    if (!ok) return;
    try {
      await deposerPlacement(sessionId);
      setAnnonce(`${courseCode} retirée du planning — repose-la depuis « À placer ».`);
      onSeanceChangee?.();
      onAPlacerRefresh?.();
    } catch (e) {
      onError?.(e instanceof Error ? e.message : "Retrait impossible");
    }
  };

  // Glisser-déposer d'une séance déjà placée — même logique que l'ancien
  // TdWeekGrid (validation -> confirmation si conflit -> forçage ou non,
  // `utils/moveSession.ts::performMove`), déplacée ici (retour utilisateur
  // 28/08/2026). `dragEnabled` seul détermine si c'est actif — voir
  // `PromoViewProps.placements`.
  const handleDrop = async (targetDay: number, slot: number) => {
    setDropTarget(null);
    const sessionId = draggingId;
    setDraggingId(null);
    if (!sessionId || !placements || !onPlacementUpdated || !onError || solverWeek === null) return;
    const placement = placements.find((p) => p.session_id === sessionId);
    if (!placement || placement.locked) return;
    if (placement.day === targetDay && placement.slot === slot && placement.week === solverWeek) return;
    await performMove(sessionId, { week: solverWeek, day: targetDay, slot }, placement, onPlacementUpdated, onError);
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
    setPark((actuel) => (actuel.parked ? replacePark(actuel, placement, displayIndex) : createPark(placement, displayIndex)));
    setChoixAPlacer(null);
    setListeMasquee(false);
    setRoute?.({ panel: "aplacer" });
    setDisplayWeek(displayIndex);
  };

  /** Dépôt SUR une séance : les deux échangent leurs places. Un seul appel
   *  serveur, qui juge les deux positions finales ensemble — cf.
   *  `utils/moveSession.ts::performSwap`. */
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
    await performSwap(sourceId, cibleId, source.course_code, cible.course_code, onPlacementUpdated, onError);
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
          onDragLeave: () =>
            setDropTarget((cur) => (cur?.day === targetDay && cur?.slot === slot ? null : cur)),
          onDrop: (e: ReactDragEvent) => {
            e.preventDefault();
            void handleDrop(targetDay, slot);
          },
        }
      : {};

  return (
    <section className="view promo">
      <p role="status" aria-live="polite" className="sr-only">
        {annonce}
      </p>

      <div className="promo-avec-aplacer">
        {!readOnly && !listeMasquee && (
          <APlacerView
            variante="panneau"
            payload={payload}
            onPlacement={() => onAPlacerRefresh?.()}
            onChoisirSurPromo={(seance) => {
              setChoixAPlacer(seance);
              setPark((actuel) => (actuel.parked ? { ...actuel, selected: false } : actuel));
            }}
            onFermer={() => {
              if (park.parked) restaurerPark();
              setListeMasquee(true);
              setChoixAPlacer(null);
              setRoute?.({ panel: "" });
            }}
            park={park}
            onSelectPark={() => {
              setChoixAPlacer(null);
              setPark(selectPark(park));
            }}
            onAnnulerPark={restaurerPark}
          />
        )}
        <div className="promo-principal">
      {!readOnly && listeMasquee && (
        <button
          type="button"
          className="btn btn--ghost btn--sm promo-aplacer-ouvrir"
          onClick={() => {
            setListeMasquee(false);
            setRoute?.({ panel: "aplacer" });
          }}
        >
          Séances à placer
        </button>
      )}

      {placementActif && (
        <div className="panel promo-placement-actif">
          <div>
            <strong>Placement en cours : {placementActif.course_code}</strong>
            <span className="muted">
              {" "}
              — {placementActif.session_type} · {placementActif.groupes_libelles.join(", ")} · cliquez une case
              libre de la colonne {placementActif.parcours} ci-dessous.
            </span>
          </div>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => {
              setChoixAPlacer(null);
              onAnnulerPlacement?.();
            }}
          >
            Annuler
          </button>
        </div>
      )}
      {erreurPlacement && (
        <div className="panel promo-placement-erreur">
          <p className="alerte">{erreurPlacement}</p>
        </div>
      )}

      <div className="panel controls">
        <div className="field weekfield">
          <WeekBar
            weekRows={payload.weekRows}
            countByWeekIndex={countByWeek}
            selected={displayWeek}
            onSelect={setDisplayWeek}
            dropEnabled={dragEnabled && Boolean(draggingId)}
            onDropWeek={dragEnabled ? handleDropOnWeek : undefined}
          />
        </div>
        <label>
          Enseignant
          <select value={teacherFilter} onChange={(e) => setTeacherFilter(e.target.value)}>
            <option value="">Tous</option>
            {teacherCodes.map((c) => (
              <option key={c} value={c}>
                {payload.teacherLabels[c]}
              </option>
            ))}
          </select>
        </label>
        {seanceModaleEnabled && (
          <button type="button" className="btn btn--accent btn--sm" onClick={() => setModaleSeance("creer")}>
            + Nouvelle séance
          </button>
        )}
      </div>

      {modaleSeance && (
        <CreerSeanceModal
          payload={payload}
          mode={
            modaleSeance && modaleSeance !== "creer" && !payload.rows.some((row) => row.id === modaleSeance.session_id && row.custom)
              ? "maquette"
              : undefined
          }
          seanceExistante={modaleSeance === "creer" ? null : modaleSeance}
          onCancel={() => setModaleSeance(null)}
          onCree={(placement) => {
            setModaleSeance(null);
            setAnnonce(
              modaleSeance === "creer"
                ? `${placement.course_code} créée ${DAY_LABELS[placement.day]} ${SLOT_TIMES[placement.slot].label}.`
                : `${placement.course_code} modifiée.`,
            );
            onPlacementUpdated?.(placement);
            onSeanceChangee?.();
          }}
          onRetiree={(sessionId) => {
            const courseCode = modaleSeance !== "creer" ? modaleSeance?.course_code : undefined;
            setModaleSeance(null);
            setAnnonce(`${courseCode ?? sessionId} retirée du planning — repose-la depuis « À placer ».`);
            onSeanceChangee?.();
          }}
        />
      )}

      <div className="daybar">
        {DAY_LABELS.map((label, d) => {
          const badge = dayBadges[d];
          const dateLabel = formatShortDate(dateForWeekDay(payload, solverWeek ?? -1, d));
          return (
            <button
              key={label}
              type="button"
              className={`daybtn ${d === day ? "active" : ""} ${badge ?? ""}`}
              onClick={() => setDay(d)}
            >
              {label}
              {dateLabel ? ` ${dateLabel}` : ""}
              {badge ? " •" : ""}
            </button>
          );
        })}
      </div>

      <div className="panel">
        <h3>
          Toutes promos — {DAY_LABELS[day]} — {payload.weekRows[displayWeek]?.label ?? ""}
        </h3>
        {solverWeek === null ? (
          <p className="muted">Semaine bloquée (vacances/fermeture).</p>
        ) : (
          <div className="ref-table-wrap">
            <table className={`promo-grid ${teacherFilter ? "teacher-filter" : ""}${couleursParMatiere ? " couleurs-matiere" : ""}`}>
              <thead>
                <tr>
                  <th className="timecol" rowSpan={2} />
                  {colGroups.map((g, gi) => (
                    <th key={g.parcours} colSpan={g.cols.length} className={`grp-band pc${gi % 6}`}>
                      {/* Cliquable seulement quand l'édition est possible :
                          en lecture seule (lien public), la modale n'aurait
                          rien à proposer. */}
                      {dragEnabled ? (
                        <button
                          type="button"
                          className="grp-band-btn"
                          onClick={() => setParcoursOuvert(g.parcours)}
                          title={`Ouvrir la semaine complète de ${g.parcours} (déplacement entre jours)`}
                        >
                          {g.parcours}
                        </button>
                      ) : (
                        g.parcours
                      )}
                    </th>
                  ))}
                </tr>
                <tr>
                  {cols.map((c, i) => (
                    <th key={c} className={colClass(i)}>
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
                        {cols.map((c, i) => (
                          <td key={c} className={colClass(i)} />
                        ))}
                      </tr>
                    )}
                    <tr>
                      <td className="timecell mono">{slot.label}</td>
                      {cols.map((c, i) => {
                        const entries = byColSlot.get(`${i}-${s}`) ?? [];
                        const cellClass = `promocell ${colClass(i)}`;
                        const busyHit = teacherBusyOnCell(teacherBusyMap, day, s, entries);
                        const busyClass = busyHit ? " promocell--teacher-busy" : "";
                        const busyHint = busyHit ? (
                          <span className="promocell__teacher-busy">{teacherBusyLabel(busyHit)}</span>
                        ) : null;
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

                        // Cellule cible pour un placement en cours — manquante
                        // (parcours de la séance) ou séance parquée (même règle).
                        const parkParcours = park.parked
                          ? park.parked.origin.group_ids
                              .map((g) => payload.groupParcours[g])
                              .find((pc): pc is string => Boolean(pc))
                          : undefined;
                        const eligiblePark =
                          Boolean(park.parked && park.selected && solverWeek !== null) &&
                          (parkParcours === undefined || colParcours[i] === parkParcours);
                        const eligibleManquante =
                          Boolean(placementActif) && colParcours[i] === placementActif?.parcours;
                        const eligible = eligiblePark || eligibleManquante;
                        const cleCellule = `${solverWeek}-${day}-${s}`;
                        const placementProps = eligible
                          ? {
                              role: "button" as const,
                              tabIndex: 0,
                              onClick: () => {
                                if (park.parked && park.selected) void poserParked(s);
                                else void placerIci(s);
                              },
                              onKeyDown: (e: ReactKeyboardEvent) => {
                                if (e.key === "Enter" || e.key === " ") {
                                  e.preventDefault();
                                  if (park.parked && park.selected) void poserParked(s);
                                  else void placerIci(s);
                                }
                              },
                            }
                          : {};
                        const eligibleClass = eligible ? " promocell--placeable" : "";
                        const isDropHover = dragEnabled && dropTarget?.day === day && dropTarget?.slot === s;
                        const dropCls = isDropHover ? " dropzone-hover" : "";
                        const libellePoser =
                          enCoursPlacement === cleCellule
                            ? "Placement…"
                            : eligiblePark || entries.length
                              ? "+ poser ici (conflit possible)"
                              : "+ poser ici";

                        if (entries.length) {
                          return (
                            <td
                              key={c}
                              className={cellClass + eligibleClass + dropCls + busyClass}
                              {...placementProps}
                              {...dropHandlers(day, s)}
                            >
                              {eligible && (
                                <div className="promocell-poser">
                                  {libellePoser}
                                </div>
                              )}
                              {busyHint}
                              {entries.map((r) => {
                                const highlighted = teacherFilter && r.te.includes(teacherFilter);
                                const teacherNames = r.te.map((tc) => payload.teacherLabels[tc] ?? tc).join(", ");
                                const durLabel = (r.dur || 1) > 1 ? ` · ${((r.dur || 1) * 1.5).toFixed(1).replace(".0", "")}h` : "";
                                // Clé d'édition de salle UNIQUE PAR CELLULE, pas par
                                // séance : un CM de promo est rendu dans TOUTES les
                                // colonnes de sa promo (et sur chaque créneau de sa
                                // durée). Avec la seule `r.id`, cliquer « changer la
                                // salle » ouvrait un <select autoFocus> dans chacune
                                // — chacun volant le focus au précédent, dont le
                                // `onBlur` refermait aussitôt l'édition. Symptôme
                                // observé : seuls les TP (présents dans une seule
                                // colonne) étaient modifiables.
                                const cleEditionSalle = `${i}-${s}-${r.id}`;
                                // Verrouillée = jamais glissable, même quand le
                                // drag est actif (même règle que l'ancien
                                // TdWeekGrid) — `placements` sert UNIQUEMENT à
                                // ça ici, le contenu affiché reste `payload.rows`.
                                const source = placements?.find((p) => p.session_id === r.id);
                                const draggableHere = dragEnabled && !!source && !source.locked;
                                // Salle : l'état VIVANT des placements prime sur
                                // `payload.rows`. Changer une salle mettait bien à jour
                                // `placements` sur-le-champ, mais le libellé affiché,
                                // lui, venait du payload — rechargé seulement par
                                // l'appel asynchrone de 550 Ko qui suit. L'ancienne
                                // salle restait donc à l'écran (retour utilisateur
                                // 31/08/2026 : « le changement de salle n'est pas pris
                                // en compte, l'ancienne est toujours là »).
                                //
                                // `payload.rows` reste la source quand les deux
                                // s'accordent : lui seul porte le suffixe
                                // « (Évaluation) » des CM d'examen, que
                                // `room_label` n'a pas.
                                const salleDuPayload = sallesTriees.find(
                                  (s2) => s2.label === (r.r ?? "").replace(/\s*\([^)]*\)\s*$/, ""),
                                );
                                const salleAffichee =
                                  !source || source.room_id === (salleDuPayload?.id ?? null)
                                    ? r.r
                                    : source.room_label ?? "";
                                return (
                                  <div
                                    key={r.id}
                                    draggable={draggableHere}
                                    onDragStart={
                                      draggableHere
                                        ? (e) => {
                                            e.dataTransfer.effectAllowed = "move";
                                            setDraggingId(r.id);
                                          }
                                        : undefined
                                    }
                                    onDragEnd={
                                      draggableHere
                                        ? () => {
                                            setDraggingId(null);
                                            setCibleEchange(null);
                                          }
                                        : undefined
                                    }
                                    {...echangeHandlers(r.id)}
                                    style={couleursMatiere(r.c) as React.CSSProperties}
                                    className={`promo-chip type-${r.t.toLowerCase()} ${r.ev ? "eval" : ""} ${highlighted ? "chip-highlight" : ""} ${draggableHere ? "promo-chip--draggable" : ""} ${draggingId === r.id ? "dragging" : ""} ${cibleEchange === r.id ? "swap-target" : ""}`}
                                  >
                                    <span className="code">{r.c}</span>
                                    <span className="ty">
                                      {r.t}
                                      {r.ev ? " · éval" : ""}
                                      {durLabel}
                                    </span>
                                    {seanceModaleEnabled && source && (
                                      <span className="promo-chip-custom">
                                        <button
                                          type="button"
                                          className="promo-chip-custom-btn"
                                          title="Modifier cette séance"
                                          aria-label="Modifier cette séance"
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            setModaleSeance(source);
                                          }}
                                          onMouseDown={(e) => e.stopPropagation()}
                                        >
                                          ✎
                                        </button>
                                        <button
                                          type="button"
                                          className="promo-chip-custom-btn"
                                          title="Retirer du planning (vers À placer)"
                                          aria-label={`Retirer ${r.c} du planning`}
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            void retirerDuPlanning(r.id, r.c);
                                          }}
                                          onMouseDown={(e) => e.stopPropagation()}
                                        >
                                          ↩
                                        </button>
                                        {r.custom && (
                                        <button
                                          type="button"
                                          className="promo-chip-custom-btn"
                                          title="Supprimer cette séance"
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            void supprimerSeance(r.id, `${r.c} (${r.t})`);
                                          }}
                                          onMouseDown={(e) => e.stopPropagation()}
                                        >
                                          🗑
                                        </button>
                                        )}
                                      </span>
                                    )}
                                    {/* Salle modifiable sur place (retour utilisateur
                                        28/08/2026) — un <select> apparaît à la place du
                                        libellé au clic. `stopPropagation` sur le clic :
                                        sans lui, ouvrir le sélecteur déclencherait aussi
                                        le clic de la CELLULE (poser une séance en cours
                                        de placement). */}
                                    {salleEnEdition === cleEditionSalle ? (
                                      <select
                                        className="rm promo-chip-salle"
                                        autoFocus
                                        disabled={salleEnCours}
                                        defaultValue={source?.room_id ?? salleDuPayload?.id ?? ""}
                                        onClick={(e) => e.stopPropagation()}
                                        onMouseDown={(e) => e.stopPropagation()}
                                        onChange={(e) => {
                                          if (e.target.value === "__new__") {
                                            setCreationSallePour(r.id);
                                            setSalleEnEdition(null);
                                            return;
                                          }
                                          void appliquerSalle(r.id, e.target.value);
                                        }}
                                        onBlur={() => setSalleEnEdition(null)}
                                      >
                                        <option value="">— choisir une salle —</option>
                                        <option value="__new__">+ Créer une salle…</option>
                                        {sallesTriees.map((s2) => (
                                          <option key={s2.id} value={s2.id}>
                                            {s2.label} ({s2.capacity} pl.)
                                          </option>
                                        ))}
                                      </select>
                                    ) : roomEditEnabled ? (
                                      <button
                                        type="button"
                                        className={`rm promo-chip-salle-btn${salleAffichee ? "" : " rm--absente"}`}
                                        title="Changer la salle"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          setSalleEnEdition(cleEditionSalle);
                                        }}
                                        onMouseDown={(e) => e.stopPropagation()}
                                      >
                                        {salleAffichee || "salle à définir"}
                                      </button>
                                    ) : (
                                      <span className={`rm${salleAffichee ? "" : " rm--absente"}`}>
                                        {salleAffichee || "salle à définir"}
                                      </span>
                                    )}
                                    <span className="te">{teacherNames || "—"}</span>
                                  </div>
                                );
                              })}
                            </td>
                          );
                        }
                        if (holiday) {
                          return (
                            <td
                              key={c}
                              className={cellClass + eligibleClass + dropCls + busyClass}
                              {...placementProps}
                              {...dropHandlers(day, s)}
                            >
                              {eligible && <div className="promocell-poser">{libellePoser}</div>}
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
                            <td
                              key={c}
                              className={cellClass + eligibleClass + dropCls + busyClass}
                              {...placementProps}
                              {...dropHandlers(day, s)}
                            >
                              {eligible && <div className="promocell-poser">{libellePoser}</div>}
                              {busyHint}
                              <div className="sessiongrid-sae">
                                <span className="title">SAE</span>
                                <span className="codes">{sae.codes.join(", ")}</span>
                              </div>
                            </td>
                          );
                        }
                        if (eventsAtSlot.length) {
                          return (
                            <td
                              key={c}
                              className={cellClass + eligibleClass + dropCls + busyClass}
                              {...placementProps}
                              {...dropHandlers(day, s)}
                            >
                              {eligible && <div className="promocell-poser">{libellePoser}</div>}
                              {busyHint}
                              <div className="sessiongrid-event">
                                {eventsAtSlot.map((e) => (
                                  <span key={e} className="label">
                                    {e}
                                  </span>
                                ))}
                              </div>
                            </td>
                          );
                        }
                        if (dayEvents) {
                          return (
                            <td
                              key={c}
                              className={cellClass + eligibleClass + dropCls + busyClass}
                              {...placementProps}
                              {...dropHandlers(day, s)}
                            >
                              {eligible && <div className="promocell-poser">{libellePoser}</div>}
                              {busyHint}
                              <div className="sessiongrid-event">
                                {dayEvents.map((e) => (
                                  <span key={e} className="label">
                                    {e}
                                  </span>
                                ))}
                              </div>
                            </td>
                          );
                        }
                        return (
                          <td
                            key={c}
                            className={cellClass + eligibleClass + dropCls + busyClass}
                            {...placementProps}
                            {...dropHandlers(day, s)}
                          >
                            {eligible && (
                              <div className="promocell-poser">
                                {libellePoser}
                              </div>
                            )}
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
      </div>

      {parcoursOuvert && placements && onPlacementUpdated && onError && (
        <ParcoursWeekModal
          payload={payload}
          parcours={parcoursOuvert}
          weekIndex={displayWeek}
          placements={placements}
          onClose={() => {
            if (park.parked) restaurerPark();
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
            // La salle vient d'être créée côté serveur : elle est libre par
            // construction, l'appliquer ne peut pas buter sur un conflit.
            void appliquerSalle(sessionId, salle.id);
          }}
        />
      )}
        </div>
      </div>
    </section>
  );
}
