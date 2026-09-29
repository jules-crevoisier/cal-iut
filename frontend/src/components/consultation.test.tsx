/**
 * Écrans de consultation (refonte du 29/09/2026) : navigation de semaine au
 * clavier, prochain cours, agenda du semestre filtrable, lien d'agenda,
 * lecture jour par jour, aujourd'hui repéré dans la grille.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { googleAgendaDepuis, MenuAgenda, webcalDepuis } from "./MenuAgenda";
import { NavSemaine } from "./NavSemaine";
import { ListeJours } from "./PlanningSemaine";
import { ProchainCours } from "./ProchainCours";
import { SemesterAgenda } from "./SemesterAgenda";
import { SessionGrid } from "./SessionGrid";
import type { WeekRow } from "../types/app";
import { sessionsWithDates } from "../utils/ics";
import { emptyPayload, placedRow } from "../test/payloadFixture";

const SEMAINES: WeekRow[] = [
  { monday: "2026-09-21", label: "Semaine 5 (21–25 sept. 2026)", blocked: false, weekIndex: 0 },
  { monday: "2026-09-28", label: "Semaine 6 (28 sept.–2 oct. 2026)", blocked: false, weekIndex: 1 },
  { monday: "2026-10-05", label: "Semaine 7 (5–9 oct. 2026)", blocked: false, weekIndex: 2 },
];

describe("NavSemaine", () => {
  it("passe à la semaine suivante / précédente avec les flèches, et l'écrit en clair", () => {
    const onSelect = vi.fn();
    render(<NavSemaine weekRows={SEMAINES} selected={1} onSelect={onSelect} countByWeekIndex={new Map()} />);
    expect(screen.getByText("Semaine 6")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(onSelect).toHaveBeenLastCalledWith(2);
    fireEvent.keyDown(document, { key: "ArrowLeft" });
    expect(onSelect).toHaveBeenLastCalledWith(0);
    fireEvent.click(screen.getByRole("button", { name: "Semaine suivante" }));
    expect(onSelect).toHaveBeenLastCalledWith(2);
  });

  it("ignore les flèches pendant une saisie ou avec Ctrl", () => {
    const onSelect = vi.fn();
    render(
      <>
        <input aria-label="champ" />
        <NavSemaine weekRows={SEMAINES} selected={1} onSelect={onSelect} countByWeekIndex={new Map()} />
      </>,
    );
    fireEvent.keyDown(screen.getByLabelText("champ"), { key: "ArrowRight" });
    fireEvent.keyDown(document, { key: "ArrowRight", ctrlKey: true });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("T ramène à la semaine en cours et appelle onAujourdhui", () => {
    const onSelect = vi.fn();
    const onAujourdhui = vi.fn();
    render(
      <NavSemaine weekRows={SEMAINES} selected={0} onSelect={onSelect} countByWeekIndex={new Map()} onAujourdhui={onAujourdhui} />,
    );
    fireEvent.keyDown(document, { key: "t" });
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onAujourdhui).toHaveBeenCalledTimes(1);
  });
});

describe("ProchainCours", () => {
  const payload = emptyPayload({ weekDates: ["2026-09-28"], groupLabels: { g: "TD AB" } });
  const items = sessionsWithDates(payload, [
    placedRow({ id: "a", w: 0, d: 1, s: 3, c: "WRA313M", n: "Audiovisuel", t: "TD", r: "H.203", g: ["g"] }),
    placedRow({ id: "b", w: 0, d: 0, s: 0, c: "WR101", n: "Passé", t: "TD", r: "H.101", g: ["g"] }),
  ]);

  it("annonce la prochaine séance avec son jour, son heure et sa salle", () => {
    render(<ProchainCours payload={payload} items={items} maintenant={new Date(2026, 8, 29, 10, 0)} />);
    const bloc = screen.getByRole("status");
    expect(within(bloc).getByText("Prochain cours")).toBeInTheDocument();
    expect(bloc.textContent).toContain("aujourd'hui · 14h–15h30");
    expect(within(bloc).getByText("H.203")).toBeInTheDocument();
  });

  it("dit « En cours » pendant la séance, puis « plus aucun cours » ensuite", () => {
    const { rerender } = render(<ProchainCours payload={payload} items={items} maintenant={new Date(2026, 8, 29, 14, 30)} />);
    expect(screen.getByText("En cours")).toBeInTheDocument();
    rerender(<ProchainCours payload={payload} items={items} maintenant={new Date(2026, 9, 30)} />);
    expect(screen.getByText(/plus aucun cours/i)).toBeInTheDocument();
  });

  it("« Voir dans la grille » renvoie la séance", () => {
    const onVoir = vi.fn();
    render(<ProchainCours payload={payload} items={items} maintenant={new Date(2026, 8, 29, 10, 0)} onVoir={onVoir} />);
    fireEvent.click(screen.getByRole("button", { name: /voir dans la grille/i }));
    expect(onVoir).toHaveBeenCalledWith(expect.objectContaining({ id: "a" }));
  });
});

describe("SemesterAgenda", () => {
  const payload = emptyPayload({
    weekDates: ["2026-09-21", "2026-09-28"],
    weekLabels: ["Semaine 5 (21–25 sept. 2026)", "Semaine 6 (28 sept.–2 oct. 2026)"],
  });
  const items = sessionsWithDates(payload, [
    placedRow({ id: "a", w: 0, d: 0, s: 0, c: "WR101", n: "Anglais", t: "TD" }),
    placedRow({ id: "b", w: 1, d: 0, s: 0, c: "WR102", n: "Culture", t: "CM", dur: 2 }),
    placedRow({ id: "c", w: 1, d: 1, s: 0, c: "WR101", n: "Anglais", t: "TD" }),
  ]);

  it("filtre par matière et recalcule le total d'heures", () => {
    render(<SemesterAgenda payload={payload} items={items} maintenant={new Date(2026, 8, 1)} />);
    expect(screen.getByText("3 séances")).toBeInTheDocument();
    expect(screen.getByText("6 h")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Matière"), { target: { value: "WR101" } });
    expect(screen.getByText("2 séances")).toBeInTheDocument();
    expect(screen.getByText("3 h")).toBeInTheDocument();
    expect(screen.queryByText("Culture")).not.toBeInTheDocument();
  });

  it("« À venir seulement » retire les séances passées", () => {
    render(<SemesterAgenda payload={payload} items={items} maintenant={new Date(2026, 8, 28, 20, 0)} />);
    fireEvent.click(screen.getByLabelText(/à venir seulement/i));
    expect(screen.getByText("1 séance")).toBeInTheDocument();
  });

  it("le titre d'une semaine l'ouvre dans la grille", () => {
    const onChoisirSemaine = vi.fn();
    render(<SemesterAgenda payload={payload} items={items} onChoisirSemaine={onChoisirSemaine} />);
    fireEvent.click(screen.getByRole("button", { name: /Semaine 6/ }));
    expect(onChoisirSemaine).toHaveBeenCalledWith(1);
  });
});

describe("MenuAgenda", () => {
  const url = "https://cal.example/ics/prof/KBR.ics?t=KBR";

  it("propose l'abonnement direct (webcal) et Google Agenda à partir du flux", () => {
    expect(webcalDepuis(url)).toBe("webcal://cal.example/ics/prof/KBR.ics?t=KBR");
    expect(googleAgendaDepuis(url)).toBe(
      `https://calendar.google.com/calendar/r?cid=${encodeURIComponent("webcal://cal.example/ics/prof/KBR.ics?t=KBR")}`,
    );
    render(<MenuAgenda url={url} />);
    fireEvent.click(screen.getByRole("button", { name: /ajouter à mon agenda/i }));
    expect(screen.getByRole("menuitem", { name: /iphone/i })).toHaveAttribute("href", webcalDepuis(url));
    expect(screen.getByRole("menuitem", { name: /copier le lien/i })).toBeInTheDocument();
  });
});

describe("Lecture jour par jour", () => {
  const payload = emptyPayload({ weekDates: ["2026-09-28"] });

  it("liste les séances du jour choisi, dans l'ordre, avec leur salle", () => {
    const rows = [
      placedRow({ id: "b", d: 1, s: 3, c: "WR102", n: "Culture", t: "CM", r: "H.018" }),
      placedRow({ id: "a", d: 1, s: 0, c: "WR101", n: "Anglais", t: "TD", r: "H.103" }),
      placedRow({ id: "z", d: 2, s: 0, c: "WR103", n: "Autre jour", t: "TD", r: "H.101" }),
    ];
    render(<ListeJours payload={payload} rows={rows} week={0} parcours="" showPac={false} showPromo={false} jour={1} onJour={vi.fn()} />);
    const noms = screen.getAllByText(/Anglais|Culture/).map((e) => e.textContent);
    expect(noms).toEqual(["Anglais", "Culture"]);
    expect(screen.getByText("H.018")).toBeInTheDocument();
    expect(screen.getByText("Pause déjeuner")).toBeInTheDocument();
    expect(screen.queryByText("Autre jour")).not.toBeInTheDocument();
  });

  it("propose le prochain jour avec cours quand celui-ci est vide", () => {
    const onJour = vi.fn();
    const rows = [placedRow({ id: "z", d: 3, s: 0, c: "WR103", n: "Jeudi", t: "TD" })];
    render(<ListeJours payload={payload} rows={rows} week={0} parcours="" showPac={false} showPromo={false} jour={0} onJour={onJour} />);
    expect(screen.getByText("Pas de cours ce jour-là.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /voir jeudi/i }));
    expect(onJour).toHaveBeenCalledWith(3);
  });
});

describe("SessionGrid — aujourd'hui", () => {
  it("repère la colonne du jour quand la semaine affichée contient aujourd'hui", () => {
    const now = new Date();
    const lundi = new Date(now);
    lundi.setDate(now.getDate() - ((now.getDay() + 6) % 7));
    const p = (n: number) => String(n).padStart(2, "0");
    const iso = `${lundi.getFullYear()}-${p(lundi.getMonth() + 1)}-${p(lundi.getDate())}`;
    render(<SessionGrid payload={emptyPayload({ weekDates: [iso] })} rows={[]} week={0} />);
    const enWeekEnd = now.getDay() === 0 || now.getDay() === 6;
    expect(screen.queryAllByText("aujourd'hui")).toHaveLength(enWeekEnd ? 0 : 1);
  });
});
