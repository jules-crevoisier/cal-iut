/**
 * Écran Celcat : une matière sans code module se mappe sur place (29/09/2026),
 * parmi les codes relevés ; un identifiant interne de groupe, lui, ne se
 * saisit pas — l'écran dit où il se règle.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CelcatMappings } from "../api/client";
import { BlocagesCelcat } from "./BlocagesCelcat";

const MATIERE = {
  motif: "séance non saisissable : module WR100BU sans code Celcat",
  seances: ["WR100BU-S1-TD-1-but1-td-ab"],
  tentatives: 12,
  famille: "matieres" as const,
  cle: "WR100BU",
};

const GROUPE = {
  motif: "le groupe « BUT MMI S5 TD EF » manque à data/config/celcat_groupes.yaml : relevé à compléter",
  seances: ["WRA501-S5-TD-1-but3-td-ef"],
  tentatives: 3,
  famille: "" as const,
  cle: "",
};

function mappings(): CelcatMappings {
  return {
    salles: [],
    enseignants: [],
    matieres: [{ cle: "WR999", valeur: "TSBZ1M01", ajoute_le: "2026-09-29T10:00:00+00:00", ajoute_par: "jules@iut" }],
    matieres_celcat: ["TSBZ1M01", "TSBZ1202"],
    salles_celcat: [],
    manquants: [MATIERE, GROUPE],
  };
}

describe("BlocagesCelcat — matières et groupes", () => {
  it("mappe une matière sur un code module relevé", () => {
    const onMapper = vi.fn();
    render(<BlocagesCelcat mappings={mappings()} occupe={false} erreur={null} onMapper={onMapper} onOublier={vi.fn()} />);
    const ligne = screen.getByTestId("blocage-matieres");
    const champ = within(ligne).getByRole("combobox", { name: "Équivalent Celcat de WR100BU" });
    expect(champ).toHaveAttribute("placeholder", "TSBZ1M01");
    expect(within(ligne).getByText(/Code module Celcat de cette matière/)).toBeInTheDocument();
    expect(document.querySelectorAll("#celcat-matieres-connues option")).toHaveLength(2);
    fireEvent.change(champ, { target: { value: "TSBZ1202" } });
    fireEvent.click(within(ligne).getByRole("button", { name: "Mapper" }));
    expect(onMapper).toHaveBeenCalledWith("matieres", "WR100BU", "TSBZ1202");
  });

  it("mène à la ligne de la matière dans Référence → Codes Celcat (30/09/2026)", () => {
    render(<BlocagesCelcat mappings={mappings()} occupe={false} erreur={null} onMapper={vi.fn()} onOublier={vi.fn()} />);
    const lien = within(screen.getByTestId("blocage-matieres")).getByRole("link", { name: /Voir dans Codes Celcat/ });
    const params = new URLSearchParams(lien.getAttribute("href")!.slice(1));
    expect(Object.fromEntries(params)).toEqual({ vue: "reference", onglet: "codes-celcat", famille: "cours", cle: "WR100BU" });
  });

  it("dit qu'un identifiant de groupe se règle dans celcat_groupes.yaml, sans champ", () => {
    render(<BlocagesCelcat mappings={mappings()} occupe={false} erreur={null} onMapper={vi.fn()} onOublier={vi.fn()} />);
    const ligne = screen.getByText(GROUPE.motif).closest("li")!;
    expect(within(ligne).getByText(/se règle dans celcat_groupes\.yaml/)).toBeInTheDocument();
    expect(within(ligne).queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("liste les codes modules déjà mappés, retirables", () => {
    const onOublier = vi.fn();
    render(<BlocagesCelcat mappings={mappings()} occupe={false} erreur={null} onMapper={vi.fn()} onOublier={onOublier} />);
    fireEvent.click(screen.getByRole("button", { name: "Retirer la correspondance WR999" }));
    expect(onOublier).toHaveBeenCalledWith("matieres", "WR999");
  });
});
