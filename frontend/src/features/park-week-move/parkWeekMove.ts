/**
 * Parcage visuel d'une ou plusieurs séances déjà placées, le temps de
 * cliquer une case sur une autre semaine. Aucun I/O : le POST n'arrive
 * qu'au performMove. File multi depuis 03/09/2026 (brief promo polish).
 */
import type { Placement } from "../../types";
import type { WeekRow } from "../../types/app";

export type ParkDecision = "park" | "navigate" | "refuse";

export interface ParkedSession {
  sessionId: string;
  origin: Placement;
  viaDisplayWeek: number | null;
}

export interface ParkUiState {
  items: ParkedSession[];
  selectedSessionId: string | null;
}

function snapshotPlacement(placement: Placement): Placement {
  return {
    ...placement,
    group_ids: [...placement.group_ids],
    teacher_codes: [...placement.teacher_codes],
  };
}

export function decideWeekDrop(input: {
  placement: Placement | null | undefined;
  target: WeekRow | undefined;
  currentSolverWeek: number | null;
}): ParkDecision {
  const { placement, target } = input;
  if (!placement || placement.locked) return "refuse";
  if (!target || target.blocked || target.weekIndex === null) return "refuse";
  if (target.weekIndex === placement.week) return "navigate";
  return "park";
}

export function emptyPark(): ParkUiState {
  return { items: [], selectedSessionId: null };
}

/** @deprecated alias — préférez `emptyPark`. */
export function clearPark(_state?: ParkUiState): ParkUiState {
  return emptyPark();
}

export function addPark(
  state: ParkUiState,
  placement: Placement,
  viaDisplayWeek: number | null,
): ParkUiState {
  const entry: ParkedSession = {
    sessionId: placement.session_id,
    origin: snapshotPlacement(placement),
    viaDisplayWeek,
  };
  const sansDoublon = state.items.filter((p) => p.sessionId !== entry.sessionId);
  return {
    items: [...sansDoublon, entry],
    selectedSessionId: state.selectedSessionId === entry.sessionId ? entry.sessionId : state.selectedSessionId,
  };
}

/** Premier parcage (file vide) — équivalent historique de createPark. */
export function createPark(placement: Placement, viaDisplayWeek: number | null): ParkUiState {
  return addPark(emptyPark(), placement, viaDisplayWeek);
}

/** Ajoute à la file (ne remplace plus les autres). */
export function replacePark(
  state: ParkUiState,
  placement: Placement,
  viaDisplayWeek: number | null,
): ParkUiState {
  return addPark(state, placement, viaDisplayWeek);
}

export function removePark(state: ParkUiState, sessionId: string): ParkUiState {
  const items = state.items.filter((p) => p.sessionId !== sessionId);
  return {
    items,
    selectedSessionId: state.selectedSessionId === sessionId ? null : state.selectedSessionId,
  };
}

export function isHiddenOnGrid(state: ParkUiState, sessionId: string): boolean {
  return state.items.some((p) => p.sessionId === sessionId);
}

export function selectPark(state: ParkUiState, sessionId?: string): ParkUiState {
  if (state.items.length === 0) return emptyPark();
  const cible = sessionId ?? state.items[state.items.length - 1]?.sessionId;
  if (!cible || !state.items.some((p) => p.sessionId === cible)) {
    return { items: state.items, selectedSessionId: null };
  }
  return { items: state.items, selectedSessionId: cible };
}

export function selectedParked(state: ParkUiState): ParkedSession | null {
  if (!state.selectedSessionId) return null;
  return state.items.find((p) => p.sessionId === state.selectedSessionId) ?? null;
}

export function hasParked(state: ParkUiState): boolean {
  return state.items.length > 0;
}
