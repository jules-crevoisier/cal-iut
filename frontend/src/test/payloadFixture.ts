/**
 * Fixtures de payload pour les tests de contrat (recherche, fiches, à traiter).
 * Pas de données de production — catalogues minimaux, champs requis remplis.
 */
import type { Route } from "../hooks/useHashRoute";
import type {
  AppPayload,
  AppRow,
  CourseCatalogEntry,
  RoomCatalogEntry,
  TeacherInfo,
} from "../types/app";

export function testRoute(patch: Record<string, unknown> = {}): Route {
  return {
    vue: "",
    prof: "",
    groupe: "",
    salle: "",
    cours: "",
    panel: "",
    sem: null,
    jour: null,
    mode: "",
    t: "",
    ...patch,
  } as Route;
}

export function emptyPayload(overrides: Partial<AppPayload> = {}): AppPayload {
  return {
    status: "ok",
    objective: null,
    quality: null,
    groupLabels: {},
    groupKind: {},
    groupCohort: {},
    groupTpPair: {},
    groupIsFc: {},
    groupParcours: {},
    weekLabels: ["S1"],
    weekDates: ["2026-01-05"],
    weekRows: [{ monday: "2026-01-05", label: "S1", blocked: false, weekIndex: 0 }],
    weekStatus: [{ week: 0, status: "current" }],
    defaultGroup: null,
    rows: [],
    saeRows: [],
    holidayRows: [],
    eventRows: [],
    eventSlotRows: [],
    exceptions: [],
    teachers: [],
    teacherLabels: {},
    teacherEmails: {},
    teacherTokens: {},
    groupTokens: {},
    ruleChecks: [],
    institutionalCalendar: [],
    rooms: [],
    courses: [],
    ...overrides,
  };
}

export function catalogCourse(
  code: string,
  name: string,
  extras: Partial<CourseCatalogEntry> = {},
): CourseCatalogEntry {
  return {
    code,
    name,
    semestre: "S1",
    parcours: "BUT1",
    nCM: 0,
    nTD: 0,
    nTP: 0,
    nEval: 0,
    progressionDefined: false,
    teachers: [],
    ordonnancement: [],
    nPlaced: 0,
    ...extras,
  };
}

export function catalogRoom(
  id: string,
  extras: Partial<RoomCatalogEntry> = {},
): RoomCatalogEntry {
  return {
    id,
    label: id,
    capacity: 28,
    type: "TD",
    equipment: [],
    nSessions: 0,
    ...extras,
  };
}

export function catalogTeacher(
  code: string,
  name: string,
  extras: Partial<TeacherInfo> = {},
): TeacherInfo {
  return {
    code,
    name,
    rawIndisponibilites: "",
    rawDisponibilites: "",
    rawContraintes: "",
    forbiddenSlots: [],
    forbiddenDates: [],
    nPlaced: 0,
    violations: [],
    hasConstraint: false,
    ...extras,
  };
}

export function placedRow(partial: Partial<AppRow> & Pick<AppRow, "id">): AppRow {
  return {
    w: 0,
    d: 0,
    s: 0,
    c: "XX000",
    n: "Cours",
    t: "CM",
    g: [],
    te: [],
    r: "A100",
    ev: false,
    dur: 1,
    locked: false,
    custom: false,
    ...partial,
  };
}
