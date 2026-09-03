import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Placement } from "../../types";
import type { ParkedSession } from "./parkWeekMove";
import { ParkedCard } from "./ParkedCard";

function parked(overrides: Partial<Placement> = {}): ParkedSession {
  const origin: Placement = {
    session_id: "s1",
    week: 3,
    day: 1,
    slot: 2,
    course_code: "WR118",
    course_name: "Économie, gestion et droit du numérique",
    session_type: "TD",
    group_ids: ["g-td-ab"],
    teacher_codes: [],
    room_id: "h104",
    room_label: "H.104",
    is_eval: false,
    locked: false,
    duration_slots: 1,
    ...overrides,
  };
  return { sessionId: origin.session_id, origin, viaDisplayWeek: null };
}

describe("ParkedCard", () => {
  it("should show the concerned group when group labels are given", () => {
    // Retour utilisateur (03/09/2026) : impossible de savoir, sur cette
    // carte, à quel groupe (TD AB, TP C…) la séance parquée appartenait.
    render(
      <ParkedCard
        parked={parked()}
        selected={false}
        onSelect={vi.fn()}
        onAnnuler={vi.fn()}
        groupLabels={{ "g-td-ab": "TD AB" }}
      />,
    );
    expect(screen.getByText(/AB/)).toBeInTheDocument();
  });

  it("should still render without throwing when no group labels are given", () => {
    render(<ParkedCard parked={parked()} selected={false} onSelect={vi.fn()} onAnnuler={vi.fn()} />);
    expect(screen.getByText(/cliquez puis une case de la grille/i)).toBeInTheDocument();
  });
});
