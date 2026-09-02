/**
 * Onglet Administration Celcat — bandeau Live, 3 étapes, lot de nuit, extras, journal.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminCelcatView } from "./AdminCelcatView";

const ETAT = {
  saisie_active: false,
  semaines_validees: [1],
  semaines_passees: [] as number[],
  semaines_lancees: [] as number[],
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

function jsonOk(data: unknown): Promise<Response> {
  return Promise.resolve({ ok: true, json: async () => data } as Response);
}

function stubFetch(opts?: { etat?: typeof ETAT; extras?: typeof EXTRAS }): ReturnType<typeof vi.fn> {
  const etat = opts?.etat ?? ETAT;
  const extras = opts?.extras ?? EXTRAS;
  const mock = vi.fn((url: string, init?: RequestInit) => {
    const cible = String(url);
    if (cible.includes("/celcat/extras") && !cible.includes("/ajouter") && !cible.includes("/ignorer")) {
      return jsonOk({ extras });
    }
    if (cible.includes("/celcat/logs")) {
      return jsonOk(LOGS);
    }
    if (cible.includes("/celcat/saisie") && init?.method === "PATCH") {
      const body = JSON.parse(String(init.body)) as { active: boolean };
      return jsonOk({ ...etat, saisie_active: body.active });
    }
    if (cible.includes("/celcat/valider") && init?.method === "POST") {
      const body = JSON.parse(String(init.body)) as { semaines: number[] };
      return jsonOk({ ...etat, semaines_validees: body.semaines });
    }
    if (cible.includes("/celcat/lancer-nuit") && init?.method === "POST") {
      const lancees = [...new Set([...(etat.semaines_lancees ?? []), ...(etat.semaines_validees ?? [])])].sort(
        (a, b) => a - b,
      );
      return jsonOk({ ...etat, semaines_lancees: lancees });
    }
    if (cible.includes("/ajouter") || cible.includes("/ignorer")) {
      return jsonOk({ statut: "ok" });
    }
    return jsonOk(etat);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function urlsDuMock(mock: ReturnType<typeof vi.fn>): string[] {
  return mock.mock.calls.map((appel) => String(appel[0]));
}

describe("AdminCelcatView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("should show ÉCRITURE OFF, consequence, worker and last validation in the hero", async () => {
    stubFetch();
    render(<AdminCelcatView />);

    await screen.findByText("ÉCRITURE OFF");
    expect(screen.getByText(/ne s’écrivent pas tout de suite/i)).toBeInTheDocument();
    expect(screen.getByText("Worker joignable.")).toBeInTheDocument();
    expect(screen.getByText(/Dernière validation/)).toBeInTheDocument();
    expect(screen.getByText(/2026-09-01/)).toBeInTheDocument();
  });

  it("should show ÉCRITURE ON and the Live consequence when saisie is active", async () => {
    stubFetch({ etat: { ...ETAT, saisie_active: true } });
    render(<AdminCelcatView />);

    await screen.findByText("ÉCRITURE ON");
    expect(screen.getByText(/s’écrit tout de suite/i)).toBeInTheDocument();
  });

  it("should expose a switch named écriture, off by default, without PATCH on first paint", async () => {
    const mock = stubFetch();
    render(<AdminCelcatView />);

    const interrupteur = await screen.findByRole("switch", { name: /écriture/i });
    expect(interrupteur).toHaveAttribute("aria-checked", "false");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();

    await waitFor(() => expect(urlsDuMock(mock).some((u) => u.includes("/celcat/etat"))).toBe(true));
    expect(urlsDuMock(mock).some((u) => u.includes("/celcat/saisie"))).toBe(false);
  });

  it("should PATCH /celcat/saisie with active true when the switch is turned on", async () => {
    const mock = stubFetch();
    render(<AdminCelcatView />);

    fireEvent.click(await screen.findByRole("switch", { name: /écriture/i }));

    await waitFor(() => {
      const saisie = mock.mock.calls.find(([url, init]) => String(url).includes("/celcat/saisie") && init?.method === "PATCH");
      expect(saisie).toBeDefined();
      expect(JSON.parse(String(saisie?.[1]?.body))).toEqual({ active: true });
    });
    expect(await screen.findByText("ÉCRITURE ON")).toBeInTheDocument();
  });

  it("should show numbered steps 1, 2 and 3 and explain the night lot in step 2", async () => {
    stubFetch();
    render(<AdminCelcatView />);

    await screen.findByRole("switch", { name: /écriture/i });
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /armer l’écriture/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /lot de nuit/i })).toBeInTheDocument();
    expect(screen.getByText(/lancer maintenant enfile le même lot/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /lancer maintenant/i })).toBeInTheDocument();
  });

  it("should name the submit lot de nuit and not expose a button named only Valider", async () => {
    stubFetch();
    render(<AdminCelcatView />);

    await screen.findByRole("button", { name: /lot de nuit/i });
    expect(screen.queryByRole("button", { name: /^valider$/i })).not.toBeInTheDocument();
  });

  it("should label weeks Semaine N, keep multi-select, and distinguish validated vs checked", async () => {
    stubFetch();
    render(<AdminCelcatView />);

    const s1 = await screen.findByRole("button", { name: /^semaine 1 validée$/i });
    const s2 = screen.getByRole("button", { name: /^semaine 2$/i });
    expect(s1).toHaveClass("celcat-semaine--validee");
    expect(s1).toHaveClass("celcat-semaine--cochee");
    expect(s2).not.toHaveClass("celcat-semaine--validee");
    expect(s2).not.toHaveClass("celcat-semaine--cochee");

    fireEvent.click(s2);
    expect(s2).toHaveClass("celcat-semaine--cochee");
    expect(s2).not.toHaveClass("celcat-semaine--validee");

    fireEvent.click(s2);
    expect(s2).not.toHaveClass("celcat-semaine--cochee");
  });

  it("should POST /celcat/valider with the draft semaines when the night-lot button is pressed", async () => {
    const mock = stubFetch();
    render(<AdminCelcatView />);

    fireEvent.click(await screen.findByRole("button", { name: /^semaine 2$/i }));
    fireEvent.click(screen.getByRole("button", { name: /lot de nuit/i }));

    await waitFor(() => {
      const valider = mock.mock.calls.find(([url, init]) => String(url).includes("/celcat/valider") && init?.method === "POST");
      expect(valider).toBeDefined();
      expect(JSON.parse(String(valider?.[1]?.body))).toEqual({ semaines: [1, 2] });
    });
  });

  it("should show Ajouter and Ignorer for an open extra and POST the matching extras routes", async () => {
    const mock = stubFetch();
    render(<AdminCelcatView />);

    await screen.findByText(/WR106/);
    fireEvent.click(screen.getByRole("button", { name: /ajouter WR106/i }));
    await waitFor(() => {
      expect(urlsDuMock(mock).some((u) => u.includes("/celcat/extras/extra-1/ajouter"))).toBe(true);
    });
    expect(screen.queryByText(/WR106/)).not.toBeInTheDocument();
  });

  it("should POST ignorer for an open extra", async () => {
    const mock = stubFetch();
    render(<AdminCelcatView />);

    fireEvent.click(await screen.findByRole("button", { name: /ignorer WR106/i }));
    await waitFor(() => {
      expect(urlsDuMock(mock).some((u) => u.includes("/celcat/extras/extra-1/ignorer"))).toBe(true);
    });
  });

  it("should show Aucun extra ouvert and no Ajouter/Ignorer when extras are empty", async () => {
    stubFetch({ extras: [] });
    render(<AdminCelcatView />);

    await screen.findByText("Aucun extra ouvert.");
    expect(screen.queryByRole("button", { name: /ajouter/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /ignorer/i })).not.toBeInTheDocument();
  });

  it("should keep journal separate from extras with lisible kinds and motif", async () => {
    stubFetch();
    render(<AdminCelcatView />);

    const journal = await screen.findByRole("heading", { name: /^journal$/i });
    const panneau = journal.closest(".panel");
    expect(panneau).not.toBeNull();
    expect(within(panneau as HTMLElement).queryByRole("button", { name: /ajouter/i })).not.toBeInTheDocument();
    expect(within(panneau as HTMLElement).getByText(/créé/i)).toBeInTheDocument();
    expect(within(panneau as HTMLElement).getByText(/bloqué/i)).toBeInTheDocument();
    expect(within(panneau as HTMLElement).getByText(/WR314D/)).toBeInTheDocument();
    expect(within(panneau as HTMLElement).getByText(/sans code Celcat/i)).toBeInTheDocument();
  });

  it("should only call etat, extras ouvert, and logs on mount", async () => {
    const mock = stubFetch();
    render(<AdminCelcatView />);

    await screen.findByRole("switch", { name: /écriture/i });
    const chemins = urlsDuMock(mock);
    expect(chemins.some((u) => u.includes("/celcat/etat"))).toBe(true);
    expect(chemins.some((u) => u.includes("/celcat/extras?statut=ouvert"))).toBe(true);
    expect(chemins.some((u) => u.includes("/celcat/logs?limit=50"))).toBe(true);
    expect(chemins).toHaveLength(3);
  });

  it("should disable a past week and a launched week", async () => {
    stubFetch({
      etat: { ...ETAT, semaines_passees: [1], semaines_lancees: [3], semaines_validees: [3] },
    });
    render(<AdminCelcatView />);

    const passee = await screen.findByRole("button", { name: /semaine 1 passée/i });
    const lancee = screen.getByRole("button", { name: /semaine 3 lancée/i });
    expect(passee).toBeDisabled();
    expect(lancee).toBeDisabled();
    expect(screen.getByRole("button", { name: /^semaine 2$/i })).not.toBeDisabled();
  });

  it("should disable Lancer maintenant when saisie is off", async () => {
    stubFetch();
    render(<AdminCelcatView />);

    const lancer = await screen.findByRole("button", { name: /lancer maintenant/i });
    expect(lancer).toBeDisabled();
  });

  it("should POST /celcat/lancer-nuit when Lancer maintenant is clicked while saisie is on", async () => {
    const mock = stubFetch({ etat: { ...ETAT, saisie_active: true, semaines_validees: [4] } });
    render(<AdminCelcatView />);

    fireEvent.click(await screen.findByRole("button", { name: /lancer maintenant/i }));
    await waitFor(() => {
      expect(
        mock.mock.calls.some(([url, init]) => String(url).includes("/celcat/lancer-nuit") && init?.method === "POST"),
      ).toBe(true);
    });
  });
});
