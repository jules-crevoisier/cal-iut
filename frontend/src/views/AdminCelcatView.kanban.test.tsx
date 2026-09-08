/**
 * Vue d'activité Celcat, en colonnes.
 *
 * Demande utilisateur 08/09/2026 : « j'aimerais bien une vue qui nous dit en
 * temps réel les cours modifiés dans cal-iut, leur statut dans Celcat, et les
 * infos un peu comme un kanban », avec des colonnes par type d'action
 * récente, et « pouvoir voir ce qui est dans Celcat […] avec un bouton qui
 * permette de refresh quand l'on veut ».
 *
 * Ce que ces tests protègent tient en une phrase : la vue ne doit jamais
 * avoir l'air de dire que tout va bien quand elle ne sait rien. C'est la
 * leçon de la semaine — un worker qui annonçait « file d'attente drainée »
 * sans avoir écrit une seule fois, et des compteurs à zéro qui ne pouvaient
 * structurellement pas bouger. Un écran de supervision qui reproduirait ce
 * défaut serait pire qu'utile : il rassurerait.
 *
 * D'où les points vérifiés ici :
 *   - un échec répété affiche son NOMBRE de tentatives, pas une ligne isolée
 *     qui laisserait croire à un incident ponctuel ;
 *   - un instantané périmé le DIT, au lieu de se présenter comme l'état
 *     courant ;
 *   - un relevé qui a échoué montre sa raison plutôt qu'un écran vide ;
 *   - le bouton annonce une demande différée, pas un rafraîchissement
 *     immédiat qu'on ne peut pas tenir (le sidecar doit monter le VPN).
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminCelcatView } from "./AdminCelcatView";

const ETAT = {
  saisie_active: true,
  semaines_validees: [1],
  semaines_passees: [] as number[],
  semaines_lancees: [] as number[],
  semaines_completes: [] as number[],
  valide_le: null,
  dernier_job: null,
  derniere_ecriture_celcat: null as string | null,
  compteurs: { created: 2, modified: 1, deleted: 1, blocked: 0 },
  worker_ok: true,
};

const LOGS = {
  items: [
    { kind: "created", session_id: "WR101-S1-TD-1", event_id: 111, course_code: "WR101" },
    { kind: "modified", session_id: "WR116-S1-CM-1", event_id: 1931709, course_code: "WR116" },
    { kind: "deleted", session_id: "WR120-S1-TD-3", event_id: 1933245, course_code: "WR120" },
    {
      kind: "echec",
      session_id: "WR108-S1-CM-1",
      course_code: "WR108",
      motif: "EUDLDSError : partial key",
      repetitions: 87,
    },
  ],
  cursor: null,
};

const INSTANTANE_FRAIS = {
  evenements: [{ event_id: 1931709, module: "WR116 Traitement Info", salle: "Amphi 3 MMI" }],
  groupes: ["BUT MMI S1 CM"],
  releve_le: "2026-09-08T10:00:00+00:00",
  age_secondes: 300,
  perime: false,
  demande_en_cours: false,
  erreur: null as string | null,
};

function jsonOk(data: unknown): Promise<Response> {
  return Promise.resolve({ ok: true, json: async () => data } as Response);
}

function stubFetch(instantane: unknown = INSTANTANE_FRAIS) {
  const mock = vi.fn((url: string, init?: RequestInit) => {
    const cible = String(url);
    if (cible.includes("/celcat/instantane/rafraichir")) {
      return jsonOk({ demande: true, message: "Relevé demandé — au prochain passage." });
    }
    if (cible.includes("/celcat/instantane")) return jsonOk(instantane);
    if (cible.includes("/celcat/logs")) return jsonOk(LOGS);
    if (cible.includes("/celcat/extras")) return jsonOk({ extras: [] });
    if (cible.includes("/celcat/etat")) return jsonOk(ETAT);
    return jsonOk(ETAT);
  });
  vi.stubGlobal("fetch", mock as unknown as typeof fetch);
  return mock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Vue d'activité Celcat", () => {
  it("range chaque écriture dans sa colonne", async () => {
    stubFetch();
    render(<AdminCelcatView />);

    const creees = await screen.findByTestId("colonne-created");
    expect(within(creees).getByText(/WR101-S1-TD-1/)).toBeTruthy();

    const modifiees = screen.getByTestId("colonne-modified");
    expect(within(modifiees).getByText(/WR116-S1-CM-1/)).toBeTruthy();

    const supprimees = screen.getByTestId("colonne-deleted");
    expect(within(supprimees).getByText(/WR120-S1-TD-3/)).toBeTruthy();

    const echecs = screen.getByTestId("colonne-echec");
    expect(within(echecs).getByText(/WR108-S1-CM-1/)).toBeTruthy();
  });

  it("montre COMBIEN de fois un échec s'est répété", async () => {
    // 87 tentatives et 1 tentative n'appellent pas le même geste : sans ce
    // nombre, un blocage installé depuis des heures ressemble à un incident.
    stubFetch();
    render(<AdminCelcatView />);

    const echecs = await screen.findByTestId("colonne-echec");
    expect(within(echecs).getByText(/87/)).toBeTruthy();
  });

  it("affiche le motif d'un échec, pas seulement son existence", async () => {
    stubFetch();
    render(<AdminCelcatView />);

    const echecs = await screen.findByTestId("colonne-echec");
    expect(within(echecs).getByText(/partial key/)).toBeTruthy();
  });

  it("donne l'âge du relevé Celcat", async () => {
    stubFetch();
    render(<AdminCelcatView />);

    const bloc = await screen.findByTestId("instantane-celcat");
    expect(within(bloc).getByText(/il y a/i)).toBeTruthy();
  });

  it("signale un relevé périmé au lieu de le présenter comme courant", async () => {
    stubFetch({ ...INSTANTANE_FRAIS, age_secondes: 10800, perime: true });
    render(<AdminCelcatView />);

    const bloc = await screen.findByTestId("instantane-celcat");
    expect(within(bloc).getByText(/périmé|à rafraîchir/i)).toBeTruthy();
  });

  it("dit qu'aucun relevé n'existe encore, sans faire croire que Celcat est vide", async () => {
    stubFetch({
      evenements: [],
      groupes: [],
      releve_le: null,
      age_secondes: null,
      perime: true,
      demande_en_cours: false,
      erreur: null,
    });
    render(<AdminCelcatView />);

    const bloc = await screen.findByTestId("instantane-celcat");
    expect(within(bloc).getByText(/aucun relevé/i)).toBeTruthy();
  });

  it("remonte la raison d'un relevé qui a échoué", async () => {
    // Un instantané vide sans explication ramènerait au silence qu'on répare.
    stubFetch({ ...INSTANTANE_FRAIS, evenements: [], erreur: "ESessionTimeout" });
    render(<AdminCelcatView />);

    const bloc = await screen.findByTestId("instantane-celcat");
    expect(within(bloc).getByText(/ESessionTimeout/)).toBeTruthy();
  });

  it("le bouton Rafraîchir demande un relevé sans promettre l'immédiat", async () => {
    const mock = stubFetch();
    render(<AdminCelcatView />);

    const bouton = await screen.findByRole("button", { name: /rafraîchir/i });
    fireEvent.click(bouton);

    await waitFor(() =>
      expect(
        mock.mock.calls.some(([u]) => String(u).includes("/celcat/instantane/rafraichir")),
      ).toBe(true),
    );
    // L'utilisateur doit comprendre que le relevé n'est pas encore fait.
    await screen.findByText(/prochain passage|demandé/i);
  });
});
