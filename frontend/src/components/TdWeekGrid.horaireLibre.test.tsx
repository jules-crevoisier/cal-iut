/**
 * Vue Semaine (`TdWeekGrid`) construit sa grille depuis `Placement`
 * (`/placements`), pas depuis `/app-state` — `hor` (retour Jules
 * 23/09/2026, `PlacementResponse.hor` côté API) doit donc être porté
 * séparément jusqu'ici pour qu'un évènement à horaire libre affiche son
 * heure RÉELLE dans sa case de STOCKAGE (créneau 3).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TdWeekGrid } from "./TdWeekGrid";
import type { GroupMeta, Placement } from "../types";

vi.mock("../utils/preferences", () => ({ usePreferences: () => ({ couleursParMatiere: false }) }));

const GROUPS: GroupMeta[] = [
  { id: "but1-td-ab", label: "TD AB", parcours: "BUT1", kind: "td", related_ids: ["but1-tp-a", "but1-tp-b"] },
];

function placement(over: Partial<Placement> = {}): Placement {
  return {
    session_id: "evenement-1", week: 0, day: 0, slot: 3, course_code: "PRESENTATION-PAC",
    course_name: "Présentation PAC", session_type: "CM", group_ids: ["but1-promo"], teacher_codes: [],
    room_id: null, room_label: null, is_eval: false, locked: false, duration_slots: 1,
    ...over,
  };
}

describe("TdWeekGrid — horaire réel d'un évènement à horaire libre", () => {
  it("affiche `hor` à côté du type de séance quand il est présent", () => {
    render(
      <TdWeekGrid
        placements={[placement({ hor: "13h15–14h" })]}
        displayWeek={0}
        tdGroupId="but1-td-ab"
        groups={GROUPS}
        groupLabels={{}}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByText(/13h15.*14h/)).toBeInTheDocument();
  });

  it("n'affiche rien de plus pour une séance normale, sans `hor`", () => {
    render(
      <TdWeekGrid
        placements={[placement({ session_id: "normal-1", course_code: "WR101", course_name: "Cours normal", session_type: "TD", hor: null })]}
        displayWeek={0}
        tdGroupId="but1-td-ab"
        groups={GROUPS}
        groupLabels={{}}
        onSelect={() => {}}
      />,
    );
    const bloc = screen.getByText("WR101").closest("button");
    expect(bloc?.textContent).toBe("WR101TD · but1-promo");
  });
});
