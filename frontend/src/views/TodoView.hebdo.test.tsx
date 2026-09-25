/**
 * Section « Contrôle hebdomadaire » de l'écran « À traiter » (Jules
 * Crevoisier, 25/09/2026, dicté : « on veut faire quelque chose qui
 * vérifie chaque semaine [...] »). Le filet tourne côté serveur sans écran
 * (`api/controle_doublons_hebdo.py`) ; cette section n'affiche que son
 * dernier résultat (`GET /controles/doublons/hebdo`) et permet de le
 * déclencher à la demande (`POST`, bouton « Vérifier maintenant »).
 *
 * Mock `fetch` DISTINCT de `TodoView.doublons.test.tsx` : cette suite
 * distingue explicitement `/controles/doublons` (liste à la demande, section
 * existante) de `/controles/doublons/hebdo` (ce contrôle), pour ne pas
 * confondre les deux réponses — contrairement au mock générique de l'autre
 * fichier (préfixe partagé), sans conséquence là-bas puisqu'il ne teste pas
 * cette section.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Doublon, DoublonHebdoRun } from "../api/client";
import { emptyPayload } from "../test/payloadFixture";
import { TodoView } from "./TodoView";

const payload = emptyPayload({
  weekLabels: ["Semaine 1"],
  weekDates: ["2026-09-28"],
});

function doublon(overrides: Partial<Doublon> = {}): Doublon {
  return {
    semaine: 0,
    jour: 3,
    creneau: 3,
    type: "salle",
    ressource: "H.201 / H.203",
    seances: [
      { session_id: "a", course_code: "WR101", groupes: ["g1"], salle: "H.201", enseignants: ["MRI"] },
      { session_id: "b", course_code: "WR205", groupes: ["g2"], salle: "H.203", enseignants: ["AUT"] },
    ],
    ...overrides,
  };
}

function run(overrides: Partial<DoublonHebdoRun> = {}): DoublonHebdoRun {
  return {
    date: "2026-09-25",
    semaine_iso: "2026-W39",
    genere_le: "2026-09-25T08:00:00+00:00",
    total: 1,
    par_type: { salle: 1 },
    doublons: [doublon()],
    nouveaux: [],
    resolus: [],
    premier_controle: false,
    ...overrides,
  };
}

function stubFetch(opts: { liste?: Doublon[]; hebdo?: DoublonHebdoRun | null; postHebdo?: DoublonHebdoRun }) {
  const liste = opts.liste ?? [doublon()];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.startsWith("/controles/doublons/hebdo")) {
        if (init?.method === "POST") {
          return Promise.resolve({ ok: true, json: async () => opts.postHebdo ?? run() });
        }
        return Promise.resolve({ ok: true, json: async () => ({ dernier: opts.hebdo ?? null }) });
      }
      if (u.startsWith("/controles/doublons")) {
        return Promise.resolve({ ok: true, json: async () => ({ doublons: liste }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    }),
  );
}

describe("TodoView — contrôle hebdomadaire des doublons", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("says plainly the control has never run, and still offers to run it now", async () => {
    stubFetch({ hebdo: null });
    render(<TodoView payload={payload} setRoute={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/jamais/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Vérifier maintenant" })).toBeInTheDocument();
  });

  it("shows the summary line with date, total and new-since-previous count", async () => {
    stubFetch({ hebdo: run({ total: 111, nouveaux: [doublon(), doublon(), doublon(), doublon()] }) });
    render(<TodoView payload={payload} setRoute={vi.fn()} />);

    await waitFor(() =>
      expect(
        screen.getByText("Contrôle du 25/09/2026 : 111 doublons — 4 nouveaux depuis le contrôle précédent"),
      ).toBeInTheDocument(),
    );
  });

  it("marks a doublon present in `nouveaux` as new in the per-week list", async () => {
    const nouveau = doublon({ semaine: 0, jour: 3, creneau: 3, ressource: "H.201 / H.203" });
    stubFetch({ liste: [nouveau], hebdo: run({ nouveaux: [nouveau] }) });
    render(<TodoView payload={payload} setRoute={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("H.201 / H.203")).toBeInTheDocument());
    expect(screen.getByText("nouveau")).toBeInTheDocument();
  });

  it("does not mark a doublon absent from `nouveaux`", async () => {
    const ancien = doublon({ ressource: "H.201 / H.203" });
    stubFetch({ liste: [ancien], hebdo: run({ nouveaux: [] }) });
    render(<TodoView payload={payload} setRoute={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("H.201 / H.203")).toBeInTheDocument());
    expect(screen.queryByText("nouveau")).not.toBeInTheDocument();
  });

  it("re-runs the check on demand and refreshes the summary line", async () => {
    stubFetch({
      hebdo: run({ date: "2026-09-18", total: 3, nouveaux: [] }),
      postHebdo: run({ date: "2026-09-25", total: 5, nouveaux: [doublon()] }),
    });
    render(<TodoView payload={payload} setRoute={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Contrôle du 18/09/2026 : 3 doublons")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Vérifier maintenant" }));

    await waitFor(() =>
      expect(
        screen.getByText("Contrôle du 25/09/2026 : 5 doublons — 1 nouveau depuis le contrôle précédent"),
      ).toBeInTheDocument(),
    );
  });
});
