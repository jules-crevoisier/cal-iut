/**
 * Vue Semaine (refonte du 29/09/2026) : navigation de semaine, détail de
 * séance, modifications depuis la génération — libellés de la GRILLE
 * (« Semaine 6 »), jamais l'index interne du solveur (« S1 »).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DiffResponse, Placement } from "../types";
import { DiffPanel } from "./DiffPanel";
import { SessionPanel } from "./SessionPanel";
import { Toolbar } from "./Toolbar";
import { WeekStepper } from "./WeekStepper";

vi.mock("../utils/confirmDialog", () => ({
  confirmAsync: vi.fn().mockResolvedValue(false),
}));

// Deux semaines de vacances décalent la grille de l'index solveur : l'index 1
// s'appelle « Semaine 9 ».
const weekRows = [
  { monday: "2026-10-05", label: "Semaine 7 (5–9 oct. 2026)", blocked: false, weekIndex: 0 },
  { monday: "2026-10-19", label: "Semaine 9 (19–23 oct. 2026)", blocked: true, weekIndex: null },
  { monday: "2026-11-02", label: "Semaine 11 (2–6 nov. 2026)", blocked: false, weekIndex: 1 },
];

describe("WeekStepper", () => {
  it("should step to the previous and next week and disable at the ends", () => {
    const onSelect = vi.fn();
    const { rerender } = render(<WeekStepper weekRows={weekRows} selected={0} onSelect={onSelect} />);
    expect(screen.getByRole("button", { name: "Semaine précédente" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Semaine suivante" }));
    expect(onSelect).toHaveBeenCalledWith(1);
    rerender(<WeekStepper weekRows={weekRows} selected={2} onSelect={onSelect} />);
    expect(screen.getByRole("button", { name: "Semaine suivante" })).toBeDisabled();
    expect(screen.getByRole("heading", { name: /semaine 11 \(2–6 nov\. 2026\) · semaine calendaire 45/i })).toBeInTheDocument();
  });

  it("should say when the displayed week is a holiday", () => {
    render(<WeekStepper weekRows={weekRows} selected={1} onSelect={vi.fn()} />);
    expect(screen.getByRole("heading", { name: /vacances/i })).toBeInTheDocument();
  });
});

const diff: DiffResponse = {
  run_id: 1,
  total: 100,
  changed_count: 2,
  entries: [
    { session_id: "a", course_code: "WR101", solver_week: 1, solver_day: 2, solver_slot: 0, current_week: 1, current_day: 2, current_slot: 2, changed: true, locked: false },
    { session_id: "b", course_code: "WR102", solver_week: 0, solver_day: 0, solver_slot: 0, current_week: 1, current_day: 1, current_slot: 3, changed: true, locked: true },
  ],
} as DiffResponse;

describe("DiffPanel", () => {
  const props = {
    diff,
    analysis: null,
    onApplyFeedback: vi.fn(),
    onExportCsv: vi.fn(),
    onExportJson: vi.fn(),
    loading: false,
    weekRows,
  };

  it("should name weeks with the grid labels, not the solver index", () => {
    render(<DiffPanel {...props} />);
    expect(screen.getByText("mer. 8h → mer. 11h")).toBeInTheDocument();
    expect(screen.getByText("Semaine 11")).toBeInTheDocument();
    expect(screen.getByText("Semaine 7 lun. 8h → Semaine 11 mar. 14h")).toBeInTheDocument();
    expect(screen.queryByText(/S2 /)).not.toBeInTheDocument();
  });

  it("should jump to the week of a change when it is clicked", () => {
    const onAllerSemaine = vi.fn();
    render(<DiffPanel {...props} onAllerSemaine={onAllerSemaine} />);
    fireEvent.click(screen.getByRole("button", { name: /WR101/ }));
    expect(onAllerSemaine).toHaveBeenCalledWith(2);
  });

  it("should explain the learning in plain words", () => {
    render(
      <DiffPanel
        {...props}
        analysis={{ patterns: [], suggestions: { gap_penalty: 150 }, top_courses: [], top_teachers: [], total_corrections: 3 } as never}
      />,
    );
    expect(screen.getByText(/éviter les trous dans les journées : \+150/)).toBeInTheDocument();
    expect(screen.queryByText(/gap_penalty/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ajuster la génération" })).toBeInTheDocument();
  });
});

const seance: Placement = {
  session_id: "s1",
  week: 1,
  day: 2,
  slot: 1,
  course_code: "WR105",
  course_name: "Stratégies de communication",
  session_type: "CM",
  group_ids: ["but1-promo"],
  teacher_codes: ["JLE"],
  room_id: "h018",
  room_label: "H.018 (Amphi MMI)",
  is_eval: false,
  locked: false,
  duration_slots: 1,
};

describe("SessionPanel", () => {
  const base = {
    onClose: vi.fn(),
    onUpdated: vi.fn(),
    onError: vi.fn(),
    weekRows,
    weekDates: ["2026-10-05", "2026-11-02"],
    groupLabels: { "but1-promo": "Promo BUT1" },
    teacherLabels: { JLE: "JOAN LEFEVRE" },
  };

  it("should invite to click a session when none is selected", () => {
    render(<SessionPanel {...base} placement={null} />);
    expect(screen.getByText(/cliquez une séance/i)).toBeInTheDocument();
  });

  it("should show readable labels: grid week, date, group and teacher names", () => {
    render(<SessionPanel {...base} placement={seance} />);
    expect(screen.getByText("Semaine 11 (2–6 nov. 2026)")).toBeInTheDocument();
    expect(screen.getByText(/Mercredi 4 nov\., 9h30–11h/)).toBeInTheDocument();
    expect(screen.getByText("Promo BUT1")).toBeInTheDocument();
    expect(screen.getByText("Joan Lefevre")).toBeInTheDocument();
  });

  it("should open the Vue Promo on the session's week and day", () => {
    const onOuvrirPromo = vi.fn();
    render(<SessionPanel {...base} placement={seance} onOuvrirPromo={onOuvrirPromo} />);
    fireEvent.click(screen.getByRole("button", { name: "Modifier dans la Vue Promo" }));
    expect(onOuvrirPromo).toHaveBeenCalledWith(seance);
  });

  it("should ask before locking (it cannot be undone from the interface)", async () => {
    const { confirmAsync } = await import("../utils/confirmDialog");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<SessionPanel {...base} placement={seance} />);
    fireEvent.click(screen.getByRole("button", { name: "Verrouiller ce créneau" }));
    await waitFor(() => expect(confirmAsync).toHaveBeenCalled());
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});

describe("Toolbar de la Vue Semaine", () => {
  const props = {
    year: 1,
    parcours: "BUT1",
    years: [{ id: 1, label: "1re année (S1–S2)", semestres: ["S1", "S2"], parcours: ["BUT1"] }],
    parcoursList: ["BUT1"],
    displayWeek: 0,
    maxWeeks: 24,
    weekRows,
    weekCounts: new Map<number, number>(),
    viewMode: "group" as const,
    groupId: "",
    teacherCode: "",
    roomId: "",
    groups: [],
    teachers: ["JLE"],
    rooms: [],
    loading: false,
    couleursParMatiere: false,
    onYearChange: vi.fn(),
    onParcoursChange: vi.fn(),
    onViewModeChange: vi.fn(),
    onCouleursChange: vi.fn(),
    onGroupChange: vi.fn(),
    onTeacherChange: vi.fn(),
    onRoomChange: vi.fn(),
  };

  it("should change week with Maj + → and ignore the shortcut inside a field", () => {
    const onWeekChange = vi.fn();
    render(<Toolbar {...props} onWeekChange={onWeekChange} />);
    fireEvent.keyDown(document.body, { key: "ArrowRight", shiftKey: true });
    expect(onWeekChange).toHaveBeenCalledWith(1);
    onWeekChange.mockClear();
    fireEvent.keyDown(screen.getByLabelText("Parcours"), { key: "ArrowRight", shiftKey: true });
    expect(onWeekChange).not.toHaveBeenCalled();
  });

  it("should offer the display modes as pressed buttons and hide the useless Semestre select", () => {
    const onViewModeChange = vi.fn();
    render(<Toolbar {...props} onWeekChange={vi.fn()} onViewModeChange={onViewModeChange} />);
    expect(screen.getByRole("button", { name: "Groupe" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Enseignant" }));
    expect(onViewModeChange).toHaveBeenCalledWith("teacher");
    expect(screen.queryByLabelText("Semestre")).not.toBeInTheDocument();
  });

  it("should show teacher names, not only codes, in teacher mode", () => {
    render(
      <Toolbar {...props} viewMode="teacher" teacherLabels={{ JLE: "JOAN LEFEVRE" }} onWeekChange={vi.fn()} />,
    );
    expect(screen.getByRole("option", { name: "Joan Lefevre (JLE)" })).toBeInTheDocument();
  });
});
