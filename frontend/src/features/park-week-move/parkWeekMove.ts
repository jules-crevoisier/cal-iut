/**
 * Parcage visuel d'une séance déjà placée, le temps de cliquer une case
 * sur une autre semaine. Aucun I/O : le POST n'arrive qu'au performMove.
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
  parked: ParkedSession | null;
  selected: boolean;
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

export function createPark(placement: Placement, viaDisplayWeek: number | null): ParkUiState {
  return {
    parked: {
      sessionId: placement.session_id,
      origin: {
        ...placement,
        group_ids: [...placement.group_ids],
        teacher_codes: [...placement.teacher_codes],
      },
      viaDisplayWeek,
    },
    selected: false,
  };
}

export function isHiddenOnGrid(state: ParkUiState, sessionId: string): boolean {
  return state.parked?.sessionId === sessionId;
}

export function clearPark(_state?: ParkUiState): ParkUiState {
  return { parked: null, selected: false };
}

export function selectPark(state: ParkUiState): ParkUiState {
  if (!state.parked) return { parked: null, selected: false };
  return { parked: state.parked, selected: true };
}

export function replacePark(
  _state: ParkUiState,
  placement: Placement,
  viaDisplayWeek: number | null,
): ParkUiState {
  return createPark(placement, viaDisplayWeek);
}
