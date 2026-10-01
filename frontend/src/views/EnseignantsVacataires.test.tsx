/**
 * Référence → « Enseignants & vacataires » (01/10/2026, demande de Kyllian
 * Bresson) : tableau de tous les enseignants et vacataires — type, prénom,
 * nom, diminutif, code Celcat, mail, téléphone —, recherche, tri (mémorisé),
 * filtre par type, édition en ligne de chaque champ, lecture seule (téléphone
 * masqué), export CSV.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AnnuaireEnseignantsReponse, LigneAnnuaireEnseignant, LigneCodeCelcat } from "../api/client";
import { ContexteDroits, type RoleCompte } from "../contexts/Droits";
import { emptyPayload } from "../test/payloadFixture";
import { csvAnnuaire, EnseignantsVacataires } from "./EnseignantsVacataires";
import { ReferenceView } from "./ReferenceView";

function codeCelcat(cle: string, p: Partial<LigneCodeCelcat> = {}): LigneCodeCelcat {
  return {
    cle,
    libelle: cle,
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
    modifiable: false,
    peut_revenir: false,
    peut_marquer_sans_code: false,
    peut_retirer_sans_code: false,
    ...p,
  };
}

function personne(p: Partial<LigneAnnuaireEnseignant> & Pick<LigneAnnuaireEnseignant, "code">): LigneAnnuaireEnseignant {
  return {
    prenom: "",
    nom: "",
    nom_complet: p.code,
    type: null,
    email: null,
    telephone: null,
    telephone_affiche: null,
    nb_seances: 0,
    code_celcat: codeCelcat(p.code),
    cree_dans_appli: false,
    surcharges: {},
    ...p,
  };
}

function lignesDeBase(): LigneAnnuaireEnseignant[] {
  return [
    personne({
      code: "KBR",
      prenom: "Kyllian",
      nom: "BRESSON",
      nom_complet: "Kyllian Bresson",
      type: "enseignant",
      email: "kyllian.bresson@univ-reims.fr",
      telephone: "+33612345678",
      telephone_affiche: "06 12 34 56 78",
      nb_seances: 120,
      code_celcat: codeCelcat("KBR", { code: "35543", code_connu: "35543", origine: "fichier", origine_detail: "celcat.yaml" }),
    }),
    personne({
      code: "MNI",
      prenom: "Marc",
      nom: "NINO",
      nom_complet: "Marc Nino",
      type: "vacataire",
      email: "marc.nino@exemple.fr",
      nb_seances: 12,
      code_celcat: codeCelcat("MNI", { code: "40001", code_connu: "40001", origine: "fichier" }),
    }),
    personne({
      code: "APE",
      prenom: "Anne-Laure",
      nom: "PERRONE",
      nom_complet: "Anne-Laure Perrone",
      nb_seances: 3,
    }),
  ];
}

/** Petit serveur en mémoire : `GET /reference/enseignants` renvoie l'état
 *  courant, les PUT / DELETE le modifient. Le téléphone n'est renvoyé
 *  qu'aux rôles edit / admin, comme le vrai serveur. */
function stubServeur(role: RoleCompte) {
  const lignes = lignesDeBase();
  const appels: { url: string; methode: string; corps: Record<string, unknown> }[] = [];
  const peutModifier = role === "edit" || role === "admin";
  const reponse = (): AnnuaireEnseignantsReponse => {
    const visibles = lignes.map((l) => ({
      ...l,
      telephone: peutModifier ? l.telephone : null,
      telephone_affiche: peutModifier ? l.telephone_affiche : null,
      code_celcat: l.code_celcat && { ...l.code_celcat, modifiable: role === "admin" && l.code_celcat.code_connu === null },
    }));
    return {
      revision: 1,
      peut_modifier: peutModifier,
      admin: role === "admin",
      telephone_visible: peutModifier,
      compteurs: {
        total: lignes.length,
        enseignants: lignes.filter((l) => l.type === "enseignant").length,
        vacataires: lignes.filter((l) => l.type === "vacataire").length,
        a_preciser: lignes.filter((l) => !l.type).length,
        sans_mail: lignes.filter((l) => !l.email).length,
        sans_telephone: peutModifier ? lignes.filter((l) => !l.telephone).length : null,
        sans_code_celcat: lignes.filter((l) => l.code_celcat?.origine === "manquant").length,
      },
      lignes: visibles,
    };
  };
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const methode = (init?.method ?? "GET").toUpperCase();
    const corps = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    appels.push({ url: String(url), methode, corps });
    const repondre = (status: number, json: unknown) =>
      Promise.resolve({ ok: status < 400, status, statusText: "", json: async () => json });
    const u = String(url);
    if (u === "/reference/enseignants" && methode === "GET") return repondre(200, reponse());
    const m = /^\/reference\/enseignants\/([A-Z]+)(?:\/([a-z_]+))?$/.exec(u);
    if (m) {
      const l = lignes.find((x) => x.code === m[1])!;
      if (methode === "PUT" && m[2] === "contact") {
        l.email = String(corps.email);
      } else if (methode === "PUT") {
        if (corps.telephone === "+33 6 00") return repondre(400, { detail: "Numéro refusé par le serveur." });
        if (typeof corps.prenom === "string") l.prenom = corps.prenom;
        if (typeof corps.nom_famille === "string") l.nom = corps.nom_famille.toUpperCase();
        if (typeof corps.type === "string") l.type = corps.type as "enseignant" | "vacataire";
        if (typeof corps.telephone === "string") {
          l.telephone = corps.telephone;
          l.telephone_affiche = "07 11 22 33 44";
        }
      } else if (methode === "DELETE") {
        if (m[2] === "type") l.type = null;
        if (m[2] === "telephone") {
          l.telephone = null;
          l.telephone_affiche = null;
        }
      }
      return repondre(200, { famille: "enseignant", cle: m[1], valeurs: corps, message: "Enregistré.", revision: 2 });
    }
    if (u === "/reference/codes-celcat" && methode === "PUT") {
      const l = lignes.find((x) => x.code === corps.cle)!;
      l.code_celcat = codeCelcat(l.code, { code: String(corps.code), origine: "appli" });
      return repondre(200, { famille: "enseignants", cle: corps.cle, code: corps.code, origine: "appli", message: "ok", revision: 3 });
    }
    return repondre(200, {});
  });
  vi.stubGlobal("fetch", fetchMock);
  return appels;
}

function rendre(role: RoleCompte) {
  const setRoute = vi.fn();
  const apresEnregistrement = vi.fn();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContexteDroits.Provider value={{ role, revision: 1, apresEnregistrement }}>{children}</ContexteDroits.Provider>
  );
  render(<EnseignantsVacataires setRoute={setRoute} onNouvelIntervenant={vi.fn()} />, { wrapper });
  return { setRoute, apresEnregistrement };
}

function codesAffiches(): string[] {
  return Array.from(document.querySelectorAll("tbody tr[data-cle]")).map((tr) => tr.getAttribute("data-cle") ?? "");
}

function ligneDe(code: string): HTMLElement {
  return document.querySelector(`tbody tr[data-cle="${code}"]`) as HTMLElement;
}

describe("Référence — Enseignants & vacataires", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("est un onglet de Référence, avant « Liens & partage », mémorisé dans l'adresse", async () => {
    stubServeur("edit");
    const setRoute = vi.fn();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ContexteDroits.Provider value={{ role: "edit", revision: 1, apresEnregistrement: vi.fn() }}>{children}</ContexteDroits.Provider>
    );
    render(<ReferenceView payload={emptyPayload()} setRoute={setRoute} route={{ vue: "reference", onglet: "salles" }} />, { wrapper });
    const onglets = screen.getAllByRole("tab").map((t) => t.textContent ?? "");
    const ici = onglets.findIndex((t) => t.startsWith("Enseignants & vacataires"));
    expect(ici).toBeGreaterThan(-1);
    expect(onglets[ici + 1]).toMatch(/^Liens & partage/);
    fireEvent.click(screen.getByRole("tab", { name: /^Enseignants & vacataires/ }));
    expect(setRoute).toHaveBeenCalledWith({ onglet: "enseignants", famille: "", cle: "" });
  });

  it("montre tout le monde : type, prénom, nom, diminutif, code Celcat, mail, téléphone, compteurs", async () => {
    stubServeur("edit");
    rendre("edit");
    await screen.findByText("BRESSON");
    expect(codesAffiches().sort()).toEqual(["APE", "KBR", "MNI"]);
    const kbr = within(ligneDe("KBR"));
    expect(kbr.getByText("Enseignant")).toBeInTheDocument();
    expect(kbr.getByText("Kyllian")).toBeInTheDocument();
    expect(kbr.getByText("KBR")).toHaveClass("mono");
    expect(kbr.getByText("35543")).toBeInTheDocument();
    expect(kbr.getByText("kyllian.bresson@univ-reims.fr").closest("a")).toHaveAttribute("href", "mailto:kyllian.bresson@univ-reims.fr");
    expect(kbr.getByText("06 12 34 56 78").closest("a")).toHaveAttribute("href", "tel:+33612345678");
    expect(within(ligneDe("MNI")).getByText("Vacataire")).toBeInTheDocument();
    expect(within(ligneDe("APE")).getByText("à préciser")).toBeInTheDocument();
    // Code Celcat manquant : lien vers l'onglet Codes Celcat.
    expect(within(ligneDe("APE")).getByRole("button", { name: "Codes Celcat →" })).toBeInTheDocument();
    const tuiles = within(screen.getByRole("region", { name: "Enseignants et vacataires" }));
    expect(tuiles.getByRole("button", { name: /Enseignants\s*1/ })).toBeInTheDocument();
    expect(tuiles.getByRole("button", { name: /Vacataires\s*1/ })).toBeInTheDocument();
    expect(tuiles.getByRole("button", { name: /À préciser\s*1/ })).toBeInTheDocument();
    expect(tuiles.getByRole("button", { name: /Sans mail\s*1/ })).toBeInTheDocument();
    expect(tuiles.getByRole("button", { name: /Sans téléphone\s*2/ })).toBeInTheDocument();
  });

  it("recherche par nom, prénom, diminutif ou mail (sans accents)", async () => {
    stubServeur("edit");
    rendre("edit");
    await screen.findByText("BRESSON");
    const champ = screen.getByLabelText("Rechercher un enseignant ou un vacataire");
    fireEvent.change(champ, { target: { value: "perrone" } });
    expect(codesAffiches()).toEqual(["APE"]);
    fireEvent.change(champ, { target: { value: "kyllian" } });
    expect(codesAffiches()).toEqual(["KBR"]);
    fireEvent.change(champ, { target: { value: "mni" } });
    expect(codesAffiches()).toEqual(["MNI"]);
    fireEvent.change(champ, { target: { value: "exemple.fr" } });
    expect(codesAffiches()).toEqual(["MNI"]);
    fireEvent.change(champ, { target: { value: "anne laure" } });
    expect(codesAffiches()).toEqual(["APE"]);
    fireEvent.change(champ, { target: { value: "zzz" } });
    expect(screen.getByText("Aucun enseignant ne correspond.")).toBeInTheDocument();
  });

  it("trie sur chaque colonne, et retient le tri sur le poste", async () => {
    stubServeur("edit");
    rendre("edit");
    await screen.findByText("BRESSON");
    expect(codesAffiches()).toEqual(["KBR", "MNI", "APE"]); // Nom : BRESSON, NINO, PERRONE
    fireEvent.click(screen.getByRole("button", { name: /^Diminutif/ }));
    expect(codesAffiches()).toEqual(["APE", "KBR", "MNI"]);
    fireEvent.click(screen.getByRole("button", { name: /^Diminutif/ }));
    expect(codesAffiches()).toEqual(["MNI", "KBR", "APE"]);
    fireEvent.click(screen.getByRole("button", { name: /^Séances/ }));
    expect(codesAffiches()).toEqual(["APE", "MNI", "KBR"]);
    fireEvent.click(screen.getByRole("button", { name: /^Type/ }));
    expect(codesAffiches()).toEqual(["KBR", "MNI", "APE"]);
    expect(JSON.parse(window.localStorage.getItem("cal-iut:reference:enseignants:tri:v1") ?? "{}")).toEqual({ cle: "type", sens: 1 });
  });

  it("le tri retenu est repris à l'ouverture", async () => {
    window.localStorage.setItem("cal-iut:reference:enseignants:tri:v1", JSON.stringify({ cle: "code", sens: -1 }));
    stubServeur("edit");
    rendre("edit");
    await screen.findByText("BRESSON");
    expect(codesAffiches()).toEqual(["MNI", "KBR", "APE"]);
    expect(screen.getByRole("button", { name: /^Diminutif/ }).closest("th")).toHaveAttribute("aria-sort", "descending");
  });

  it("filtre par type (pastilles et tuiles)", async () => {
    stubServeur("edit");
    rendre("edit");
    await screen.findByText("BRESSON");
    const types = within(screen.getByRole("group", { name: "Type" }));
    fireEvent.click(types.getByRole("button", { name: /^Vacataires/ }));
    expect(codesAffiches()).toEqual(["MNI"]);
    fireEvent.click(types.getByRole("button", { name: /^À préciser/ }));
    expect(codesAffiches()).toEqual(["APE"]);
    fireEvent.click(types.getByRole("button", { name: /^Enseignants/ }));
    expect(codesAffiches()).toEqual(["KBR"]);
    fireEvent.click(types.getByRole("button", { name: /^Tous/ }));
    expect(codesAffiches()).toHaveLength(3);
    const tuiles = within(screen.getByRole("region", { name: "Enseignants et vacataires" }));
    fireEvent.click(tuiles.getByRole("button", { name: /Sans mail/ }));
    expect(codesAffiches()).toEqual(["APE"]);
    expect(screen.getByText("1 sur 3 personnes")).toBeInTheDocument();
  });

  it("modifie le prénom en ligne : Entrée enregistre, « Enregistré » annoncé", async () => {
    const appels = stubServeur("edit");
    const { apresEnregistrement } = rendre("edit");
    await screen.findByText("BRESSON");
    fireEvent.click(screen.getByRole("button", { name: "Modifier — Prénom de Kyllian Bresson (KBR)" }));
    const champ = screen.getByRole("textbox", { name: "Prénom de Kyllian Bresson (KBR)" });
    expect(champ).toHaveValue("Kyllian");
    fireEvent.change(champ, { target: { value: "Kylian" } });
    fireEvent.submit(champ.closest("form")!);
    await waitFor(() => expect(appels.some((a) => a.methode === "PUT" && a.url === "/reference/enseignants/KBR")).toBe(true));
    expect(appels.find((a) => a.methode === "PUT")!.corps).toEqual({ prenom: "Kylian" });
    await screen.findByText("Kylian");
    expect(apresEnregistrement).toHaveBeenCalled();
    expect(screen.getByText("Kyllian Bresson : prénom enregistré.")).toBeInTheDocument();
  });

  it("Échap annule sans rien envoyer", async () => {
    const appels = stubServeur("edit");
    rendre("edit");
    await screen.findByText("BRESSON");
    fireEvent.click(screen.getByRole("button", { name: "Modifier — Nom de Kyllian Bresson (KBR)" }));
    const champ = screen.getByRole("textbox", { name: "Nom de Kyllian Bresson (KBR)" });
    fireEvent.change(champ, { target: { value: "AUTRE" } });
    fireEvent.keyDown(champ, { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: "Nom de Kyllian Bresson (KBR)" })).not.toBeInTheDocument();
    expect(appels.filter((a) => a.methode !== "GET")).toHaveLength(0);
  });

  it("modifie le nom, le mail et le type", async () => {
    const appels = stubServeur("edit");
    rendre("edit");
    await screen.findByText("BRESSON");
    fireEvent.click(screen.getByRole("button", { name: "Modifier — Nom de Marc Nino (MNI)" }));
    const nom = screen.getByRole("textbox", { name: "Nom de Marc Nino (MNI)" });
    fireEvent.change(nom, { target: { value: "Nino-Rossi" } });
    fireEvent.submit(nom.closest("form")!);
    await screen.findByText("NINO-ROSSI");
    expect(appels.some((a) => a.methode === "PUT" && a.corps.nom_famille === "Nino-Rossi")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Ajouter — Adresse mail de Anne-Laure Perrone" }));
    const mail = screen.getByRole("textbox", { name: "Adresse mail de Anne-Laure Perrone" });
    fireEvent.change(mail, { target: { value: "pas-une-adresse" } });
    fireEvent.submit(mail.closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Adresse invalide/);
    fireEvent.change(mail, { target: { value: "alp@exemple.fr" } });
    fireEvent.submit(mail.closest("form")!);
    await waitFor(() => expect(appels.some((a) => a.url === "/reference/enseignants/APE/contact" && a.corps.email === "alp@exemple.fr")).toBe(true));

    fireEvent.click(screen.getByRole("button", { name: "Modifier — Type de Anne-Laure Perrone (APE)" }));
    const type = screen.getByRole("combobox", { name: "Type de Anne-Laure Perrone (APE)" });
    fireEvent.change(type, { target: { value: "vacataire" } });
    fireEvent.submit(type.closest("form")!);
    await waitFor(() => expect(appels.some((a) => a.methode === "PUT" && a.corps.type === "vacataire")).toBe(true));
    await waitFor(() => expect(within(ligneDe("APE")).getAllByText("Vacataire").length).toBeGreaterThan(0));

    // « À préciser » : la saisie est retirée.
    fireEvent.click(screen.getByRole("button", { name: "Modifier — Type de Marc Nino (MNI)" }));
    const typeMni = screen.getByRole("combobox", { name: "Type de Marc Nino (MNI)" });
    fireEvent.change(typeMni, { target: { value: "" } });
    fireEvent.submit(typeMni.closest("form")!);
    await waitFor(() => expect(appels.some((a) => a.methode === "DELETE" && a.url === "/reference/enseignants/MNI/type")).toBe(true));
  });

  it("téléphone : refus immédiat d'un format invalide, normalisation, erreur serveur sous le champ", async () => {
    const appels = stubServeur("edit");
    rendre("edit");
    await screen.findByText("BRESSON");
    fireEvent.click(screen.getByRole("button", { name: "Ajouter — Téléphone de Marc Nino (MNI)" }));
    const champ = screen.getByRole("textbox", { name: "Téléphone de Marc Nino (MNI)" });
    expect(champ).toHaveAttribute("inputmode", "tel");
    fireEvent.change(champ, { target: { value: "06 12" } });
    fireEvent.submit(champ.closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Numéro invalide/);
    expect(appels.filter((a) => a.methode === "PUT")).toHaveLength(0);
    fireEvent.change(champ, { target: { value: "07.11.22.33.44" } });
    fireEvent.submit(champ.closest("form")!);
    await waitFor(() => expect(appels.some((a) => a.methode === "PUT" && a.corps.telephone === "+33711223344")).toBe(true));
    expect((await screen.findByText("07 11 22 33 44")).closest("a")).toHaveAttribute("href", "tel:+33711223344");

    // Vider le champ retire le numéro.
    fireEvent.click(screen.getByRole("button", { name: "Modifier — Téléphone de Kyllian Bresson (KBR)" }));
    const kbr = screen.getByRole("textbox", { name: "Téléphone de Kyllian Bresson (KBR)" });
    expect(kbr).toHaveValue("06 12 34 56 78");
    fireEvent.change(kbr, { target: { value: "" } });
    fireEvent.submit(kbr.closest("form")!);
    await waitFor(() => expect(appels.some((a) => a.methode === "DELETE" && a.url === "/reference/enseignants/KBR/telephone")).toBe(true));
  });

  it("code Celcat : la cellule de l'onglet Codes Celcat, saisie par un administrateur", async () => {
    const appels = stubServeur("admin");
    rendre("admin");
    await screen.findByText("BRESSON");
    // Code connu : verrouillé.
    expect(within(ligneDe("KBR")).getByLabelText("verrouillé")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Saisir — Code Celcat de APE" }));
    const champ = screen.getByRole("textbox", { name: "Code Celcat de APE" });
    fireEvent.change(champ, { target: { value: "40999" } });
    fireEvent.submit(champ.closest("form")!);
    await waitFor(() =>
      expect(appels.some((a) => a.methode === "PUT" && a.url === "/reference/codes-celcat" && a.corps.code === "40999")).toBe(true),
    );
    expect(await within(ligneDe("APE")).findByText("saisi dans l’appli")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nouvel intervenant" })).toBeInTheDocument();
  });

  it("un compte « edit » ne saisit pas de code Celcat, ni de nouvel intervenant", async () => {
    stubServeur("edit");
    rendre("edit");
    await screen.findByText("BRESSON");
    expect(screen.queryByRole("button", { name: /^Saisir — Code Celcat/ })).not.toBeInTheDocument();
    expect(within(ligneDe("APE")).getByText("manquant")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Nouvel intervenant" })).not.toBeInTheDocument();
  });

  it("lecture seule : aucun crayon, téléphone masqué « — »", async () => {
    stubServeur("read_only");
    rendre("read_only");
    await screen.findByText("BRESSON");
    expect(screen.queryAllByRole("button", { name: /^Modifier — / })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: /^Ajouter — / })).toHaveLength(0);
    expect(screen.queryByText("06 12 34 56 78")).not.toBeInTheDocument();
    expect(within(ligneDe("KBR")).getByTitle("Visible pour les comptes qui peuvent modifier")).toHaveTextContent("—");
    expect(screen.queryByRole("button", { name: /Sans téléphone/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Lecture seule\. Le téléphone n’est visible/)).toBeInTheDocument();
    // Le reste reste lisible.
    expect(screen.getByText("kyllian.bresson@univ-reims.fr")).toBeInTheDocument();
    expect(screen.getByText("Vacataire")).toBeInTheDocument();
  });

  it("« Voir la fiche » ouvre la fiche Vue Enseignant", async () => {
    stubServeur("edit");
    const { setRoute } = rendre("edit");
    await screen.findByText("BRESSON");
    fireEvent.click(screen.getByRole("button", { name: "Voir la fiche de Marc Nino" }));
    expect(setRoute).toHaveBeenCalledWith({ vue: "prof", prof: "MNI" });
  });

  it("export « Annuaire (.csv) » : le même contenu, téléphone seulement si visible", async () => {
    const lignes = lignesDeBase();
    const avec = csvAnnuaire(lignes, true);
    expect(avec.split("\r\n")[0]).toBe('﻿"Type";"Prénom";"Nom";"Diminutif";"Code Celcat";"E-mail";"Téléphone";"Séances"');
    expect(avec).toContain('"Enseignant";"Kyllian";"BRESSON";"KBR";"35543";"kyllian.bresson@univ-reims.fr";"06 12 34 56 78";"120"');
    expect(avec).toContain('"à préciser";"Anne-Laure";"PERRONE";"APE";"";"";"";"3"');
    const sans = csvAnnuaire(lignes, false);
    expect(sans).not.toContain("Téléphone");
    expect(sans).not.toContain("06 12 34 56 78");

    stubServeur("read_only");
    const creer = vi.fn(() => "blob:x");
    vi.stubGlobal("URL", { ...URL, createObjectURL: creer, revokeObjectURL: vi.fn() });
    const clic = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    rendre("read_only");
    await screen.findByText("BRESSON");
    fireEvent.click(screen.getByRole("button", { name: "Annuaire (.csv)" }));
    expect(clic).toHaveBeenCalled();
    const blob = (creer.mock.calls[0] as unknown as [Blob])[0];
    const texte = await blob.text();
    expect(texte).toContain("Kyllian");
    expect(texte).not.toContain("Téléphone");
    clic.mockRestore();
  });
});
