/**
 * Date passée : le glisser-déposer (`performMove`) et l'échange
 * (`performSwap`) doivent, eux aussi, proposer la popup de forçage FORTE
 * dès qu'un conflit forçable commence par « Date passée : » — item A,
 * 22/09/2026. Cf. `placement.datePassee.test.ts` pour la construction du
 * texte/des options (`texteEtOptionsForcage`, partagée par les deux
 * chemins).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Placement } from "../types";
import { confirmAsync } from "./confirmDialog";
import { performMove, performSwap } from "./moveSession";

vi.mock("./confirmDialog", () => ({ confirmAsync: vi.fn(), alerterAsync: vi.fn() }));
vi.mock("../api/client", () => ({
  validateMove: vi.fn(),
  movePlacement: vi.fn(),
  echangerPlacements: vi.fn(),
}));

const MOTIF_DATE = "Date passée : cette séance a déjà eu lieu (lundi 21/09/2026).";

const PLACEMENT: Placement = {
  session_id: "s1",
  week: 3,
  day: 1,
  slot: 2,
  course_code: "WR101",
  course_name: "Culture numérique",
  session_type: "TD",
  group_ids: ["but1-td-ab"],
  teacher_codes: ["MRI"],
  room_id: null,
  room_label: null,
  is_eval: false,
  locked: false,
  duration_slots: 1,
};

afterEach(() => {
  vi.mocked(confirmAsync).mockReset();
  vi.resetAllMocks();
});

describe("performMove — date passée", () => {
  it("propose « Oui, modifier le passé » en variante danger", async () => {
    const client = await import("../api/client");
    vi.mocked(client.validateMove).mockResolvedValue({
      valid: false,
      hard_conflicts: [MOTIF_DATE],
      soft_warnings: [],
      blocking_conflicts: [],
      suggestions: [],
      suggestions_note: null,
    });
    vi.mocked(client.movePlacement).mockResolvedValue({ ...PLACEMENT, week: 3, day: 2, slot: 2 });
    vi.mocked(confirmAsync).mockResolvedValue(true);

    const ok = await performMove(
      "s1",
      { week: 3, day: 2, slot: 2 },
      PLACEMENT,
      () => {},
      () => {},
    );

    expect(ok).toBe(true);
    const [texte, options] = vi.mocked(confirmAsync).mock.calls[0];
    expect(String(texte).indexOf(MOTIF_DATE)).toBe(0);
    expect(String(texte)).toContain("la modification sera aussi envoyée vers Celcat");
    expect(options).toEqual({
      title: "Modifier une date passée",
      confirmLabel: "Oui, modifier le passé",
      variant: "danger",
    });
    expect(vi.mocked(client.movePlacement).mock.calls[0][1]).toMatchObject({ force: true });
  });

  it("reste « Forcer le déplacement » sans date passée", async () => {
    const client = await import("../api/client");
    vi.mocked(client.validateMove).mockResolvedValue({
      valid: false,
      hard_conflicts: ["Ordre pédagogique non respecté"],
      soft_warnings: [],
      blocking_conflicts: [],
      suggestions: [],
      suggestions_note: null,
    });
    vi.mocked(client.movePlacement).mockResolvedValue({ ...PLACEMENT, day: 2 });
    vi.mocked(confirmAsync).mockResolvedValue(true);

    await performMove(
      "s1",
      { week: 3, day: 2, slot: 2 },
      PLACEMENT,
      () => {},
      () => {},
    );

    const [, options] = vi.mocked(confirmAsync).mock.calls[0];
    expect(options?.confirmLabel).toBe("Forcer le déplacement");
    expect(options?.variant).toBeUndefined();
  });
});

describe("performSwap — date passée", () => {
  it("propose « Oui, modifier le passé » en variante danger", async () => {
    const client = await import("../api/client");
    // Premier appel : accepter l'échange lui-même (confirmAsync générique).
    // Second appel : le forçage, celui qu'on vérifie.
    vi.mocked(confirmAsync).mockResolvedValueOnce(true).mockResolvedValueOnce(true);
    vi.mocked(client.echangerPlacements)
      .mockRejectedValueOnce(
        new Error(
          JSON.stringify({ message: "Conflit", hard_conflicts: [MOTIF_DATE], soft_warnings: [], blocking_conflicts: [] }),
        ),
      )
      .mockResolvedValueOnce({ placements: [PLACEMENT, { ...PLACEMENT, session_id: "s2" }] });

    const ok = await performSwap(
      "s1",
      "s2",
      "Séance A",
      "Séance B",
      () => {},
      () => {},
    );

    expect(ok).toBe(true);
    const [texte, options] = vi.mocked(confirmAsync).mock.calls[1];
    expect(String(texte).indexOf(MOTIF_DATE)).toBe(0);
    expect(options).toEqual({
      title: "Modifier une date passée",
      confirmLabel: "Oui, modifier le passé",
      variant: "danger",
    });
  });
});
