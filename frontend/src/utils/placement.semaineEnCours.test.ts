/**
 * Créer une séance sur la semaine en cours doit proposer « Créer quand même ».
 *
 * Signalement du 21/09/2026 : « je souhaite créer une séance, sur cette
 * semaine mais je ne peux pas la forcer, mince ».
 *
 * Le verrou de semaine est forçable, mais le serveur le renvoyait en simple
 * texte. `creerSeanceAvecConfirmation` ne propose de forcer que devant un
 * conflit STRUCTURÉ : devant un texte, il rendait le message et s'arrêtait.
 * Ces tests tiennent les deux côtés du contrat.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { confirmAsync } from "./confirmDialog";
import { creerSeanceAvecConfirmation } from "./placement";

vi.mock("./confirmDialog", () => ({ confirmAsync: vi.fn(), alerterAsync: vi.fn() }));

const CORPS = {
  course_code: "WR101",
  session_type: "TD",
  group_ids: ["but1-td-ab"],
  teacher_codes: ["MRI"],
  week: 3,
  day: 1,
  slot: 2,
};

const VERROU = "Semaine 4 non modifiable (statut : current)";

function reponse(status: number, corps: unknown): Promise<Response> {
  return Promise.resolve({
    ok: status < 400,
    status,
    statusText: status === 409 ? "Conflict" : "OK",
    json: async () => corps,
  } as Response);
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(confirmAsync).mockReset();
});

describe("Créer une séance sur la semaine en cours", () => {
  it("propose de forcer, puis recrée avec force, quand le verrou est structuré", async () => {
    vi.mocked(confirmAsync).mockResolvedValue(true);
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(
        reponse(409, {
          detail: { message: "Conflit", hard_conflicts: [VERROU], soft_warnings: [], suggestions: [] },
        }),
      )
      .mockReturnValueOnce(reponse(200, { session_id: "WR101-S1-TD-x", week: 3, day: 1, slot: 2 }));
    vi.stubGlobal("fetch", fetchMock);

    const resultat = await creerSeanceAvecConfirmation(CORPS);

    expect(confirmAsync).toHaveBeenCalledTimes(1);
    expect(String(vi.mocked(confirmAsync).mock.calls[0][0])).toContain(VERROU);
    expect(vi.mocked(confirmAsync).mock.calls[0][1]?.confirmLabel).toBe("Créer quand même");
    const second = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(second.force).toBe(true);
    expect(resultat.ok).toBe(true);
  });

  it("ne crée rien si l'utilisateur renonce", async () => {
    vi.mocked(confirmAsync).mockResolvedValue(false);
    const fetchMock = vi.fn().mockReturnValueOnce(
      reponse(409, { detail: { message: "Conflit", hard_conflicts: [VERROU], soft_warnings: [] } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const resultat = await creerSeanceAvecConfirmation(CORPS);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(resultat.ok).toBe(false);
  });

  it("documente l'ancien défaut : un verrou en simple texte ne proposait pas de forcer", async () => {
    // Ce que le serveur renvoyait avant le 21/09/2026. Le test fige la raison
    // du correctif côté serveur : le front ne peut pas deviner qu'un texte
    // est forçable, c'est au serveur de le structurer.
    const fetchMock = vi.fn().mockReturnValueOnce(reponse(409, { detail: VERROU }));
    vi.stubGlobal("fetch", fetchMock);

    const resultat = await creerSeanceAvecConfirmation(CORPS);

    expect(confirmAsync).not.toHaveBeenCalled();
    expect(resultat).toEqual({ ok: false, message: VERROU });
  });
});
