/**
 * Vue « Occupé ailleurs » (02/10/2026, retour de Jules : l'écran Celcat →
 * Occupations hors MMI était « illisible, à mettre autre part »). Contrat :
 * `.orchestrator/contract-occupe-ailleurs.md`.
 *
 * Conventions que le test suppose (reprises de ContraintesView) :
 * - la pastille « filtre posé » porte un `sr-only` « (retirer le filtre) » ;
 * - le choix d'une ressource passe par le `<select>` « Ressource » s'il est
 *   rendu, sinon par un bouton de l'annuaire portant le libellé ;
 * - la carte des conflits a une colonne « Quand », celle des occupations une
 *   colonne « Horaire » : c'est ainsi que le test retrouve chaque tableau ;
 * - libellé d'une salle : `payload.rooms[].label` ; nom d'un enseignant :
 *   `payload.teacherLabels[code]` ; à défaut, le code.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OccupationsHorsMmi } from "../api/client";
import { catalogRoom, emptyPayload } from "../test/payloadFixture";
import type { AppPayload, ConflitOccupationExterne, OccupationExterne, OccupationsExternesPayload } from "../types/app";

const mocks = vi.hoisted(() => ({
  fetchOccupationsHorsMmi: vi.fn(),
  rafraichirOccupationsHorsMmi: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  fetchOccupationsHorsMmi: mocks.fetchOccupationsHorsMmi,
  rafraichirOccupationsHorsMmi: mocks.rafraichirOccupationsHorsMmi,
}));

import { OccupeAilleursView } from "./OccupeAilleursView";

function occ(patch: Partial<OccupationExterne>): OccupationExterne {
  return {
    t: "salle",
    code: "h018",
    w: 3,
    d: 3,
    s: [0],
    date: "2026-10-08",
    debut: "08:00",
    fin: "10:00",
    dep: "TC",
    lib: "TC101 Anglais",
    cat: "[CM]",
    ...patch,
  };
}

// Salles : h018 (3), a018 (1), b002 (1) -> 3 distinctes, 5 créneaux.
// Enseignants : AFR (2), RHU (1) -> 2 distincts, 3 créneaux.
const OCCUPATIONS: OccupationExterne[] = [
  occ({ t: "salle", code: "h018", date: "2026-10-08", debut: "08:00", fin: "10:00", dep: "TC", lib: "TC101 Anglais" }),
  occ({ t: "salle", code: "h018", date: "2026-10-12", debut: "14:00", fin: "16:00", dep: "", lib: "Réunion de service" }),
  occ({ t: "salle", code: "h018", date: "2026-10-13", debut: "09:00", fin: "11:00", dep: "TC", lib: "TC102 Maths" }),
  occ({ t: "salle", code: "a018", date: "2026-10-09", debut: "08:00", fin: "10:00", dep: "CJ", lib: "JR307 Droit fiscal 1" }),
  occ({ t: "salle", code: "b002", date: "2026-10-14", debut: "10:00", fin: "12:00", dep: "", lib: "Concours" }),
  occ({ t: "enseignant", code: "AFR", date: "2026-10-08", debut: "08:00", fin: "10:00", dep: "TC", lib: "Conseil de département" }),
  occ({ t: "enseignant", code: "AFR", date: "2026-10-15", debut: "14:00", fin: "16:00", dep: "CJ", lib: "CJ201 Contrats" }),
  occ({ t: "enseignant", code: "RHU", date: "2026-10-16", debut: "08:00", fin: "10:00", dep: "", lib: "Jury de soutenance" }),
];

function conflit(patch: Partial<ConflitOccupationExterne>): ConflitOccupationExterne {
  return {
    seance_id: "s1",
    course_code: "WR101",
    nom: "Culture numérique",
    type: "TD",
    semaine: 3,
    jour: 3,
    creneau: 0,
    groupes: ["but1-td-ab"],
    enseignants: ["AFR"],
    ressource_type: "salle",
    ressource: "h018",
    message: "MESSAGE-C1 H.018 occupée jeudi par CJ",
    ressource_libelle: "H.018 (Amphi MMI)",
    date: "2026-10-08",
    debut: "08:00",
    fin: "10:00",
    departement: "CJ",
    categorie: "[CM]",
    intitule: "JR307 Droit fiscal 1",
    ...patch,
  };
}

const C1 = conflit({});
const C2 = conflit({
  seance_id: "s2",
  course_code: "WR202",
  nom: "Web avancé",
  type: "TP",
  ressource_type: "enseignant",
  ressource: "AFR",
  message: "MESSAGE-C2 AFR pris mardi",
  ressource_libelle: "Anthony Froli",
  date: "2026-10-06",
  debut: "14:00",
  fin: "16:00",
  departement: "",
  categorie: "Réunion",
  intitule: "",
});

function externes(patch: Partial<OccupationsExternesPayload> = {}): OccupationsExternesPayload {
  return {
    releveLe: "2026-10-02T12:20:00+02:00",
    ageSecondes: 3600,
    absent: false,
    perime: false,
    fraicheurHeures: 6,
    strict: false,
    erreur: null,
    occupations: OCCUPATIONS,
    conflits: [C1, C2],
    ...patch,
  };
}

function payloadAvec(patch: Partial<OccupationsExternesPayload> | null = {}): AppPayload {
  return emptyPayload({
    rooms: [
      catalogRoom("h018", { label: "H.018 (Amphi MMI)" }),
      catalogRoom("a018", { label: "A.018" }),
      catalogRoom("b002", { label: "B.002" }),
    ],
    teacherLabels: { AFR: "Anthony Froli", RHU: "Émilie Rhu" },
    groupLabels: { "but1-td-ab": "BUT1 TD AB" },
    ...(patch === null ? {} : { occupationsExternes: externes(patch) }),
  });
}

function rendre(payload: AppPayload, options: { estAdmin?: boolean; setRoute?: () => void } = {}) {
  const setRoute = options.setRoute ?? vi.fn();
  render(<OccupeAilleursView payload={payload} setRoute={setRoute} estAdmin={options.estAdmin ?? false} />);
  return setRoute;
}

function tableAvecEntete(entete: string): HTMLElement {
  const t = screen.getAllByRole("table").find((x) => within(x).queryByRole("columnheader", { name: entete }));
  if (!t) throw new Error(`Aucun tableau avec la colonne « ${entete} »`);
  return t;
}
const tableConflits = () => tableAvecEntete("Quand");
const tableOccupations = () => tableAvecEntete("Horaire");
const lignes = (t: HTMLElement) => within(t).getAllByRole("row").length - 1;

function tuile(nom: RegExp): HTMLElement {
  return within(screen.getByRole("region", { name: "Sommaire des occupations hors MMI" })).getByRole("button", { name: nom });
}

function choisirRessource(libelle: RegExp) {
  const select = screen.queryByRole("combobox", { name: "Ressource" });
  if (select) {
    const option = within(select).getByRole("option", { name: libelle }) as HTMLOptionElement;
    fireEvent.change(select, { target: { value: option.value } });
  } else {
    fireEvent.click(screen.getByRole("button", { name: libelle }));
  }
}

const RELEVE_ADMIN: OccupationsHorsMmi = {
  releveLe: "2026-10-02T12:20:00+02:00",
  ageSecondes: 3600,
  absent: false,
  perime: false,
  fraicheurHeures: 6,
  strict: false,
  erreur: null,
  demandeEnCours: false,
  lectureActive: true,
  periode: { du: "2026-09-28", au: "2027-07-31" },
  base: "URCA_2026",
  ignores: { "hors période": 4, "sans salle": 2 },
  erreurs: [],
  ressources: [
    { type: "salle", code: "h018", libelle: "H.018 (Amphi MMI)", celcat: "H018 Amphi", celcat_id: 41, trouvee: true, nombre: 3 },
    { type: "salle", code: "a018", libelle: "A.018", celcat: "A018 Salle info", celcat_id: null, trouvee: false, nombre: 0 },
  ],
  evenements: [],
  conflits: [],
};

beforeEach(() => {
  mocks.fetchOccupationsHorsMmi.mockReset();
  mocks.rafraichirOccupationsHorsMmi.mockReset();
  mocks.fetchOccupationsHorsMmi.mockResolvedValue(RELEVE_ADMIN);
  mocks.rafraichirOccupationsHorsMmi.mockResolvedValue({ demande: true, message: "Relecture demandée au robot." });
});

describe("OccupeAilleursView — sommaire", () => {
  it("should show conflicts, distinct rooms, distinct teachers and the age of the last reading in four tiles", () => {
    rendre(payloadAvec());
    const conflits = within(tuile(/Séances en conflit/));
    expect(conflits.getByText("2")).toBeInTheDocument();
    expect(conflits.getByText("à déplacer ou à forcer")).toBeInTheDocument();
    const salles = within(tuile(/Salles prises ailleurs/));
    expect(salles.getByText("3")).toBeInTheDocument();
    expect(salles.getByText("5 créneaux")).toBeInTheDocument();
    const profs = within(tuile(/Enseignants pris ailleurs/));
    expect(profs.getByText("2")).toBeInTheDocument();
    expect(profs.getByText("3 créneaux")).toBeInTheDocument();
    const sommaire = within(screen.getByRole("region", { name: "Sommaire des occupations hors MMI" }));
    expect(sommaire.getByText("Dernier relevé Celcat")).toBeInTheDocument();
    expect(sommaire.getByText("il y a 1 h")).toBeInTheDocument();
  });

  it("should say there is no conflict in the tile when the list is empty", () => {
    rendre(payloadAvec({ conflits: [] }));
    const conflits = within(tuile(/Séances en conflit/));
    expect(conflits.getByText("0")).toBeInTheDocument();
    expect(conflits.getByText("aucune")).toBeInTheDocument();
  });

  it("should filter the occupations on rooms when the rooms tile is clicked, and lift the filter on a second click", () => {
    rendre(payloadAvec());
    expect(lignes(tableOccupations())).toBe(8);
    fireEvent.click(tuile(/Salles prises ailleurs/));
    expect(tuile(/Salles prises ailleurs/)).toHaveAttribute("aria-pressed", "true");
    expect(lignes(tableOccupations())).toBe(5);
    fireEvent.click(tuile(/Salles prises ailleurs/));
    expect(tuile(/Salles prises ailleurs/)).toHaveAttribute("aria-pressed", "false");
    expect(lignes(tableOccupations())).toBe(8);
  });

  it("should filter the occupations on teachers when the teachers tile is clicked, and lift the filter on a second click", () => {
    rendre(payloadAvec());
    fireEvent.click(tuile(/Enseignants pris ailleurs/));
    expect(tuile(/Enseignants pris ailleurs/)).toHaveAttribute("aria-pressed", "true");
    expect(lignes(tableOccupations())).toBe(3);
    fireEvent.click(tuile(/Enseignants pris ailleurs/));
    expect(lignes(tableOccupations())).toBe(8);
  });
});

describe("OccupeAilleursView — séances en conflit", () => {
  it("should show the separate fields of a conflict and not the sentence", () => {
    rendre(payloadAvec());
    const table = tableConflits();
    const ligne = within(table).getByRole("row", { name: /WR101/ });
    expect(within(ligne).getByText("jeu. 8 oct.")).toBeInTheDocument();
    expect(within(ligne).getByText("08h00–10h00")).toBeInTheDocument();
    expect(within(ligne).getByText("Salle")).toBeInTheDocument();
    expect(within(ligne).getByText("H.018 (Amphi MMI)")).toBeInTheDocument();
    expect(within(ligne).getByText("CJ")).toBeInTheDocument();
    expect(within(ligne).getByText("JR307 Droit fiscal 1")).toBeInTheDocument();
    expect(screen.queryByText(/MESSAGE-C1/)).not.toBeInTheDocument();
    expect(screen.queryByText(/MESSAGE-C2/)).not.toBeInTheDocument();
  });

  it("should tag a teacher conflict, write Administration for an empty department and fall back on the category", () => {
    rendre(payloadAvec());
    const ligne = within(tableConflits()).getByRole("row", { name: /WR202/ });
    expect(within(ligne).getByText("Enseignant")).toBeInTheDocument();
    expect(within(ligne).getByText("Anthony Froli")).toBeInTheDocument();
    expect(within(ligne).getByText("Administration")).toBeInTheDocument();
    expect(within(ligne).getByText("Réunion")).toBeInTheDocument();
    expect(within(ligne).getByText("mar. 6 oct.")).toBeInTheDocument();
    expect(within(ligne).getByText("14h00–16h00")).toBeInTheDocument();
  });

  it("should list the conflicts by date then start time", () => {
    rendre(payloadAvec());
    const rangees = within(tableConflits()).getAllByRole("row").slice(1);
    expect(rangees[0]).toHaveTextContent("WR202");
    expect(rangees[1]).toHaveTextContent("WR101");
  });

  it("should fall back on the message when the separate fields are missing (older server)", () => {
    const ancien = conflit({
      ressource_libelle: undefined,
      date: undefined,
      debut: undefined,
      fin: undefined,
      departement: undefined,
      categorie: undefined,
      intitule: undefined,
      message: "H.018 occupée jeudi 8 oct. par TC",
    });
    rendre(payloadAvec({ conflits: [ancien] }));
    const ligne = within(tableConflits()).getByRole("row", { name: /WR101/ });
    expect(within(ligne).getByText(/H\.018 occupée jeudi 8 oct\. par TC/)).toBeInTheDocument();
    expect(within(ligne).queryByText("Administration")).not.toBeInTheDocument();
  });

  it("should say so when no placed session conflicts with an occupation", () => {
    rendre(payloadAvec({ conflits: [] }));
    expect(screen.getByText("Aucune séance placée n'est en conflit avec une occupation hors MMI.")).toBeInTheDocument();
  });

  it("should call setRoute with a destination when Ouvrir is clicked", () => {
    const setRoute = vi.fn();
    rendre(payloadAvec(), { setRoute });
    const ligne = within(tableConflits()).getByRole("row", { name: /WR101/ });
    fireEvent.click(within(ligne).getByRole("button", { name: /Ouvrir/ }));
    expect(setRoute).toHaveBeenCalledTimes(1);
    expect(setRoute).toHaveBeenCalledWith(expect.objectContaining({ vue: expect.any(String) }));
  });
});

describe("OccupeAilleursView — salles et enseignants pris ailleurs", () => {
  it("should show date, schedule, resource, department and title for each occupation", () => {
    rendre(payloadAvec());
    const ligne = within(tableOccupations()).getByRole("row", { name: /Réunion de service/ });
    expect(within(ligne).getByText("lun. 12 oct.")).toBeInTheDocument();
    expect(within(ligne).getByText("14h00–16h00")).toBeInTheDocument();
    expect(within(ligne).getByText("H.018 (Amphi MMI)")).toBeInTheDocument();
    expect(within(ligne).getByText("Administration")).toBeInTheDocument();
  });

  it("should filter the table when a resource is chosen, and lift it with the crossed pill", () => {
    rendre(payloadAvec());
    choisirRessource(/H\.018/);
    expect(lignes(tableOccupations())).toBe(3);
    expect(within(tableOccupations()).queryByRole("columnheader", { name: "Ressource" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retirer le filtre/ }));
    expect(lignes(tableOccupations())).toBe(8);
    expect(screen.queryByRole("button", { name: /retirer le filtre/ })).not.toBeInTheDocument();
  });

  it("should filter by text, so that tc finds the TC department", () => {
    rendre(payloadAvec());
    fireEvent.change(screen.getByPlaceholderText("Filtrer : salle, enseignant, département…"), { target: { value: "tc" } });
    const table = tableOccupations();
    expect(lignes(table)).toBe(3);
    expect(within(table).queryByText("Réunion de service")).not.toBeInTheDocument();
    expect(within(table).getByText("TC102 Maths")).toBeInTheDocument();
  });

  it("should show only the first 200 rows and say so when there are more", () => {
    const beaucoup = Array.from({ length: 205 }, (_, i) =>
      occ({ code: "h018", date: "2026-11-02", debut: `${String(7 + (i % 12)).padStart(2, "0")}:00`, lib: `Créneau ${i}` }),
    );
    rendre(payloadAvec({ occupations: beaucoup, conflits: [] }));
    expect(lignes(tableOccupations())).toBe(200);
    expect(screen.getByText("200 premières affichées — préciser le filtre.")).toBeInTheDocument();
  });

  it("should not show the limit sentence when everything fits", () => {
    rendre(payloadAvec());
    expect(screen.queryByText(/premières affichées/)).not.toBeInTheDocument();
  });
});

describe("OccupeAilleursView — états", () => {
  it("should show the empty state without any table when the reading is absent", () => {
    rendre(payloadAvec({ absent: true, occupations: [], conflits: [], releveLe: null, ageSecondes: null }));
    expect(screen.getByText(/Aucun relevé Celcat pour l'instant\./)).toBeInTheDocument();
    expect(screen.getByText(/Rien n'est pris en compte\./)).toBeInTheDocument();
    expect(screen.queryAllByRole("table")).toHaveLength(0);
    expect(within(screen.getByRole("region", { name: "Sommaire des occupations hors MMI" })).getByText("—")).toBeInTheDocument();
    expect(screen.getByText("aucun relevé : rien n'est appliqué")).toBeInTheDocument();
  });

  it("should show the same empty state when the server does not send occupationsExternes", () => {
    rendre(payloadAvec(null));
    expect(screen.getByText(/Aucun relevé Celcat pour l'instant\./)).toBeInTheDocument();
    expect(screen.queryAllByRole("table")).toHaveLength(0);
  });

  it("should warn with a banner when the reading is old", () => {
    rendre(payloadAvec({ perime: true, ageSecondes: 9 * 3600 }));
    expect(
      screen.getByText("Relevé ancien (il y a 9 h) : les occupations restent appliquées telles quelles."),
    ).toBeInTheDocument();
  });

  it("should not show the old-reading banner when the reading is fresh", () => {
    rendre(payloadAvec());
    expect(screen.queryByText(/Relevé ancien/)).not.toBeInTheDocument();
  });
});

describe("OccupeAilleursView — carte Relevé Celcat (administrateurs)", () => {
  it("should hide the card and never call the server when the user is not an administrator", () => {
    rendre(payloadAvec(), { estAdmin: false });
    expect(screen.queryByRole("heading", { name: "Relevé Celcat" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Relire maintenant" })).not.toBeInTheDocument();
    expect(mocks.fetchOccupationsHorsMmi).not.toHaveBeenCalled();
  });

  it("should load the reading, list the missing resources and the discarded reasons for an administrator", async () => {
    rendre(payloadAvec(), { estAdmin: true });
    expect(screen.getByRole("heading", { name: "Relevé Celcat" })).toBeInTheDocument();
    expect(await screen.findByText("Introuvables dans Celcat")).toBeInTheDocument();
    expect(mocks.fetchOccupationsHorsMmi).toHaveBeenCalled();
    expect(screen.getByText(/A018 Salle info/)).toBeInTheDocument();
    expect(screen.getByText("Pas de fiche dans Celcat cette année : leurs occupations ne peuvent pas être lues.")).toBeInTheDocument();
    expect(screen.queryByText(/H018 Amphi/)).not.toBeInTheDocument();
    expect(screen.getByText(/URCA_2026/)).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /hors période/ })).toHaveTextContent("4");
    expect(screen.getByRole("row", { name: /sans salle/ })).toHaveTextContent("2");
  });

  it("should not list missing resources when every resource was found", async () => {
    mocks.fetchOccupationsHorsMmi.mockResolvedValue({ ...RELEVE_ADMIN, ressources: [RELEVE_ADMIN.ressources[0]] });
    rendre(payloadAvec(), { estAdmin: true });
    await screen.findByText(/URCA_2026/);
    expect(screen.queryByText("Introuvables dans Celcat")).not.toBeInTheDocument();
  });

  it("should ask the robot to read again and show the message it returns", async () => {
    rendre(payloadAvec(), { estAdmin: true });
    await screen.findByText("Introuvables dans Celcat");
    fireEvent.click(screen.getByRole("button", { name: "Relire maintenant" }));
    expect(await screen.findByText("Relecture demandée au robot.")).toBeInTheDocument();
    expect(mocks.rafraichirOccupationsHorsMmi).toHaveBeenCalledTimes(1);
  });

  it("should disable the read-again button when the reading is switched off", async () => {
    mocks.fetchOccupationsHorsMmi.mockResolvedValue({ ...RELEVE_ADMIN, lectureActive: false });
    rendre(payloadAvec(), { estAdmin: true });
    await waitFor(() => expect(screen.getByRole("button", { name: "Relire maintenant" })).toBeDisabled());
    expect(mocks.rafraichirOccupationsHorsMmi).not.toHaveBeenCalled();
  });

  it("should still show the card for an administrator when there is no reading yet", async () => {
    rendre(payloadAvec(null), { estAdmin: true });
    expect(screen.getByRole("heading", { name: "Relevé Celcat" })).toBeInTheDocument();
    await waitFor(() => expect(mocks.fetchOccupationsHorsMmi).toHaveBeenCalled());
  });
});
