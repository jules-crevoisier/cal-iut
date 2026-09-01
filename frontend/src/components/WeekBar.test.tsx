/**
 * Légende de la WeekBar : première / sélectionnée / dernière semaine, mais
 * jamais le même libellé affiché deux fois — retour utilisateur 31/08/2026
 * (« revois un peu les espacements ») sur une capture où la semaine
 * sélectionnée ÉTAIT la première : "Semaine 2 ... Semaine 2 ... Semaine 29"
 * se lisait comme un bug d'affichage plutôt qu'une information.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WeekBar } from "./WeekBar";
import type { WeekRow } from "../types/app";

const semaines: WeekRow[] = [
  { monday: "2026-08-31", label: "Semaine 2 (31 août–4 sept. 2026)", blocked: false, weekIndex: 0 },
  { monday: "2026-10-12", label: "Semaine 8 (12–16 oct. 2026)", blocked: false, weekIndex: 6 },
  { monday: "2027-03-08", label: "Semaine 29 (8–12 mars 2027)", blocked: false, weekIndex: 27 },
];

const baseProps = {
  weekRows: semaines,
  countByWeekIndex: new Map<number, number>(),
  onSelect: vi.fn(),
};

describe("WeekBar caption", () => {
  it("should show all three labels once each when the selected week is in the middle", () => {
    render(<WeekBar {...baseProps} selected={1} />);
    expect(screen.getAllByText("Semaine 2 (31 août–4 sept. 2026)")).toHaveLength(1);
    expect(screen.getAllByText("Semaine 8 (12–16 oct. 2026)")).toHaveLength(1);
    expect(screen.getAllByText("Semaine 29 (8–12 mars 2027)")).toHaveLength(1);
  });

  it("should not repeat the first week's label when it is also the selected week", () => {
    render(<WeekBar {...baseProps} selected={0} />);
    expect(screen.getAllByText("Semaine 2 (31 août–4 sept. 2026)")).toHaveLength(1);
    expect(screen.getAllByText("Semaine 29 (8–12 mars 2027)")).toHaveLength(1);
  });

  it("should not repeat the last week's label when it is also the selected week", () => {
    render(<WeekBar {...baseProps} selected={2} />);
    expect(screen.getAllByText("Semaine 2 (31 août–4 sept. 2026)")).toHaveLength(1);
    expect(screen.getAllByText("Semaine 29 (8–12 mars 2027)")).toHaveLength(1);
  });

  it("should show a single label when there is only one week", () => {
    render(<WeekBar {...baseProps} weekRows={[semaines[0]]} selected={0} />);
    expect(screen.getAllByText("Semaine 2 (31 août–4 sept. 2026)")).toHaveLength(1);
  });
});

describe("WeekBar drop onto another week", () => {
  it("should call onDropWeek with the target display index", () => {
    const onDropWeek = vi.fn();
    render(<WeekBar {...baseProps} selected={0} onDropWeek={onDropWeek} />);
    fireEvent.drop(screen.getByRole("button", { name: /semaine 8/i }));
    expect(onDropWeek).toHaveBeenCalledWith(1);
  });

  it("should not fire onDropWeek when the target week is blocked", () => {
    const onDropWeek = vi.fn();
    render(
      <WeekBar
        {...baseProps}
        selected={0}
        onDropWeek={onDropWeek}
        weekRows={[
          semaines[0],
          { monday: "2026-12-21", label: "Vacances de Noël", blocked: true, weekIndex: 12 },
          semaines[1],
        ]}
      />,
    );
    fireEvent.drop(screen.getByRole("button", { name: /vacances/i }));
    expect(onDropWeek).not.toHaveBeenCalled();
  });

  it("should still select another week after a drop on a different week", () => {
    const onDropWeek = vi.fn();
    const onSelect = vi.fn();
    render(
      <WeekBar {...baseProps} selected={0} onSelect={onSelect} onDropWeek={onDropWeek} />,
    );
    fireEvent.drop(screen.getByRole("button", { name: /semaine 8/i }));
    fireEvent.click(screen.getByRole("button", { name: /semaine 29/i }));
    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it("should not fire onDropWeek when the target weekIndex is null", () => {
    const onDropWeek = vi.fn();
    render(
      <WeekBar
        {...baseProps}
        selected={0}
        onDropWeek={onDropWeek}
        weekRows={[
          semaines[0],
          { monday: "2026-12-28", label: "Semaine hors calendrier", blocked: false, weekIndex: null },
          semaines[1],
        ]}
      />,
    );
    fireEvent.drop(screen.getByRole("button", { name: /hors calendrier/i }));
    expect(onDropWeek).not.toHaveBeenCalled();
  });
});


