/**
 * Ce que l'écran dit APRÈS un clic sur « Corriger ».
 *
 * Retour utilisateur du 16/09/2026 : « j'ai l'impression de devoir cliquer
 * plusieurs fois à des heures différentes sur "Corriger les écarts de cette
 * semaine" pour que ça les corrige vraiment. »
 *
 * Le serveur a cessé de mentir (cf. `test_compte_rendu_honnete_2026_09_16`),
 * mais tant que l'écran n'affiche pas ce qu'il rend, le geste reste aussi
 * opaque qu'avant. Ces tests tiennent les trois choses qui manquaient :
 * relire après avoir agi, dire ce qui attendait déjà, et nommer ce qui n'a
 * pas pu être traduit.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ComparaisonCelcat } from "./ComparaisonCelcat";

const BASE = {
  semaine: 1,
  semaine_celcat: 3,
  releve_le: "2026-09-16T10:00:00+00:00",
  age_secondes: 300,
  perime: false,
};

const ECART = {
  statut: "ecart" as const,
  session_id: "WR116-S1-CM-1",
  course_code: "WR116",
  caliut: { jour: 1, heure: "15:30", salle: "Amphi 3 MMI", semaine: 1 },
  celcat: {
    event_id: 1931709, jour: 1, heure: "13:50", salle: "Amphi 3 MMI",
    categorie: "[CM]", module: "WR116 Traitement Info", groupe: "BUT MMI S1 CM",
  },
  ecarts: ["heure"],
};

function jsonOk(data: unknown): Promise<Response> {
  return Promise.resolve({ ok: true, json: async () => data } as Response);
}

/** Un serveur qui répond selon l'URL : la comparaison, la correction, la file. */
function serveur({
  correction,
  lignesApres,
}: {
  correction: Record<string, unknown>;
  lignesApres?: unknown[];
}) {
  let corrige = false;
  const mock = vi.fn((url: unknown) => {
    const u = String(url);
    if (u.includes("/comparaison/corriger")) {
      corrige = true;
      return jsonOk(correction);
    }
    if (u.includes("/celcat/comparaison")) {
      // Un « en trop » dès le départ : c'est lui qui fait apparaître
      // « Corriger sans supprimer », le geste rattrapable par lequel ces
      // tests entrent sans avoir à simuler la modale de confirmation.
      return jsonOk({
        ...BASE,
        lignes: corrige && lignesApres !== undefined ? lignesApres : AVEC_EN_TROP,
      });
    }
    if (u.includes("/celcat/file")) {
      return jsonOk({ en_attente: 1, par_action: { update: 1 }, reussis: 0, echecs: 0 });
    }
    return jsonOk({});
  });
  vi.stubGlobal("fetch", mock as unknown as typeof fetch);
  return mock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function corriger() {
  fireEvent.click(
    await screen.findByRole("button", { name: /corriger sans supprimer/i }),
  );
}

// « Corriger sans supprimer » ne demande aucune confirmation — c'est le
// geste rattrapable. Il sert donc de porte d'entrée à ces tests, sans avoir
// à simuler la modale.
const AVEC_EN_TROP = [
  ECART,
  { ...ECART, statut: "en_trop_celcat" as const, session_id: "", caliut: null },
];

describe("Compte rendu après « Corriger »", () => {
  it("relit la comparaison au lieu de laisser le tableau figé", async () => {
    // LE DÉFAUT PRINCIPAL. Le tableau restait sur l'état d'avant le clic :
    // rien ne bougeait à l'écran, même quand tout avait réussi.
    const mock = vi.fn((url: unknown) => {
      const u = String(url);
      if (u.includes("/comparaison/corriger")) {
        return jsonOk({ total: 1, message: "1 correction(s) mises en file", abandonnes: [] });
      }
      if (u.includes("/celcat/comparaison")) return jsonOk({ ...BASE, lignes: AVEC_EN_TROP });
      return jsonOk({ en_attente: 0 });
    });
    vi.stubGlobal("fetch", mock as unknown as typeof fetch);
    render(<ComparaisonCelcat semaine={1} />);

    await corriger();

    await waitFor(() => {
      const comparaisons = mock.mock.calls.filter(([u]) =>
        String(u).includes("/celcat/comparaison?"),
      );
      expect(comparaisons.length).toBeGreaterThan(1);
    });
  });

  it("dit ce qui attendait DÉJÀ, pour qu'on cesse de recliquer", async () => {
    serveur({
      correction: {
        total: 0,
        deja_en_file: 3,
        abandonnes: [],
        message: "Rien de nouveau à mettre en file.",
      },
      lignesApres: AVEC_EN_TROP,
    });
    render(<ComparaisonCelcat semaine={1} />);

    await corriger();

    const bloc = await screen.findByTestId("correction-deja-en-file");
    expect(bloc.textContent).toContain("3");
    expect(bloc.textContent).toMatch(/recliquer n’y change rien/i);
  });

  it("nomme les écarts qu'il n'a pas su traduire, groupés par cause", async () => {
    // Neuf écarts au tableau et cinq corrections au message, sans un mot sur
    // les quatre autres : c'est ce qui apprend à ne plus croire l'écran.
    serveur({
      correction: {
        total: 1,
        deja_en_file: 0,
        message: "1 correction(s) mises en file",
        abandonnes: [
          {
            statut: "en_trop_celcat", session_id: "WRA507D-S5-TD-2", course_code: "WRA507D",
            event_id: 1953820, groupe: "BUT MMI S5 TD EF", raison: "groupe_inconnu",
            explication: "le groupe « BUT MMI S5 TD EF » manque à data/config/celcat_groupes.yaml",
          },
          {
            statut: "en_trop_celcat", session_id: "WRA507D-S5-TD-3", course_code: "WRA507D",
            event_id: 1953821, groupe: "BUT MMI S5 TD EF", raison: "groupe_inconnu",
            explication: "le groupe « BUT MMI S5 TD EF » manque à data/config/celcat_groupes.yaml",
          },
        ],
      },
      lignesApres: AVEC_EN_TROP,
    });
    render(<ComparaisonCelcat semaine={1} />);

    await corriger();

    const details = await screen.findByTestId("correction-abandonnes");
    // Deux séances, UNE cause : c'est le regroupement qui dit par quoi
    // commencer — une ligne à ajouter dans un fichier, pas deux enquêtes.
    expect(details.textContent).toContain("2 écart(s)");
    expect(details.textContent).toContain("1 cause");
    expect(within(details).getByText(/2×/)).toBeTruthy();
    expect(details.textContent).toContain("celcat_groupes.yaml");
    expect(details.textContent).toContain("WRA507D-S5-TD-2");
  });

  it("n'affiche aucun compte rendu tant qu'on n'a rien demandé", async () => {
    serveur({ correction: {} });
    render(<ComparaisonCelcat semaine={1} />);

    await screen.findByTestId("comparaison-celcat");
    expect(screen.queryByTestId("compte-rendu-correction")).toBeNull();
  });

  it("oublie le compte rendu quand on change de semaine", async () => {
    // « 12 corrections mises en file » restait affiché sous la semaine
    // suivante, qui n'avait pourtant rien reçu.
    serveur({
      correction: { total: 12, deja_en_file: 0, abandonnes: [], message: "12 correction(s) mises en file" },
      lignesApres: AVEC_EN_TROP,
    });
    const vue = render(<ComparaisonCelcat semaine={1} />);

    await corriger();
    await screen.findByTestId("compte-rendu-correction");

    vue.rerender(<ComparaisonCelcat semaine={2} />);

    await waitFor(() => expect(screen.queryByTestId("compte-rendu-correction")).toBeNull());
  });
});
