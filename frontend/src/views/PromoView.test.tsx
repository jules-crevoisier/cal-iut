/**
 * Contrat `readOnly` de Vue Promo — retour utilisateur 31/08/2026 : « un
 * lien en plus ouvert à tout le monde [...] accès à la vue promo ».
 *
 * `readOnly` doit couper TOUTE écriture, y compris le panneau « Séances à
 * placer » et le clic-pour-placer, qui ne dépendaient auparavant que de
 * `placementActif` — jamais vérifiés contre la présence des callbacks
 * d'édition (`placements`/`onPlacementUpdated`/`onError`). Un lien public
 * qui ne les fournit pas était donc déjà protégé sur le papier, mais
 * seulement PAR OMISSION : si un futur appel les passait quand même à côté
 * de `readOnly`, rien ne les aurait empêchés de s'exécuter. Le dernier test
 * ci-dessous couvre exactement ce cas.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PromoView } from "./PromoView";
import type { Placement } from "../types";
import type { AppRow } from "../types/app";
import { catalogCourse, emptyPayload, placedRow, testRoute } from "../test/payloadFixture";

const payload = emptyPayload({
  groupLabels: { "but1-td-ab": "TD AB" },
  groupParcours: { "but1-td-ab": "BUT1" },
});

describe("PromoView readOnly", () => {
  it("should show the édition controls when editing callbacks are provided and readOnly is absent", () => {
    render(
      <PromoView
        payload={payload}
        route={testRoute({ vue: "promo" })}
        placements={[]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /nouvelle séance/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /séances à placer/i })).toBeInTheDocument();
  });

  it("should hide every write control when readOnly is set and no editing callback is provided", () => {
    render(<PromoView payload={payload} route={testRoute({ vue: "promo" })} readOnly />);
    expect(screen.queryByRole("button", { name: /nouvelle séance/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /séances à placer/i })).not.toBeInTheDocument();
  });

  it("should hide every write control when readOnly is set EVEN IF editing callbacks are also passed", () => {
    // Garde-fou : readOnly doit primer, pas seulement l'absence des callbacks.
    render(
      <PromoView
        payload={payload}
        route={testRoute({ vue: "promo" })}
        readOnly
        placements={[]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
        onAPlacerRefresh={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /nouvelle séance/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /séances à placer/i })).not.toBeInTheDocument();
  });
});

function placementPour(id: string): Placement {
  return {
    session_id: id,
    week: 0,
    day: 0,
    slot: 0,
    course_code: "WR101",
    course_name: "Cours",
    session_type: "TD",
    group_ids: ["but1-td-ab"],
    teacher_codes: ["MRI"],
    room_id: null,
    room_label: null,
    is_eval: false,
    locked: false,
    duration_slots: 1,
  };
}

const payloadAvecChips = emptyPayload({
  groupLabels: { "but1-td-ab": "TD AB" },
  groupParcours: { "but1-td-ab": "BUT1" },
  groupKind: { "but1-td-ab": "td" },
  groupCohort: { "but1-td-ab": ["but1-td-ab"] },
  rows: [
    placedRow({ id: "maquette-1", w: 0, d: 0, s: 0, c: "WR101", g: ["but1-td-ab"], custom: false }),
    placedRow({ id: "custom-1", w: 0, d: 0, s: 1, c: "WR102", g: ["but1-td-ab"], custom: true }),
  ],
});

const propsEdition = {
  payload: payloadAvecChips,
  route: testRoute({ vue: "promo", jour: 0, sem: 0 }),
  placements: [placementPour("maquette-1"), placementPour("custom-1")],
  onPlacementUpdated: vi.fn(),
  onError: vi.fn(),
  setRoute: vi.fn(),
};

describe("PromoView chip edit actions", () => {
  it("should show the edit pencil on a non-custom chip when not readOnly", () => {
    render(
      <PromoView
        payload={emptyPayload({
          groupLabels: { "but1-td-ab": "TD AB" },
          groupParcours: { "but1-td-ab": "BUT1" },
          groupKind: { "but1-td-ab": "td" },
          groupCohort: { "but1-td-ab": ["but1-td-ab"] },
          rows: [placedRow({ id: "maquette-1", w: 0, d: 0, s: 0, c: "WR101", g: ["but1-td-ab"], custom: false })],
        })}
        route={testRoute({ vue: "promo", jour: 0, sem: 0 })}
        placements={[placementPour("maquette-1")]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.getByTitle("Modifier cette séance")).toBeInTheDocument();
  });

  it("should hide delete on a non-custom chip when not readOnly", () => {
    render(
      <PromoView
        payload={emptyPayload({
          groupLabels: { "but1-td-ab": "TD AB" },
          groupParcours: { "but1-td-ab": "BUT1" },
          groupKind: { "but1-td-ab": "td" },
          groupCohort: { "but1-td-ab": ["but1-td-ab"] },
          rows: [placedRow({ id: "maquette-1", w: 0, d: 0, s: 0, c: "WR101", g: ["but1-td-ab"], custom: false })],
        })}
        route={testRoute({ vue: "promo", jour: 0, sem: 0 })}
        placements={[placementPour("maquette-1")]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.queryByTitle("Supprimer cette séance")).not.toBeInTheDocument();
  });

  it("should show delete only on a custom chip when not readOnly", () => {
    render(<PromoView {...propsEdition} />);
    expect(screen.getByTitle("Supprimer cette séance")).toBeInTheDocument();
  });

  it("should hide both pencil and trash when readOnly even if editing callbacks are passed", () => {
    render(<PromoView {...propsEdition} readOnly />);
    expect(screen.queryByTitle("Modifier cette séance")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Supprimer cette séance")).not.toBeInTheDocument();
  });

  it("should hide pencil when Vue Promo is readOnly", () => {
    render(
      <PromoView
        payload={emptyPayload({
          groupLabels: { "but1-td-ab": "TD AB" },
          groupParcours: { "but1-td-ab": "BUT1" },
          groupKind: { "but1-td-ab": "td" },
          groupCohort: { "but1-td-ab": ["but1-td-ab"] },
          rows: [placedRow({ id: "maquette-1", w: 0, d: 0, s: 0, c: "WR101", g: ["but1-td-ab"], custom: false })],
        })}
        route={testRoute({ vue: "promo", jour: 0, sem: 0 })}
        readOnly
        placements={[placementPour("maquette-1")]}
        onPlacementUpdated={vi.fn()}
        onError={vi.fn()}
        setRoute={vi.fn()}
      />,
    );
    expect(screen.queryByTitle("Modifier cette séance")).not.toBeInTheDocument();
    expect(screen.queryByText("✎")).not.toBeInTheDocument();
  });
});

const payloadCrayon = emptyPayload({
  groupLabels: { "but1-td-ab": "TD AB" },
  groupParcours: { "but1-td-ab": "BUT1" },
  groupKind: { "but1-td-ab": "td" },
  groupCohort: { "but1-td-ab": ["but1-td-ab"] },
  courses: [catalogCourse("WR101", "Cours existant", { parcours: "BUT1" })],
  teacherLabels: { MRI: "Riguet Marine" },
  rooms: [{ id: "h005", label: "H.005", capacity: 30, type: "standard", equipment: [], nSessions: 0 }],
  weekRows: [
    { monday: "2026-01-05", label: "S1", blocked: false, weekIndex: 0 },
    { monday: "2026-01-12", label: "S2", blocked: false, weekIndex: 1 },
  ],
  rows: [placedRow({ id: "maquette-1", w: 0, d: 0, s: 0, c: "WR101", g: ["but1-td-ab"], te: ["MRI"], r: "A100", custom: false })],
});

function PromoCrayon() {
  const [placements, setPlacements] = useState<Placement[]>([placementPour("maquette-1")]);
  const [rows, setRows] = useState<AppRow[]>(payloadCrayon.rows);
  return (
    <PromoView
      payload={{ ...payloadCrayon, rows }}
      route={testRoute({ vue: "promo", jour: 0, sem: 0 })}
      placements={placements}
      onPlacementUpdated={(p) => {
        setPlacements([p]);
        setRows((prev) =>
          prev.map((row) =>
            row.id === p.session_id
              ? { ...row, t: p.session_type, r: p.room_label ?? row.r, te: p.teacher_codes }
              : row,
          ),
        );
      }}
      onError={vi.fn()}
      setRoute={vi.fn()}
    />
  );
}

describe("PromoView pencil opens CreerSeanceModal", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("should open CreerSeanceModal prefilled from the chip when pencil is clicked on Vue Promo", () => {
    render(<PromoCrayon />);
    fireEvent.click(screen.getByTitle("Modifier cette séance"));
    expect(screen.getByRole("dialog", { name: /modifier la séance/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Semaine")).toHaveValue("0");
    expect(screen.getByLabelText("Jour")).toHaveValue("0");
    expect(screen.getByLabelText("Créneau")).toHaveValue("0");
    expect(screen.getByLabelText("Type")).toHaveValue("TD");
    expect(screen.getByRole("button", { name: /enregistrer/i })).toBeInTheDocument();
  });

  it("should persist via PATCH /seance and update the chip when Enregistrer succeeds", async () => {
    const maj: Placement = {
      ...placementPour("maquette-1"),
      session_type: "CM",
      room_id: "h005",
      room_label: "H.005",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => maj,
      }),
    );
    render(<PromoCrayon />);
    fireEvent.click(screen.getByTitle("Modifier cette séance"));
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "CM" } });
    fireEvent.change(screen.getByLabelText("Salle"), { target: { value: "h005" } });
    fireEvent.click(screen.getByRole("button", { name: /enregistrer/i }));
    await waitFor(() => {
      const appels = vi.mocked(fetch).mock.calls;
      expect(appels.some((call) => String(call[0]).includes("/placements/maquette-1/seance"))).toBe(true);
      expect(appels.some((call) => call[1] && String(call[1].method).toUpperCase() === "PATCH")).toBe(true);
    });
    await waitFor(() => {
      expect(screen.getByText("H.005")).toBeInTheDocument();
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

