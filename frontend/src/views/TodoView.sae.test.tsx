/**
 * « À traiter » : les cours de SAE hors journée SAE (liste `anomalies` de
 * `GET /api/v1/sae`) ont leur tuile et leur section, et chaque ligne ouvre
 * la Vue Promo au bon jour (29/09/2026).
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { emptyPayload } from "../test/payloadFixture";
import { TodoView } from "./TodoView";

const payload = emptyPayload({
  weekLabels: ["Semaine A"],
  weekDates: ["2026-10-19"],
  weekRows: [{ monday: "2026-10-19", label: "Semaine A", blocked: false, weekIndex: 0 }],
  weekStatus: [{ week: 0, status: "current" }],
});

const ANOMALIE = {
  id: "ws-hors", cours_code: "WS101", cours_nom: "SAE WS101", type: "TD", parcours: "BUT1",
  groupes: ["but1-td-ab"], groupes_libelles: ["TD AB"], enseignants: ["KBR"], semaine: 0, jour: 0, creneau: 0,
};

function stubFetch(anomalies: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const u = String(url);
      const ok = (corps: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => corps });
      if (u.startsWith("/api/v1/sae")) return ok({ anomalies });
      if (u.startsWith("/controles/doublons/hebdo")) return ok({ dernier: null });
      if (u.startsWith("/controles/doublons")) return ok({ doublons: [] });
      return ok({});
    }),
  );
}

describe("TodoView — cours de SAE hors journée SAE", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("compte l'anomalie dans sa tuile et ouvre la Vue Promo au bon jour", async () => {
    stubFetch([ANOMALIE]);
    const setRoute = vi.fn();
    render(<TodoView payload={payload} setRoute={setRoute} />);
    const tuile = screen.getByRole("button", { name: /^SAE hors journée/ });
    await waitFor(() => expect(within(tuile).getByText("1")).toBeInTheDocument());
    const section = screen.getByRole("heading", { name: "Cours de SAE hors journée SAE" }).closest("section")!;
    fireEvent.click(within(section).getByText("WS101 — SAE WS101"));
    expect(setRoute).toHaveBeenCalledWith({ vue: "promo", sem: 0, jour: 0, parcours: "BUT1" });
  });

  it("une réponse inattendue ne casse rien : section vide", async () => {
    stubFetch(undefined);
    render(<TodoView payload={payload} setRoute={vi.fn()} />);
    const section = screen.getByRole("heading", { name: "Cours de SAE hors journée SAE" }).closest("section")!;
    await waitFor(() => expect(within(section).getByText("Rien à signaler.")).toBeInTheDocument());
  });
});
