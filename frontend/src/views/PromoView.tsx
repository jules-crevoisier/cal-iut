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

import { changerSalle, type SeanceAPlacer } from "../api/client";
import type { Placement } from "../types";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload, AppRow } from "../types/app";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";
import { confirmAsync } from "../utils/confirmDialog";
import { detailConflit, placerAvecConfirmation } from "../utils/placement";
import { ParcoursWeekModal } from "../components/ParcoursWeekModal";
import { couleursMatiere } from "../utils/couleursMatiere";
import { performMove, performSwap } from "../utils/moveSession";
import { usePreferences } from "../utils/preferences";
import { dateForWeekDay, formatShortDate } from "../utils/weekDates";
import { compareParcoursForDisplay } from "../utils/years";
import { NewRoomModal } from "../components/NewRoomModal";
import { WeekBar } from "../components/WeekBar";

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
}

export function PromoView({
  payload,
  route,
  placementActif = null,
  onAnnulerPlacement,
  onPlaced,
  placements,
  onPlacementUpdated,
  onError,
}: PromoViewProps) {
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
  const dragEnabled = Boolean(placements && onPlacementUpdated && onError);

  // Édition de la SALLE seule (retour utilisateur 28/08/2026 : « on va
  // vouloir sur la vue promo modifier uniquement les salles ») — même
  // condition d'activation que le glisser-déposer : réservé au contexte
  // d'édition (onglet Vue Promo), jamais dans la Vue Promo intégrée à
  // « À placer », qui ne reçoit pas ces props.
  const [salleEnEdition, setSalleEnEdition] = useState<string | null>(null);
  const [salleEnCours, setSalleEnCours] = useState(false);
  const roomEditEnabled = Boolean(onPlacementUpdated && onError);
  // Séance pour laquelle on est en train de créer une salle — la salle
  // créée lui est appliquée directement, sans re-sélection manuelle.
  const [creationSallePour, setCreationSallePour] = useState<string | null>(null);
  const sallesTriees = useMemo(
    () => [...payload.rooms].sort((a, b) => a.label.localeCompare(b.label, "fr")),
    [payload.rooms],
  );

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
        const titre = detail.hard_conflicts.length ? "Salle déjà occupée" : "Attention à la capacité";
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
    const allParcoursList = [...new Set(Object.values(payload.groupParcours))].sort(compareParcoursForDisplay);

    const groups = allParcoursList
      .map((pc) => {
        const tpIds = allGroupIds.filter((gid) => payload.groupParcours[gid] === pc && payload.groupKind[gid] === "tp");
        const leaf = tpIds.length
          ? tpIds
          : allGroupIds.filter((gid) => payload.groupParcours[gid] === pc && payload.groupKind[gid] !== "promo");
        return {
          parcours: pc,
          cols: leaf.sort((a, b) => (payload.groupLabels[a] ?? a).localeCompare(payload.groupLabels[b] ?? b, "fr")),
        };
      })
      .filter((g) => g.cols.length);

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
      onPlaced?.();
    } else {
      setErreurPlacement(resultat.message);
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
    <section className="view">
      <p role="status" aria-live="polite" className="sr-only">
        {annonce}
      </p>

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
          <button type="button" className="btn btn--ghost btn--sm" onClick={onAnnulerPlacement}>
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
          <WeekBar weekRows={payload.weekRows} countByWeekIndex={countByWeek} selected={displayWeek} onSelect={setDisplayWeek} />
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
      </div>

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

                        // Cellule cible pour un placement en cours — seules les
                        // colonnes du BON parcours sont proposées (le solveur
                        // n'affecte jamais une séance en dehors du sien, offrir
                        // les autres colonnes serait juste un clic pour rien).
                        const eligible = Boolean(placementActif) && colParcours[i] === placementActif?.parcours;
                        const cleCellule = `${solverWeek}-${day}-${s}`;
                        const placementProps = eligible
                          ? {
                              role: "button" as const,
                              tabIndex: 0,
                              onClick: () => void placerIci(s),
                              onKeyDown: (e: ReactKeyboardEvent) => {
                                if (e.key === "Enter" || e.key === " ") {
                                  e.preventDefault();
                                  void placerIci(s);
                                }
                              },
                            }
                          : {};
                        const eligibleClass = eligible ? " promocell--placeable" : "";
                        const isDropHover = dragEnabled && dropTarget?.day === day && dropTarget?.slot === s;
                        const dropCls = isDropHover ? " dropzone-hover" : "";

                        if (entries.length) {
                          return (
                            <td
                              key={c}
                              className={cellClass + eligibleClass + dropCls}
                              {...placementProps}
                              {...dropHandlers(day, s)}
                            >
                              {eligible && (
                                <div className="promocell-poser">
                                  {enCoursPlacement === cleCellule ? "Placement…" : "+ poser ici (conflit possible)"}
                                </div>
                              )}
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
                                        defaultValue={sallesTriees.find((s2) => s2.label === r.r)?.id ?? ""}
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
                                        className={`rm promo-chip-salle-btn${r.r ? "" : " rm--absente"}`}
                                        title="Changer la salle"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          setSalleEnEdition(cleEditionSalle);
                                        }}
                                        onMouseDown={(e) => e.stopPropagation()}
                                      >
                                        {r.r || "salle à définir"}
                                      </button>
                                    ) : (
                                      <span className={`rm${r.r ? "" : " rm--absente"}`}>
                                        {r.r || "salle à définir"}
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
                            <td key={c} className={cellClass}>
                              <div className="sessiongrid-holiday">
                                <span className="title">{holiday.kind === "vacances" ? "Vacances" : "Férié"}</span>
                                <span className="label">{holiday.label}</span>
                              </div>
                            </td>
                          );
                        }
                        if (sae) {
                          return (
                            <td key={c} className={cellClass}>
                              <div className="sessiongrid-sae">
                                <span className="title">SAE</span>
                                <span className="codes">{sae.codes.join(", ")}</span>
                              </div>
                            </td>
                          );
                        }
                        if (eventsAtSlot.length) {
                          return (
                            <td key={c} className={cellClass}>
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
                            <td key={c} className={cellClass}>
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
                            className={cellClass + eligibleClass + dropCls}
                            {...placementProps}
                            {...dropHandlers(day, s)}
                          >
                            {eligible && (
                              <div className="promocell-poser">
                                {enCoursPlacement === cleCellule ? "Placement…" : "+ poser ici"}
                              </div>
                            )}
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
          onClose={() => setParcoursOuvert(null)}
          onPlacementUpdated={onPlacementUpdated}
          onError={onError}
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
    </section>
  );
}
