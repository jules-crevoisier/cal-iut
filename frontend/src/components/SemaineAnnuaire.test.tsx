/**
 * Vue Semaine, gabarit v2 : sans enseignant ni salle choisi, l'annuaire
 * avec les chiffres de la semaine remplace la boîte « Choisissez… ».
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Placement } from "../types";
import { SemaineAnnuaire } from "./SemaineAnnuaire";
import { SessionPanel } from "./SessionPanel";

function seance(patch: Partial<Placement>): Placement {
  return {
    session_id: "s",
    week: 0,
    day: 0,
    slot: 0,
    course_code: "WR101",
    course_name: "Anglais",
    session_type: "TD",
    group_ids: ["but1-td-ab"],
    teacher_codes: ["JLE"],
    room_id: "h101",
    room_label: "H.101",
    is_eval: false,
    locked: false,
    duration_slots: 1,
    ...patch,
  };
}

const semaine = [
  seance({ session_id: "a", teacher_codes: ["JLE"], room_id: "h101" }),
  seance({ session_id: "b", teacher_codes: ["JLE"], room_id: "h101", duration_slots: 2 }),
  seance({ session_id: "c", teacher_codes: ["TPA"], room_id: "h103", session_type: "TP", room_label: null }),
];

const labels = { JLE: "JOAN LEFEVRE", TPA: "THOMAS PAVIE", AHA: "AMINE HARAOUBIA" };

function lignes(): string[] {
  const table = screen.getByRole("table");
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((r) => r.textContent ?? "");
}

describe("SemaineAnnuaire", () => {
  it("should list every teacher with the week's sessions and hours, those without classes included", () => {
    render(
      <SemaineAnnuaire
        genre="enseignant"
        enseignants={["JLE", "TPA", "AHA"]}
        teacherLabels={labels}
        seancesSemaine={semaine}
        onChoisir={vi.fn()}
      />,
    );
    expect(lignes()).toEqual(["Amine HaraoubiaAHA——", "Joan LefevreJLE24,5 h", "Thomas PavieTPA11,5 h"]);
    expect(screen.getByText(/3 enseignants · 2 avec cours cette semaine/)).toBeInTheDocument();
  });

  it("should filter by name or code, sort by hours, and open the chosen teacher", () => {
    const onChoisir = vi.fn();
    render(
      <SemaineAnnuaire
        genre="enseignant"
        enseignants={["JLE", "TPA", "AHA"]}
        teacherLabels={labels}
        seancesSemaine={semaine}
        onChoisir={onChoisir}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Par heures" }));
    expect(lignes()[0]).toMatch(/^Joan Lefevre/);
    fireEvent.change(screen.getByLabelText("Filtrer les enseignants"), { target: { value: "tpa" } });
    expect(lignes()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Thomas Pavie" }));
    expect(onChoisir).toHaveBeenCalledWith("TPA");
  });

  it("should count rooms by their id", () => {
    render(
      <SemaineAnnuaire
        genre="salle"
        salles={[
          { id: "h101", label: "H.101", capacity: 30, room_type: "td", placement_auto: true },
          { id: "h103", label: "H.103", capacity: 16, room_type: "tp", placement_auto: true },
        ]}
        seancesSemaine={semaine}
        onChoisir={vi.fn()}
      />,
    );
    expect(lignes()).toEqual(["H.10130 places24,5 h", "H.10316 places11,5 h"]);
  });
});

describe("SessionPanel sans séance choisie", () => {
  it("should sum up the displayed week instead of an empty box", () => {
    render(
      <SessionPanel
        placement={null}
        onClose={vi.fn()}
        onUpdated={vi.fn()}
        onError={vi.fn()}
        seancesSemaine={semaine}
        portee="BUT1 · TD AB"
      />,
    );
    expect(screen.getByRole("heading", { name: "La semaine en bref" })).toBeInTheDocument();
    expect(screen.getByText("BUT1 · TD AB")).toBeInTheDocument();
    expect(screen.getByText("Séances").nextElementSibling).toHaveTextContent("3");
    expect(screen.getByText("Heures").nextElementSibling).toHaveTextContent("6 h");
    expect(screen.getByText("1 séance sans salle")).toBeInTheDocument();
  });
});
