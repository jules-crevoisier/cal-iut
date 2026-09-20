/**
 * L'écran Celcat, refondu le 16/09/2026 en un écran unique.
 *
 * Ce que ces tests protègent, dans l'ordre de lecture de l'écran :
 *
 *   1. le VERDICT de la semaine en cours d'abord, pas des réglages ;
 *   2. « Corriger » va jusqu'à la VÉRIFICATION sur un relevé neuf — c'est la
 *      réponse au retour « je dois cliquer plusieurs fois à des heures
 *      différentes » ;
 *   3. le geste par défaut ne supprime jamais ; supprimer montre ce qu'on
 *      supprime ;
 *   4. couper l'écriture, qui vide la file, demande confirmation ;
 *   5. tout ce que l'ancien écran garantissait déjà (semaines, extras,
 *      journal, relevé) reste garanti.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { confirmAsync } from "../utils/confirmDialog";
import { AdminCelcatView } from "./AdminCelcatView";

vi.mock("../utils/confirmDialog", () => ({ confirmAsync: vi.fn() }));

const CADENCE = { intervalleMs: 5, limiteWorkerMs: 400, limiteReleveMs: 400, sondageFileMs: 60_000 };

const LUNDI = "2026-09-14";

/** Calendrier : la semaine en cours (celle d'aujourd'hui) a l'indice 7, et une
 * semaine de vacances sans indice la précède — la position dans la liste ne
 * doit jamais servir d'indice. */
function weekRows() {
  const aujourdhui = new Date();
  const lundi = new Date(aujourdhui);
  lundi.setDate(aujourdhui.getDate() - ((aujourdhui.getDay() + 6) % 7));
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const decale = (jours: number) => {
    const d = new Date(lundi);
    d.setDate(d.getDate() + jours);
    return iso(d);
  };
  return [
    { monday: decale(-14), label: "Semaine 9 (passée)", blocked: false, weekIndex: 6 },
    { monday: decale(-7), label: "Semaine 10 (vacances)", blocked: true, weekIndex: null },
    { monday: decale(0), label: "Semaine 11 (en cours)", blocked: false, weekIndex: 7 },
    { monday: decale(7), label: "Semaine 12 (suivante)", blocked: false, weekIndex: 8 },
  ];
}

const ETAT = {
  saisie_active: true,
  worker_actif: true,
  semaines_validees: [8],
  semaines_passees: [1] as number[],
  semaines_lancees: [3] as number[],
  semaines_completes: [5] as number[],
  valide_le: "2026-09-01T10:00:00+00:00",
  dernier_job: null,
  derniere_ecriture_celcat: "2026-09-16T08:42:00",
  compteurs: { created: 1, modified: 0, deleted: 0, blocked: 1 },
  worker_ok: true,
};

const ECART = {
  statut: "ecart",
  session_id: "WR116-S1-CM-1",
  course_code: "WR116",
  caliut: { jour: 1, heure: "15:30", salle: "Amphi 3 MMI", semaine: 7 },
  celcat: {
    event_id: 1931709, jour: 1, heure: "13:50", salle: "Amphi 3 MMI", salles: ["Amphi 3 MMI"],
    categorie: "[CM]", module: "WR116 Traitement Info", groupe: "BUT MMI S1 CM",
  },
  ecarts: ["heure"],
};
const EN_TROP = {
  statut: "en_trop_celcat",
  session_id: "",
  course_code: "WR402",
  caliut: null,
  celcat: {
    event_id: 1953820, jour: 2, heure: "14:00", salle: "B003", salles: ["B003"],
    categorie: "[TD]", module: "WR402 Anglais", groupe: "BUT MMI S3 TD AB",
  },
  ecarts: [],
};
const IDENTIQUE = {
  statut: "identique",
  session_id: "WR101-S1-TD-1",
  course_code: "WR101",
  caliut: { jour: 0, heure: "08:00", salle: "H.103", semaine: 7 },
  celcat: {
    event_id: 111, jour: 0, heure: "07:50", salle: "H.103", salles: ["H.103"],
    categorie: "[TD]", module: "WR101 Anglais", groupe: "BUT MMI S1 TD AB",
  },
  ecarts: [],
};

function jsonOk(data: unknown): Promise<Response> {
  return Promise.resolve({ ok: true, json: async () => data } as Response);
}
function jsonKo(status: number, detail: string): Promise<Response> {
  return Promise.resolve({ ok: false, status, statusText: "Erreur", json: async () => ({ detail }) } as Response);
}

interface Scenario {
  etat?: Partial<typeof ETAT>;
  lignes?: unknown[];
  /** Lignes rendues APRÈS le nouveau relevé. */
  lignesApres?: unknown[];
  releve?: Record<string, unknown>;
  file?: Record<string, unknown>;
  correction?: Record<string, unknown>;
  /** Le worker ne repasse jamais. */
  workerMuet?: boolean;
  logs?: unknown[];
  extras?: unknown[];
}

/** Un serveur qui se souvient : le worker repasse après une correction, et un
 * relevé demandé finit par arriver. */
function serveur(s: Scenario = {}) {
  let etat = { ...ETAT, ...(s.etat ?? {}) };
  let passage = "2026-09-16T10:00:00+00:00";
  let releveLe = "2026-09-16T09:50:00+00:00";
  let corrige = false;
  let releveDemande = false;
  let relu = false;

  const mock = vi.fn((url: string, init?: RequestInit) => {
    const u = String(url);
    const methode = init?.method ?? "GET";
    if (u.includes("/app-state")) return jsonOk({ weekRows: weekRows() });
    if (u.includes("/celcat/comparaison/corriger")) {
      corrige = true;
      return jsonOk({ total: 1, deja_en_file: 0, abandonnes: [], message: "1 correction mise en file", ...(s.correction ?? {}) });
    }
    if (u.includes("/celcat/comparaison")) {
      return jsonOk({
        semaine: 7, semaine_celcat: 10, lundi: LUNDI, releve_le: releveLe, age_secondes: 300, perime: false,
        lignes: relu && s.lignesApres ? s.lignesApres : (s.lignes ?? [ECART, IDENTIQUE]),
        ...(s.releve ?? {}),
      });
    }
    if (u.includes("/celcat/instantane/rafraichir")) {
      releveDemande = true;
      return jsonOk({ demande: true, message: "Relevé demandé" });
    }
    if (u.includes("/celcat/instantane")) {
      // Le relevé demandé « arrive » à la lecture suivante.
      if (releveDemande && !relu) {
        releveDemande = false;
        relu = true;
        releveLe = "2026-09-16T10:10:00+00:00";
      }
      return jsonOk({ evenements: [], groupes: [], releve_le: releveLe, age_secondes: 300, perime: false, demande_en_cours: false, erreur: null, ...(s.releve ?? {}) });
    }
    if (u.includes("/celcat/file")) {
      if (corrige && !s.workerMuet) passage = "2026-09-16T10:06:00+00:00";
      return jsonOk({
        en_attente: corrige && !s.workerMuet ? 0 : 3, par_action: { update: 3 }, passe_le: passage, age_secondes: 40,
        reussis: 5, echecs: 0, ignores: 0, differes: 0, resume: "", ...(s.file ?? {}),
      });
    }
    if (u.includes("/celcat/logs")) return jsonOk({ items: s.logs ?? [], cursor: null });
    if (u.includes("/celcat/extras") && methode === "GET") return jsonOk({ extras: s.extras ?? [] });
    if (u.includes("/ajouter") || u.includes("/ignorer")) return jsonOk({ statut: "ok" });
    if (u.includes("/celcat/saisie") && methode === "PATCH") {
      etat = { ...etat, saisie_active: JSON.parse(String(init?.body)).active };
      return jsonOk(etat);
    }
    if (u.includes("/celcat/worker") && methode === "PATCH") {
      etat = { ...etat, worker_actif: JSON.parse(String(init?.body)).actif };
      return jsonOk(etat);
    }
    if (u.includes("/celcat/valider")) {
      etat = { ...etat, semaines_validees: JSON.parse(String(init?.body)).semaines };
      return jsonOk(etat);
    }
    if (u.includes("/celcat/lancer-nuit")) return jsonOk(etat);
    if (u.includes("/celcat/etat")) return jsonOk(etat);
    return jsonKo(404, `route non simulée : ${u}`);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

const urls = (mock: ReturnType<typeof vi.fn>) => mock.mock.calls.map((c) => String(c[0]));

async function ouvrir(scenario?: Scenario) {
  const mock = serveur(scenario);
  render(<AdminCelcatView cadence={CADENCE} />);
  await screen.findByRole("heading", { level: 2, name: /écart|concorde|relevé/i });
  return mock;
}

beforeEach(() => {
  vi.mocked(confirmAsync).mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Écran Celcat — ce qu'on voit d'abord", () => {
  it("ouvre sur le verdict de la semaine EN COURS, par son indice et non sa position", async () => {
    const mock = await ouvrir();
    // La ligne en cours est en 3e position mais porte l'indice 7.
    expect(urls(mock).some((u) => u.includes("/celcat/comparaison?semaine=7"))).toBe(true);
    expect((screen.getByRole("combobox", { name: /semaine comparée/i }) as HTMLSelectElement).value).toBe("7");
    expect(screen.queryByRole("option", { name: /vacances/ })).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: /1 écart avec Celcat/ })).toBeTruthy();
  });

  it("n'affiche plus d'onglets : réglages et activité sont repliés sous le verdict", async () => {
    await ouvrir();
    expect(screen.queryByRole("button", { name: /^pilotage$/i })).toBeNull();
    expect(screen.getByTestId("reglages-celcat").hasAttribute("open")).toBe(false);
    expect(screen.getByTestId("journal-celcat").hasAttribute("open")).toBe(false);
  });

  it("donne l'état de l'écriture, du worker et du relevé avec un mot chacun", async () => {
    await ouvrir();
    expect(within(screen.getByTestId("signal-ecriture")).getByText("active")).toBeTruthy();
    expect(within(screen.getByTestId("signal-worker")).getByText("actif")).toBeTruthy();
    expect(within(screen.getByTestId("signal-releve")).getByText("à jour")).toBeTruthy();
  });

  it("annonce une concordance complète en tête", async () => {
    await ouvrir({ lignes: [IDENTIQUE] });
    expect(screen.getByRole("heading", { level: 2, name: /tout concorde avec celcat/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^corriger/i })).toBeNull();
  });

  it("propose de relire Celcat, et non de corriger, sur un relevé périmé", async () => {
    await ouvrir({ releve: { perime: true, age_secondes: 3 * 3600 } });
    expect(screen.getByRole("heading", { level: 2, name: /trop ancien/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /relire celcat/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^corriger/i })).toBeNull();
  });

  it("efface la comparaison d'une semaine quand on passe à la suivante", async () => {
    const mock = await ouvrir();
    fireEvent.click(screen.getByRole("button", { name: /semaine suivante/i }));
    await waitFor(() => expect(urls(mock).some((u) => u.includes("/celcat/comparaison?semaine=8"))).toBe(true));
  });
});

describe("Corriger va jusqu'à la vérification", () => {
  it("met en file SANS suppression, attend le worker, demande un relevé, puis relit", async () => {
    const mock = await ouvrir({ lignes: [ECART, IDENTIQUE], lignesApres: [IDENTIQUE] });

    fireEvent.click(screen.getByRole("button", { name: /corriger l’écart/i }));

    // LE TEST DU RETOUR UTILISATEUR : sans un second clic, l'écran finit sur
    // le résultat vérifié — et plus sur les écarts d'avant.
    await screen.findByRole("heading", { level: 2, name: /tout concorde avec celcat/i }, { timeout: 3000 });
    const u = urls(mock);
    expect(u.some((x) => x.includes("/comparaison/corriger?semaine=7&supprimer=false"))).toBe(true);
    const corriger = u.findIndex((x) => x.includes("/comparaison/corriger"));
    const demande = u.findIndex((x) => x.includes("/instantane/rafraichir"));
    expect(demande).toBeGreaterThan(corriger);
    expect(screen.getByTestId("suivi-boucle").textContent).toMatch(/vérifié sur un relevé tout frais/i);
  });

  it("dit où l'attente s'est arrêtée quand le worker ne repasse pas, sans rien perdre", async () => {
    await ouvrir({ workerMuet: true });
    fireEvent.click(screen.getByRole("button", { name: /corriger l’écart/i }));
    await waitFor(
      () => expect(screen.getByTestId("suivi-boucle").textContent).toMatch(/restent en file/),
      { timeout: 3000 },
    );
  });

  it("dit ce qui attendait déjà, pour qu'on cesse de recliquer", async () => {
    await ouvrir({ correction: { total: 0, deja_en_file: 3 } });
    fireEvent.click(screen.getByRole("button", { name: /corriger l’écart/i }));
    await waitFor(() =>
      expect(screen.getByTestId("correction-deja-en-file").textContent).toMatch(/recliquer n’y change rien/),
    );
  });

  it("nomme les écarts non traduits, groupés par cause", async () => {
    const abandon = (sid: string) => ({
      statut: "ecart", session_id: sid, course_code: "WRA507D", event_id: null, groupe: null,
      raison: "event_id_absent", explication: "l'évènement Celcat n'a pas d'identifiant",
    });
    await ouvrir({ correction: { total: 0, deja_en_file: 0, abandonnes: [abandon("s-1"), abandon("s-2")] } });
    fireEvent.click(screen.getByRole("button", { name: /corriger l’écart/i }));
    const repli = await screen.findByTestId("correction-abandonnes");
    expect(repli.textContent).toContain("2 écarts non traduits");
    expect(repli.textContent).toContain("1 cause");
    expect(repli.textContent).toContain("s-1, s-2");
  });

  it("montre le refus du serveur près du bouton, sans effacer le verdict", async () => {
    const mock = await ouvrir();
    const base = mock.getMockImplementation()!;
    mock.mockImplementation((url: string, init?: RequestInit) =>
      String(url).includes("/comparaison/corriger")
        ? jsonKo(409, "Le worker Celcat est en pause.")
        : base(url, init),
    );
    fireEvent.click(screen.getByRole("button", { name: /corriger l’écart/i }));
    await waitFor(() => expect(screen.getByTestId("suivi-boucle").textContent).toContain("worker Celcat est en pause"));
    expect(screen.getByRole("heading", { level: 2, name: /1 écart avec Celcat/ })).toBeTruthy();
  });
});

describe("Les suppressions restent humaines", () => {
  it("liste les évènements en trop avant de proposer de les supprimer", async () => {
    await ouvrir({ lignes: [ECART, EN_TROP] });
    const panneau = screen.getByRole("region", { name: /1 évènement en trop/i });
    expect(panneau.textContent).toContain("WR402 Anglais");
    expect(panneau.textContent).toContain("mercredi 16/09");
    expect(panneau.textContent).toContain("#1953820");
  });

  it("ne supprime rien si la confirmation est refusée", async () => {
    vi.mocked(confirmAsync).mockResolvedValue(false);
    const mock = await ouvrir({ lignes: [ECART, EN_TROP] });
    fireEvent.click(screen.getByRole("button", { name: /supprimer cet évènement/i }));
    await waitFor(() => expect(confirmAsync).toHaveBeenCalled());
    expect(urls(mock).some((u) => u.includes("/comparaison/corriger"))).toBe(false);
  });

  it("répète la liste dans la confirmation, puis corrige avec les suppressions", async () => {
    vi.mocked(confirmAsync).mockResolvedValue(true);
    const mock = await ouvrir({ lignes: [ECART, EN_TROP] });
    fireEvent.click(screen.getByRole("button", { name: /supprimer cet évènement/i }));
    await waitFor(() =>
      expect(urls(mock).some((u) => u.includes("/comparaison/corriger?semaine=7") && !u.includes("supprimer=false"))).toBe(true),
    );
    const [texte, options] = vi.mocked(confirmAsync).mock.calls[0];
    expect(texte).toContain("WR402 Anglais");
    expect(options?.confirmLabel).toMatch(/supprimer 1 évènement/i);
  });
});

describe("Détail séance par séance", () => {
  it("montre les deux côtés d'un écart avec son verdict en mot", async () => {
    await ouvrir({ lignes: [ECART, IDENTIQUE] });
    const detail = screen.getByTestId("comparaison-celcat");
    expect(detail.hasAttribute("open")).toBe(true);
    const tableau = within(detail).getByRole("table");
    expect(tableau.textContent).toContain("mardi 15/09 15:30");
    expect(tableau.textContent).toContain("mardi 15/09 13:50");
    expect(within(tableau).getByText("À modifier")).toBeTruthy();
  });

  it("replie les séances identiques derrière un compte", async () => {
    await ouvrir({ lignes: [ECART, IDENTIQUE] });
    expect(screen.queryByTestId("comparaison-identiques")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /afficher 1 séance identique/i }));
    expect(screen.getByTestId("comparaison-identiques").textContent).toContain("lundi 14/09");
  });
});

describe("Réglages", () => {
  it("demande confirmation, avec le nombre de corrections perdues, avant de couper l'écriture", async () => {
    vi.mocked(confirmAsync).mockResolvedValue(false);
    const mock = await ouvrir();
    fireEvent.click(screen.getByRole("switch", { name: /écriture dans celcat/i }));
    await waitFor(() => expect(confirmAsync).toHaveBeenCalled());
    expect(String(vi.mocked(confirmAsync).mock.calls[0][0])).toMatch(/3 corrections en attente seront abandonnées/);
    expect(urls(mock).some((u) => u.includes("/celcat/saisie"))).toBe(false);
  });

  it("réactive l'écriture sans confirmation — c'est le geste sûr", async () => {
    const mock = await ouvrir({ etat: { saisie_active: false } });
    fireEvent.click(screen.getByRole("switch", { name: /écriture dans celcat/i }));
    await waitFor(() => expect(urls(mock).some((u) => u.includes("/celcat/saisie"))).toBe(true));
    expect(confirmAsync).not.toHaveBeenCalled();
  });

  it("met le worker en pause sans jamais toucher à l'écriture, et le dit", async () => {
    const mock = await ouvrir();
    const interrupteur = screen.getByRole("switch", { name: /worker/i });
    expect(interrupteur.getAttribute("aria-describedby")).toBeTruthy();
    fireEvent.click(interrupteur);
    await waitFor(() => expect(urls(mock).some((u) => u.includes("/celcat/worker"))).toBe(true));
    expect(urls(mock).some((u) => u.includes("/celcat/saisie"))).toBe(false);
    await screen.findByText(/la file est conservée/i);
  });

  it("nomme les semaines par leur date et dit l'état de chacune en toutes lettres", async () => {
    await ouvrir();
    // Pastille 8 = indice 7 = « Semaine 11 (en cours) ».
    const envoyee = screen.getByRole("button", { name: /^semaine 11 \(en cours\), enregistrée$/i });
    expect(envoyee.getAttribute("aria-pressed")).toBe("true");
    expect(envoyee.textContent).toContain("enregistrée");
    const passee = screen.getByRole("button", { name: /^semaine 1, passée$/i });
    expect(passee.getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByRole("button", { name: /^semaine 5, planning complet$/i })).toBeTruthy();
  });

  it("dit qu'une semaine décochée va sortir du lot", async () => {
    await ouvrir();
    fireEvent.click(screen.getByRole("button", { name: /^semaine 11 \(en cours\), enregistrée$/i }));
    expect(screen.getByRole("button", { name: /^semaine 11 \(en cours\), retirée$/i })).toBeTruthy();
  });

  it("enregistre la sélection puis l'envoie", async () => {
    const mock = await ouvrir();
    fireEvent.click(screen.getByRole("button", { name: /^semaine 12 \(suivante\)$/i }));
    fireEvent.click(screen.getByRole("button", { name: /envoyer maintenant/i }));
    await waitFor(() => expect(urls(mock).some((u) => u.includes("/celcat/lancer-nuit"))).toBe(true));
    const corps = mock.mock.calls.find((c) => String(c[0]).includes("/celcat/valider"))?.[1]?.body;
    expect(JSON.parse(String(corps)).semaines).toEqual([8, 9]);
  });

  it("explique pourquoi « Envoyer maintenant » est indisponible écriture coupée", async () => {
    await ouvrir({ etat: { saisie_active: false } });
    expect(screen.getByRole("button", { name: /envoyer maintenant/i })).toBeDisabled();
    expect(screen.getByText(/attend que l’écriture dans celcat soit active/i)).toBeTruthy();
  });

  it("ajoute ou ignore un cours présent seulement dans Celcat", async () => {
    const mock = await ouvrir({ extras: [{ id: "extra-1", statut: "ouvert", course_code: "WR106", libelle: "WR106 Expression" }] });
    fireEvent.click(screen.getByRole("button", { name: /ajouter WR106 Expression/i }));
    await waitFor(() => expect(urls(mock).some((u) => u.includes("/extras/extra-1/ajouter"))).toBe(true));
    await waitFor(() => expect(screen.queryByRole("button", { name: /ajouter WR106/i })).toBeNull());
  });
});

describe("Activité récente", () => {
  const LOGS = [
    { kind: "created", session_id: "s-a", at: "2026-09-16T08:42:00" },
    { kind: "echec", session_id: "s-b", motif: "groupe introuvable", repetitions: 87 },
  ];

  it("résume écritures et échecs sans avoir à ouvrir", async () => {
    await ouvrir({ logs: LOGS });
    const resume = screen.getByTestId("journal-celcat").querySelector("summary")!;
    expect(resume.textContent).toContain("1 écriture");
    expect(resume.textContent).toContain("1 échec ou blocage");
  });

  it("range chaque écriture, avec répétitions, motif et horodatage visible", async () => {
    await ouvrir({ logs: LOGS });
    expect(screen.getByTestId("colonne-created").textContent).toContain("16/09 à 08:42");
    const echecs = screen.getByTestId("colonne-echec");
    expect(echecs.textContent).toContain("87×");
    expect(echecs.textContent).toContain("groupe introuvable");
    // Le bouton Copier n'est plus DANS le titre, qui se lisait « Créées 1 Copier ».
    expect(within(echecs).getByRole("heading").textContent).not.toContain("Copier");
    expect(within(screen.getByTestId("colonne-deleted")).queryByRole("button", { name: /copier/i })).toBeNull();
  });
});

describe("Système", () => {
  it("dit que l'état de la file est indisponible au lieu de le masquer", async () => {
    const mock = serveur();
    const base = mock.getMockImplementation()!;
    mock.mockImplementation((url: string, init?: RequestInit) =>
      String(url).includes("/celcat/file") ? jsonKo(500, "panne") : base(url, init),
    );
    await act(async () => {
      render(<AdminCelcatView cadence={CADENCE} />);
    });
    await waitFor(() => expect(screen.getByTestId("etat-file-celcat").textContent).toMatch(/indisponible/));
  });
});
