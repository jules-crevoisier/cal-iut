/**
 * Date passée : la popup de forçage doit être FORTE (item A, 22/09/2026).
 *
 * To-do : « ne pas pouvoir déplacer ou créer de séances sur des dates
 * passées ou alors vraiment une popup pour le forcer ». Décision de Jules :
 * tout reste forçable, mais le front doit reconnaître un conflit « Date
 * passée : ... » (préfixe exact envoyé par le serveur,
 * cf. `api/main.py::_dates_passees_motifs`) et proposer une confirmation
 * FORTE — titre dédié, message de la date en premier, phrase Celcat
 * explicite, bouton de confirmation en danger.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { confirmAsync } from "./confirmDialog";
import { creerSeanceAvecConfirmation, estDatePassee, texteEtOptionsForcage } from "./placement";

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

const MOTIF_DATE = "Date passée : le lundi 21/09/2026 est déjà écoulé.";
const MOTIF_ORDINAIRE = "Ordre pédagogique non respecté";

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

describe("estDatePassee", () => {
  it("reconnaît le préfixe exact envoyé par le serveur", () => {
    expect(estDatePassee([MOTIF_DATE])).toBe(true);
    expect(estDatePassee(["cette séance a déjà eu lieu"])).toBe(false);
    expect(estDatePassee([])).toBe(false);
  });
});

describe("texteEtOptionsForcage", () => {
  it("reste la variante ordinaire sans date passée", () => {
    const { texte, options } = texteEtOptionsForcage([MOTIF_ORDINAIRE], [], [], "Forcer le déplacement");
    expect(options).toEqual({ confirmLabel: "Forcer le déplacement" });
    expect(texte).toContain("Forçable");
    expect(texte).toContain(MOTIF_ORDINAIRE);
    expect(texte).not.toContain("Modifier une date passée");
  });

  it("bascule en variante FORTE dès qu'un conflit forçable est une date passée", () => {
    const { texte, options } = texteEtOptionsForcage(
      [MOTIF_DATE, MOTIF_ORDINAIRE],
      [],
      [],
      "Forcer le déplacement",
    );
    expect(options).toEqual({
      title: "Modifier une date passée",
      confirmLabel: "Oui, modifier le passé",
      variant: "danger",
    });
    // Le message de la date en PREMIER.
    expect(texte.indexOf(MOTIF_DATE)).toBe(0);
    expect(texte).toContain("la modification sera aussi envoyée vers Celcat");
    expect(texte).toContain(MOTIF_ORDINAIRE);
  });

  it("ignore un motif « Date passée » qui serait bloquant (jamais le cas serveur, mais la fonction filtre sur `blocking`)", () => {
    const { options } = texteEtOptionsForcage([MOTIF_DATE], [MOTIF_DATE], [], "Forcer");
    // Une fois exclu des forçables (car listé dans `blocking`), il ne
    // déclenche plus la variante forte : cohérent, un motif bloquant ne
    // passe jamais par cette confirmation (les appelants l'interceptent
    // avant, cf. `gererConflitPuisForcer`/`performMove`).
    expect(options).toEqual({ confirmLabel: "Forcer" });
  });
});

describe("La popup de forçage devient FORTE sur une date passée (via un appel réel)", () => {
  it("propose « Oui, modifier le passé » en variante danger, message daté en premier", async () => {
    vi.mocked(confirmAsync).mockResolvedValue(true);
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(
        reponse(409, {
          detail: { message: "Conflit", hard_conflicts: [MOTIF_DATE], soft_warnings: [], suggestions: [] },
        }),
      )
      .mockReturnValueOnce(reponse(200, { session_id: "WR101-S1-TD-x", week: 3, day: 1, slot: 2 }));
    vi.stubGlobal("fetch", fetchMock);

    const resultat = await creerSeanceAvecConfirmation(CORPS);

    expect(confirmAsync).toHaveBeenCalledTimes(1);
    const [texte, options] = vi.mocked(confirmAsync).mock.calls[0];
    expect(String(texte).indexOf(MOTIF_DATE)).toBe(0);
    expect(String(texte)).toContain("la modification sera aussi envoyée vers Celcat");
    expect(options).toEqual({
      title: "Modifier une date passée",
      confirmLabel: "Oui, modifier le passé",
      variant: "danger",
    });
    const second = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(second.force).toBe(true);
    expect(resultat.ok).toBe(true);
  });

  it("reste la variante ordinaire quand aucun conflit ne touche une date passée", async () => {
    vi.mocked(confirmAsync).mockResolvedValue(true);
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(
        reponse(409, {
          detail: { message: "Conflit", hard_conflicts: [MOTIF_ORDINAIRE], soft_warnings: [], suggestions: [] },
        }),
      )
      .mockReturnValueOnce(reponse(200, { session_id: "WR101-S1-TD-x", week: 3, day: 1, slot: 2 }));
    vi.stubGlobal("fetch", fetchMock);

    await creerSeanceAvecConfirmation(CORPS);

    const [, options] = vi.mocked(confirmAsync).mock.calls[0];
    expect(options?.title).toBeUndefined();
    expect(options?.confirmLabel).toBe("Créer quand même");
    expect(options?.variant).toBeUndefined();
  });
});
