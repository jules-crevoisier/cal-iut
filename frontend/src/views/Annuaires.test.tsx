/**
 * Annuaires des vues de consultation (refonte v2 du 29/09/2026) : recherche
 * instantanée, filtres, tri par charge de la semaine, clic → fiche.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AnnuaireCours, AnnuaireEnseignants, AnnuaireGroupes, AnnuaireSalles } from "./Annuaires";
import { catalogCourse, catalogRoom, emptyPayload, placedRow } from "../test/payloadFixture";

const payload = emptyPayload({
  teacherLabels: { AAA: "Abel Anne", BBB: "Brun Béa", CCC: "Col Cid" },
  teacherEmails: { AAA: "anne@iut.test", CCC: "cid@iut.test" },
  rows: [
    placedRow({ id: "1", te: ["BBB"], s: 0 }),
    placedRow({ id: "2", te: ["BBB"], s: 1 }),
    placedRow({ id: "3", te: ["AAA"], s: 2 }),
  ],
});

function nomsDansLOrdre(): string[] {
  const table = screen.getByRole("table");
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((r) => within(r).getAllByRole("button")[0].textContent ?? "");
}

describe("AnnuaireEnseignants", () => {
  it("trie par heures de la semaine, la plus chargée d'abord, et le nom ramène l'ordre alphabétique", () => {
    render(<AnnuaireEnseignants payload={payload} displayWeek={0} onOuvrir={vi.fn()} />);
    expect(nomsDansLOrdre()).toEqual(["Brun Béa", "Abel Anne", "Col Cid"]);
    fireEvent.click(screen.getByRole("button", { name: /^Nom/ }));
    expect(nomsDansLOrdre()).toEqual(["Abel Anne", "Brun Béa", "Col Cid"]);
  });

  it("filtre à la frappe, sans tenir compte des accents ni de la casse", () => {
    render(<AnnuaireEnseignants payload={payload} displayWeek={0} onOuvrir={vi.fn()} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Rechercher un enseignant" }), { target: { value: "bea" } });
    expect(nomsDansLOrdre()).toEqual(["Brun Béa"]);
    fireEvent.change(screen.getByRole("searchbox", { name: "Rechercher un enseignant" }), { target: { value: "zzz" } });
    expect(screen.getByText("Aucun enseignant ne correspond.")).toBeInTheDocument();
  });

  it("signale les mails manquants et les isole d'un clic", () => {
    render(<AnnuaireEnseignants payload={payload} displayWeek={0} onOuvrir={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "1 adresse mail manquante" }));
    expect(nomsDansLOrdre()).toEqual(["Brun Béa"]);
    expect(screen.getByText("manquant")).toBeInTheDocument();
  });

  it("ouvre la fiche au clic sur le nom ou sur la ligne", () => {
    const onOuvrir = vi.fn();
    render(<AnnuaireEnseignants payload={payload} displayWeek={0} onOuvrir={onOuvrir} />);
    fireEvent.click(screen.getByRole("button", { name: "Col Cid" }));
    expect(onOuvrir).toHaveBeenLastCalledWith("CCC");
    fireEvent.click(screen.getByText("AAA"));
    expect(onOuvrir).toHaveBeenLastCalledWith("AAA");
  });
});

describe("AnnuaireGroupes", () => {
  it("range les groupes par parcours avec leurs heures de la semaine", () => {
    const onOuvrir = vi.fn();
    const p = emptyPayload({
      groupLabels: { a: "TP A", x: "TP A" },
      groupKind: { a: "tp", x: "tp" },
      groupParcours: { a: "BUT1", x: "BUT2-DEV-FI" },
      rows: [placedRow({ id: "1", g: ["a"], dur: 2 })],
    });
    render(<AnnuaireGroupes payload={p} displayWeek={0} onOuvrir={onOuvrir} />);
    const but1 = screen.getByRole("region", { name: "BUT1" });
    expect(within(but1).getByText("3 h")).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("region", { name: "BUT2-DEV-FI" })).getByRole("button"));
    expect(onOuvrir).toHaveBeenCalledWith("x");
  });
});

describe("AnnuaireCours", () => {
  it("montre le volume placé et isole les maquettes incomplètes", () => {
    const p = emptyPayload({
      courses: [
        catalogCourse("WR101", "Anglais", { nTD: 2, nPlaced: 2 }),
        catalogCourse("WR102", "Culture", { nTD: 3, nPlaced: 1 }),
      ],
    });
    render(<AnnuaireCours payload={p} displayWeek={0} onOuvrir={vi.fn()} />);
    expect(screen.getByText("2 / 2")).toBeInTheDocument();
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "1 maquette pas entièrement placée" }));
    expect(screen.queryByText("WR101")).not.toBeInTheDocument();
    expect(screen.getByText("WR102")).toBeInTheDocument();
  });
});

describe("AnnuaireSalles", () => {
  it("met la salle la plus occupée en tête et dit « saturée » en toutes lettres", () => {
    const rows = Array.from({ length: 27 }, (_, i) =>
      placedRow({ id: `r${i}`, d: Math.floor(i / 6), s: i % 6, r: "H.101" }),
    );
    const p = emptyPayload({
      rooms: [catalogRoom("a018", { label: "A.018" }), catalogRoom("h101", { label: "H.101" })],
      rows,
    });
    render(<AnnuaireSalles payload={p} displayWeek={0} onOuvrir={vi.fn()} />);
    expect(nomsDansLOrdre()).toEqual(["H.101", "A.018"]);
    expect(screen.getByText("saturée")).toBeInTheDocument();
    expect(screen.getByText("27 / 30 · 90 %")).toBeInTheDocument();
  });
});
