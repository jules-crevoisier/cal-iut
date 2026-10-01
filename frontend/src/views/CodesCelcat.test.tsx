/**
 * Référence → « Codes Celcat » (30/09/2026, « un onglet [...] où on pouvait
 * renseigner les codes Celcat pour les cours et les salles aussi »).
 *
 * Sous-onglets par famille avec le nombre de lignes sans code, filtre « Sans
 * code », saisie en ligne (Entrée enregistre, erreur sous le champ,
 * suggestions relevées dans Celcat), « Revenir à la valeur du fichier »,
 * lecture seule pour un compte non administrateur, lien vers une ligne.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CodesCelcat as DonneesCodes, LigneCodeCelcat } from "../api/client";
import { ContexteDroits, type RoleCompte } from "../contexts/Droits";
import { emptyPayload } from "../test/payloadFixture";
import { confirmAsync } from "../utils/confirmDialog";
import { CodesCelcat } from "./CodesCelcat";
import { ReferenceView } from "./ReferenceView";

vi.mock("../utils/confirmDialog", () => ({ confirmAsync: vi.fn() }));

function ligne(p: Partial<LigneCodeCelcat> & Pick<LigneCodeCelcat, "cle">): LigneCodeCelcat {
  return {
    libelle: p.cle,
    semestre: null,
    parcours: null,
    type_salle: null,
    capacite: null,
    nb_seances: 0,
    code: null,
    code_connu: null,
    origine: "manquant",
    origine_detail: null,
    code_maquette: null,
    motif_sans_code: null,
    saisi_le: null,
    saisi_par: null,
    valeur_avant: null,
    alerte: null,
    avertissement: null,
    note: null,
    modifiable: true,
    peut_revenir: false,
    peut_marquer_sans_code: false,
    peut_retirer_sans_code: false,
    ...p,
  };
}

function donnees(admin: boolean): DonneesCodes {
  const m = admin;
  // Droits calculés comme le serveur (`api/codes_celcat.py::lister`).
  const droits = (l: LigneCodeCelcat, famille: string): LigneCodeCelcat => ({
    ...l,
    modifiable: m && famille !== "groupes" && l.code_connu === null && l.origine !== "voulu" && l.origine !== "regle",
    peut_revenir: m && l.origine === "appli",
    peut_marquer_sans_code: m && famille !== "groupes" && l.origine === "manquant",
    peut_retirer_sans_code: m && l.origine === "voulu" && l.origine_detail === "appli",
    saisi_par: m ? l.saisi_par : null,
  });
  const bloc = (famille: DonneesCodes["familles"]["cours"]["famille"], lignes: LigneCodeCelcat[], suggestions: string[] = []) => ({
    famille,
    aide: `Aide ${famille}`,
    exemple: "X",
    modifiable: m && famille !== "groupes",
    total: lignes.length,
    sans_code: lignes.filter((l) => l.origine === "manquant").length,
    sans_code_bloquants: lignes.filter((l) => l.origine === "manquant" && l.nb_seances > 0).length,
    saisis: lignes.filter((l) => l.origine === "appli").length,
    voulus: lignes.filter((l) => l.origine === "voulu").length,
    maquette: lignes.filter((l) => l.origine === "maquette").length,
    suggestions,
    lignes: lignes.map((l) => droits(l, famille)),
  });
  return {
    revision: 1,
    admin,
    familles: {
      cours: bloc(
        "cours",
        [
          ligne({ cle: "WR101", libelle: "Anglais", semestre: "S1", parcours: "BUT1", nb_seances: 12, code: "TSBZ1M01", code_connu: "TSBZ1M01", origine: "fichier", origine_detail: "celcat.yaml" }),
          ligne({ cle: "WR100BU", libelle: "Jeu de piste BU", semestre: "S1", parcours: "BUT1", nb_seances: 12, origine: "voulu", origine_detail: "celcat.yaml", motif_sans_code: "Visite de la BU" }),
          ligne({ cle: "WRA401M", libelle: "Anglais S4", semestre: "S4", parcours: "BUT2-CREACOM-FC", code: "TSBZD01C", code_connu: "TSBZD01C", origine: "maquette", origine_detail: "maquette (corrigé M→C)", code_maquette: "TSBZD01M" }),
          ligne({ cle: "WRX99", libelle: "Atelier", semestre: "S1", parcours: "BUT1", nb_seances: 4 }),
          ligne({ cle: "WRX98", libelle: "Atelier 2", semestre: "S2", parcours: "BUT1", code_maquette: "TSBZ2M01", note: "Code de la maquette non repris : à faire confirmer (à redemander)." }),
          ligne({
            cle: "WRBU2",
            libelle: "Visite BU 2",
            semestre: "S1",
            parcours: "BUT1",
            nb_seances: 12,
            origine: "regle",
            origine_detail: "envoi sans module (règle)",
            motif_sans_code: "Visite de la BU en TD0 (Kyllian)",
            note: "Envoyé sans module : catégorie TD0, remarque « WRBU2 », département T_MMI T29 ; interventions de VMA.",
          }),
        ],
        ["TSBZ1M01", "TSBZ2M01"],
      ),
      salles: bloc(
        "salles",
        [
          ligne({ cle: "e102", libelle: "E.102", type_salle: "standard", capacite: 30, nb_seances: 30, code: "E.102", origine: "appli", saisi_le: "2026-09-30T08:00:00+00:00", saisi_par: "jules@iut.fr" }),
          ligne({ cle: "h018", libelle: "H.018 (Amphi MMI)", type_salle: "amphi", capacite: 150, nb_seances: 8 }),
        ],
        ["H.005", "H.006", "Amphi 3 MMI"],
      ),
      enseignants: bloc("enseignants", [ligne({ cle: "KBR", libelle: "Kyllian Bresson", code: "35543", code_connu: "35543", origine: "fichier", origine_detail: "celcat.yaml" })]),
      groupes: bloc("groupes", [ligne({ cle: "BUT MMI S1 CM", libelle: "BUT MMI S1 CM", code: "1661971", code_connu: "1661971", origine: "fichier", note: "Se règle dans celcat_groupes.yaml" })]),
    },
  };
}

function stubFetch(admin: boolean, put?: (corps: Record<string, string>) => { status: number; corps: unknown }) {
  const appels: { url: string; init?: RequestInit }[] = [];
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    appels.push({ url: String(url), init });
    const repondre = (status: number, corps: unknown) =>
      Promise.resolve({ ok: status < 400, status, statusText: "", json: async () => corps });
    const methode = (init?.method ?? "GET").toUpperCase();
    if (String(url).startsWith("/reference/codes-celcat") && methode === "GET") return repondre(200, donnees(admin));
    if (methode === "PUT") {
      const corps = JSON.parse(String(init?.body ?? "{}"));
      const r = put ? put(corps) : { status: 200, corps: { ...corps, origine: "appli", message: "ok", revision: 2 } };
      return repondre(r.status, r.corps);
    }
    if (methode === "DELETE") return repondre(200, { famille: "salles", cle: "h005", code: "H.005", origine: "fichier", message: "ok", revision: 3 });
    return repondre(200, {});
  });
  vi.stubGlobal("fetch", fetchMock);
  return appels;
}

function rendre(role: RoleCompte, props: Parameters<typeof CodesCelcat>[0] = {}) {
  const apresEnregistrement = vi.fn();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContexteDroits.Provider value={{ role, revision: 1, apresEnregistrement }}>{children}</ContexteDroits.Provider>
  );
  render(<CodesCelcat {...props} />, { wrapper });
  return { apresEnregistrement };
}

describe("Référence — Codes Celcat", () => {
  beforeEach(() => vi.mocked(confirmAsync).mockReset());
  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("montre un sous-onglet par famille, avec le nombre de lignes sans code (hors « voulu »)", async () => {
    stubFetch(true);
    rendre("admin");
    const cours = await screen.findByRole("tab", { name: /^Cours/ });
    expect(cours).toHaveAttribute("aria-selected", "true");
    expect(within(cours).getByText("2")).toBeInTheDocument();
    expect(within(screen.getByRole("tab", { name: /^Salles/ })).getByText("1")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Enseignants" })).toBeInTheDocument();
    expect(screen.getByText("WR101")).toBeInTheDocument();
    expect(screen.getByText(/Réservé aux administrateurs/)).toBeInTheDocument();
    expect(screen.getByText(/1 bloque Celcat/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /^Salles/ }));
    expect(screen.getByText("H.018 (Amphi MMI)")).toBeInTheDocument();
    expect(screen.queryByText("WR101")).not.toBeInTheDocument();
  });

  it("filtres « Sans code » et « Sans code (voulu) »", async () => {
    stubFetch(true);
    rendre("admin");
    await screen.findByText("WR101");
    fireEvent.click(screen.getByRole("button", { name: /^Sans code\d/ }));
    expect(screen.queryByText("WR101")).not.toBeInTheDocument();
    expect(screen.queryByText("WR100BU")).not.toBeInTheDocument();
    expect(screen.getByText("WRX99")).toBeInTheDocument();
    expect(screen.getByText("manquant — bloque Celcat")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filtrer les cours"), { target: { value: "atelier 2" } });
    expect(screen.queryByText("WRX99")).not.toBeInTheDocument();
    expect(screen.getByText("WRX98")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filtrer les cours"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /^Sans code \(voulu\)\d/ }));
    expect(screen.getByText("WR100BU")).toBeInTheDocument();
    expect(screen.getByText("Visite de la BU")).toBeInTheDocument();
    expect(screen.getByText("décidé dans celcat.yaml")).toBeInTheDocument();
    expect(screen.queryByText("WRX99")).not.toBeInTheDocument();
  });

  it("un cours « envoi sans module » montre sa règle, sans saisie possible", async () => {
    stubFetch(true);
    rendre("admin");
    const ligneRegle = (await screen.findByText("WRBU2")).closest("tr")!;
    expect(within(ligneRegle).getByText("envoi sans module (règle)")).toBeInTheDocument();
    expect(within(ligneRegle).getByText("sans module")).toBeInTheDocument();
    expect(within(ligneRegle).getByText(/catégorie TD0, remarque « WRBU2 », département T_MMI T29/)).toBeInTheDocument();
    expect(within(ligneRegle).getByText("se règle dans celcat.yaml")).toBeInTheDocument();
    expect(within(ligneRegle).queryByRole("button")).not.toBeInTheDocument();
    expect(within(ligneRegle).queryByText(/manquant/)).not.toBeInTheDocument();
    // Ni dans « Sans code », ni dans « Sans code (voulu) ».
    fireEvent.click(screen.getByRole("button", { name: /^Sans code\d/ }));
    expect(screen.queryByText("WRBU2")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Sans code \(voulu\)\d/ }));
    expect(screen.queryByText("WRBU2")).not.toBeInTheDocument();
  });

  it("un code connu (fichier, maquette) est verrouillé : pas de crayon", async () => {
    stubFetch(true);
    rendre("admin");
    await screen.findByText("WR101");
    expect(screen.queryByRole("button", { name: /Modifier — .*WR101/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Modifier — .*WRA401M/ })).not.toBeInTheDocument();
    expect(screen.getAllByLabelText("verrouillé")).toHaveLength(2);
    const ligneMaquette = screen.getByText("WRA401M").closest("tr")!;
    expect(within(ligneMaquette).getByText(/corrigé M→C \(maquette : TSBZD01M\)/)).toBeInTheDocument();
  });

  it("saisit un code manquant en ligne, avec les codes relevés en suggestion", async () => {
    const appels = stubFetch(true);
    const { apresEnregistrement } = rendre("admin");
    await screen.findByText("WRX99");
    fireEvent.click(screen.getByRole("button", { name: /Saisir — Code module Celcat de Atelier \(WRX99\)/ }));
    const champ = screen.getByRole("combobox", { name: "Code module Celcat de Atelier (WRX99)" });
    const liste = document.getElementById(champ.getAttribute("list") ?? "");
    expect(Array.from(liste?.querySelectorAll("option") ?? []).map((o) => o.getAttribute("value"))).toEqual([
      "TSBZ1M01",
      "TSBZ2M01",
    ]);
    fireEvent.change(champ, { target: { value: "TSBZ2M01" } });
    fireEvent.submit(champ.closest("form")!);
    await waitFor(() => expect(apresEnregistrement).toHaveBeenCalled());
    const put = appels.find((a) => a.init?.method === "PUT");
    expect(JSON.parse(String(put?.init?.body))).toEqual({ famille: "cours", cle: "WRX99", code: "TSBZ2M01" });
    expect(await screen.findByText(/TSBZ2M01 enregistré pour Celcat/)).toBeInTheDocument();
  });

  it("code de la maquette non repris : proposé en premier, raison affichée", async () => {
    stubFetch(true);
    rendre("admin");
    const ligneExclue = (await screen.findByText("WRX98")).closest("tr")!;
    expect(within(ligneExclue).getByText(/Code de la maquette non repris : à faire confirmer/)).toBeInTheDocument();
    expect(within(ligneExclue).getByText("TSBZ2M01", { selector: ".mono" })).toBeInTheDocument();
    fireEvent.click(within(ligneExclue).getByRole("button", { name: /^Saisir — / }));
    const champ = screen.getByRole("combobox", { name: "Code module Celcat de Atelier 2 (WRX98)" });
    const liste = document.getElementById(champ.getAttribute("list") ?? "");
    expect(Array.from(liste?.querySelectorAll("option") ?? []).map((o) => o.getAttribute("value"))).toEqual([
      "TSBZ2M01",
      "TSBZ1M01",
    ]);
  });

  it("marque « sans code (voulu) » avec un motif obligatoire", async () => {
    const appels = stubFetch(true);
    rendre("admin");
    await screen.findByText("WRX99");
    fireEvent.click(screen.getByRole("button", { name: /Sans code \(voulu\)… — Motif « sans code \(voulu\) » de Atelier \(WRX99\)/ }));
    const champ = screen.getByRole("textbox", { name: /Motif « sans code \(voulu\) » de Atelier/ });
    fireEvent.change(champ, { target: { value: "x" } });
    fireEvent.submit(champ.closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("motif est obligatoire");
    fireEvent.change(champ, { target: { value: "Pas une matière" } });
    fireEvent.submit(champ.closest("form")!);
    await waitFor(() => expect(appels.some((a) => a.url.includes("/sans-code") && a.init?.method === "PUT")).toBe(true));
    const put = appels.find((a) => a.url.includes("/sans-code"))!;
    expect(JSON.parse(String(put.init?.body))).toEqual({ famille: "cours", cle: "WRX99", motif: "Pas une matière" });
  });

  it("affiche le refus du serveur sous le champ, qui reste ouvert", async () => {
    stubFetch(true, () => ({ status: 409, corps: { detail: "Le code H.005 est déjà celui de H.005 (h005)." } }));
    rendre("admin");
    fireEvent.click(await screen.findByRole("tab", { name: /^Salles/ }));
    fireEvent.click(screen.getByRole("button", { name: /Saisir — Nom Celcat de H.018/ }));
    const champ = screen.getByRole("combobox", { name: /Nom Celcat de H.018/ });
    fireEvent.change(champ, { target: { value: "H.005" } });
    fireEvent.submit(champ.closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("déjà celui de H.005");
    expect(screen.getByRole("combobox", { name: /Nom Celcat de H.018/ })).toHaveValue("H.005");
  });

  it("revient à manquant après confirmation", async () => {
    const appels = stubFetch(true);
    vi.mocked(confirmAsync).mockResolvedValue(true);
    rendre("admin");
    fireEvent.click(await screen.findByRole("tab", { name: /^Salles/ }));
    const ligneE102 = screen.getByText("E.102", { selector: "td" }).closest("tr")!;
    expect(within(ligneE102).getByText("saisi dans l’appli")).toBeInTheDocument();
    expect(within(ligneE102).getByText(/par jules@iut\.fr/)).toBeInTheDocument();
    fireEvent.click(within(ligneE102).getByRole("button", { name: "Revenir à manquant" }));
    await waitFor(() => expect(appels.some((a) => a.init?.method === "DELETE")).toBe(true));
    const del = appels.find((a) => a.init?.method === "DELETE")!;
    expect(del.url).toContain("famille=salles");
    expect(del.url).toContain("cle=e102");
    expect(vi.mocked(confirmAsync).mock.calls[0][1]?.title).toBe("Revenir à manquant ?");
  });

  it("lecture seule pour un compte non administrateur", async () => {
    stubFetch(false);
    rendre("read_only");
    await screen.findByText("WR101");
    expect(screen.getByText(/Lecture seule/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Saisir|^Modifier|^Sans code \(voulu\)…/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /^Salles/ }));
    expect(screen.queryByRole("button", { name: "Revenir à manquant" })).not.toBeInTheDocument();
    expect(screen.queryByText(/jules@iut\.fr/)).not.toBeInTheDocument();
  });

  it("les groupes : l'identifiant et où il se règle, sans champ", async () => {
    stubFetch(true);
    rendre("admin");
    fireEvent.click(await screen.findByRole("tab", { name: "Groupes" }));
    expect(screen.getByText("1661971")).toBeInTheDocument();
    expect(screen.getByText(/celcat_groupes\.yaml/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Saisir|^Modifier/ })).not.toBeInTheDocument();
  });

  it("un lien ouvre le bon sous-onglet et marque la ligne visée, depuis Référence", async () => {
    stubFetch(true);
    const setRoute = vi.fn();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ContexteDroits.Provider value={{ role: "admin", revision: 1, apresEnregistrement: vi.fn() }}>{children}</ContexteDroits.Provider>
    );
    render(
      <ReferenceView
        payload={emptyPayload()}
        setRoute={setRoute}
        route={{ vue: "reference", onglet: "codes-celcat", famille: "salles", cle: "h018" }}
      />,
      { wrapper },
    );
    expect(screen.getByRole("tab", { name: "Codes Celcat" })).toHaveAttribute("aria-selected", "true");
    const cible = await screen.findByText("H.018 (Amphi MMI)");
    const familles = screen.getByRole("tablist", { name: "Familles de codes Celcat" });
    expect(within(familles).getByRole("tab", { name: /^Salles/ })).toHaveAttribute("aria-selected", "true");
    expect(cible.closest("tr")).toHaveClass("codes-celcat-visee");
    fireEvent.click(within(familles).getByRole("tab", { name: /^Enseignants/ }));
    expect(setRoute).toHaveBeenCalledWith({ onglet: "codes-celcat", famille: "enseignants", cle: "" });
  });

  it("« Nouvel intervenant » depuis Codes Celcat → Enseignants, administrateurs seulement", async () => {
    stubFetch(true);
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ContexteDroits.Provider value={{ role: "admin", revision: 1, apresEnregistrement: vi.fn() }}>{children}</ContexteDroits.Provider>
    );
    render(
      <ReferenceView
        payload={emptyPayload()}
        setRoute={vi.fn()}
        route={{ vue: "reference", onglet: "codes-celcat", famille: "enseignants", cle: "" }}
      />,
      { wrapper },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Nouvel intervenant" }));
    expect(screen.getByRole("dialog", { name: "Nouvel intervenant" })).toBeInTheDocument();
  });

  it("pas de « Nouvel intervenant » pour un non-administrateur, ni hors Enseignants", async () => {
    stubFetch(false);
    rendre("read_only", { famille: "enseignants", onNouvelIntervenant: vi.fn() });
    await screen.findByRole("tab", { name: "Enseignants" });
    expect(screen.queryByRole("button", { name: "Nouvel intervenant" })).not.toBeInTheDocument();
  });
});
