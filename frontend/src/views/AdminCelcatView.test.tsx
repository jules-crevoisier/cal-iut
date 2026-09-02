/**
 * Onglet Administration Celcat — interrupteur, semaines, Valider, extras, logs.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminCelcatView } from "./AdminCelcatView";

const ETAT = {
  saisie_active: false,
  semaines_validees: [1],
  valide_le: "2026-09-01T10:00:00+00:00",
  dernier_job: null,
  compteurs: { created: 1, modified: 0, deleted: 0, blocked: 1 },
  worker_ok: true,
};

const EXTRAS = [
  {
    id: "extra-1",
    statut: "ouvert",
    course_code: "WR106",
    libelle: "WR106 Expression Comm.",
    event_id: 1931666,
  },
];

const LOGS = {
  items: [
    { kind: "created", motif: null, session_id: "s-a" },
    { kind: "blocked", motif: "WR314D sans code Celcat", session_id: "s-d" },
  ],
  cursor: null,
};

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const cible = String(url);
      if (cible.includes("/celcat/extras")) {
        return Promise.resolve({ ok: true, json: async () => ({ extras: EXTRAS }) });
      }
      if (cible.includes("/celcat/logs")) {
        return Promise.resolve({ ok: true, json: async () => LOGS });
      }
      return Promise.resolve({ ok: true, json: async () => ETAT });
    }),
  );
}

describe("AdminCelcatView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("should render toggle, week multi-select, Valider, extras list, logs", async () => {
    stubFetch();
    render(<AdminCelcatView />);

    await waitFor(() => expect(screen.getByLabelText(/saisie/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /valider/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/semaine 1/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/semaine 2/i)).toBeInTheDocument();
    expect(screen.getByText(/WR106/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ajouter/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ignorer/i })).toBeInTheDocument();
    expect(screen.getByText(/WR314D/)).toBeInTheDocument();
    expect(screen.getByText(/sans code Celcat/i)).toBeInTheDocument();
  });
});
