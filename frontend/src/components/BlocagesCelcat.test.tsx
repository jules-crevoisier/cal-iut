/**
 * Ce qui bloque la recopie, et comment le régler sur place.
 *
 * Le 20/09/2026, trente corrections étaient bloquées depuis des jours — deux
 * salles sans équivalent Celcat, trois séances sans code enseignant, vingt-
 * cinq séances disparues de la maquette — et rien n'apparaissait dans
 * l'application : l'information vivait dans `docker compose logs`.
 *
 * Ces tests tiennent les deux demandes : voir ce qui bloque, et pouvoir
 * mapper une salle sans attendre un déploiement.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CelcatMappings } from "../api/client";
import { BlocagesCelcat } from "./BlocagesCelcat";

const SALLE = {
  motif:
    "séance non saisissable, salle manquant(s) : salle « e-102 » sans équivalent Celcat (cf. data/config/celcat.yaml)",
  seances: ["WR112-S1-TD-1-but1-td-ef", "WR113-S1-TD-1-but1-td-gh"],
  tentatives: 87,
  famille: "salles" as const,
  cle: "e-102",
};

const PROF = {
  motif: "séance non saisissable, enseignant manquant(s) : enseignant JHU sans code Celcat",
  seances: ["WR303D-S3-TP-1-a", "WR303D-S3-TP-1-b", "WR303D-S3-TP-1-c"],
  tentatives: 41,
  famille: "enseignants" as const,
  cle: "JHU",
};

const ORPHELINE = {
  motif: "séance sans placement au planning (retirée, ou planning régénéré depuis)",
  sans_semaine: true,
  seances: ["WR303D-S3-TP-1-but2-dev-fi-tp-c"],
  tentatives: 120,
  famille: "" as const,
  cle: "",
};

function mappings(extra: Partial<CelcatMappings> = {}): CelcatMappings {
  return {
    salles: [],
    enseignants: [],
    salles_celcat: ["H.104", "H.005", "Amphi 3 MMI"],
    manquants: [SALLE, PROF, ORPHELINE],
    ...extra,
  };
}

function poser(props: Partial<Parameters<typeof BlocagesCelcat>[0]> = {}) {
  const onMapper = vi.fn();
  const onOublier = vi.fn();
  render(
    <BlocagesCelcat
      mappings={mappings()}
      occupe={false}
      erreur={null}
      onMapper={onMapper}
      onOublier={onOublier}
      {...props}
    />,
  );
  return { onMapper, onOublier };
}

describe("Ce qui bloque la recopie Celcat", () => {
  it("compte les séances bloquées et dit qu'elles repartiront seules", () => {
    poser();
    expect(screen.getByRole("heading", { level: 2, name: /5 séances bloquées/i })).toBeTruthy();
    expect(screen.getByText(/repartent d’elles-mêmes/i)).toBeTruthy();
  });

  it("nomme chaque cause, avec ses séances et depuis combien de tentatives", () => {
    poser();
    const bloc = screen.getByTestId("blocage-salles");
    expect(bloc.textContent).toContain("e-102");
    expect(bloc.textContent).toContain("2 séances");
    expect(bloc.textContent).toContain("87 tentatives");
    expect(bloc.textContent).toContain("WR112-S1-TD-1-but1-td-ef");
  });

  it("propose de mapper une salle, en choisissant parmi celles que Celcat connaît", () => {
    const { onMapper } = poser();
    const champ = screen.getByLabelText(/équivalent celcat de e-102/i) as HTMLInputElement;
    // Une liste réelle : inventer un nom ferait échouer l'écriture plus tard.
    const liste = document.getElementById(champ.getAttribute("list") ?? "");
    expect(liste?.textContent).toBe("");
    expect([...(liste?.querySelectorAll("option") ?? [])].map((o) => o.getAttribute("value"))).toContain("H.104");

    fireEvent.change(champ, { target: { value: "H.104" } });
    fireEvent.click(within(screen.getByTestId("blocage-salles")).getByRole("button", { name: /mapper/i }));

    expect(onMapper).toHaveBeenCalledWith("salles", "e-102", "H.104");
  });

  it("demande un identifiant pour un enseignant, pas un nom de salle", () => {
    poser();
    const bloc = screen.getByTestId("blocage-enseignants");
    expect(bloc.textContent).toMatch(/identifiant celcat/i);
    expect(within(bloc).getByLabelText(/équivalent celcat de JHU/i).getAttribute("list")).toBeNull();
  });

  it("range hors semaine ce qui n'est plus placé, au lieu de le mêler aux écarts", () => {
    // « pourquoi on parle de 303 alors qu'il n'est pas dans les différences ? »
    // Un job dont la séance n'est plus placée n'appartient à aucune semaine.
    poser();
    expect(screen.getByRole("heading", { level: 2, name: /5 séances bloquées cette semaine/i })).toBeTruthy();
    const hors = screen.getByTestId("blocages-hors-semaine");
    expect(hors.textContent).toMatch(/1 job sans séance placée/i);
    expect(hors.textContent).toMatch(/ne relèvent d’aucune semaine/i);
  });

  it("dit où regarder pour une séance qui n'a plus de place au planning", () => {
    // Le 20/09/2026, sept séances de WR303D étaient annoncées « inconnues de
    // la maquette » alors qu'elles y figuraient toutes : elles n'avaient
    // simplement plus de placement. « Rien à mapper » ne suffit pas, il faut
    // dire OÙ regarder.
    poser();
    const bloc = screen.getByTestId("blocage-autre");
    expect(within(bloc).queryByRole("button", { name: /mapper/i })).toBeNull();
    expect(bloc.textContent).toMatch(/replacez-la depuis « À placer »/i);
    expect(bloc.textContent).toMatch(/semaines enregistrées/i);
  });

  it("n'envoie rien tant que le champ est vide", () => {
    const { onMapper } = poser();
    const bouton = within(screen.getByTestId("blocage-salles")).getByRole("button", { name: /mapper/i });
    expect(bouton).toBeDisabled();
    fireEvent.click(bouton);
    expect(onMapper).not.toHaveBeenCalled();
  });

  it("montre les correspondances déjà ajoutées, avec leur origine, et permet de les retirer", () => {
    const { onOublier } = poser({
      mappings: mappings({
        manquants: [],
        salles: [{ cle: "e-102", valeur: "H.104", ajoute_le: "2026-09-20T18:30:00", ajoute_par: "jules@iut" }],
      }),
    });
    const repli = screen.getByTestId("mappings-existants");
    expect(repli.textContent).toContain("e-102");
    expect(repli.textContent).toContain("H.104");
    expect(repli.textContent).toContain("jules@iut");
    expect(repli.textContent).toContain("20/09 à 18:30");

    fireEvent.click(within(repli).getByRole("button", { name: /retirer la correspondance e-102/i }));
    expect(onOublier).toHaveBeenCalledWith("salles", "e-102");
  });

  it("dit que les blocages affichés sont ceux de la semaine regardée", () => {
    poser();
    expect(screen.getByRole("heading", { level: 2, name: /cette semaine/i })).toBeTruthy();
  });

  it("compte ce qui bloque ailleurs au lieu de le taire", () => {
    // Filtrer trente blocages à six sans un mot ferait croire que les autres
    // se sont réglés.
    poser({ mappings: mappings({ bloques_autres_semaines: 24 }) });
    expect(screen.getByTestId("blocages-autres-semaines").textContent).toMatch(
      /24 autres blocages sur d’autres semaines/i,
    );
  });

  it("reste visible quand la semaine est saine mais qu'il bloque ailleurs", () => {
    poser({ mappings: mappings({ manquants: [], bloques_autres_semaines: 3 }) });
    expect(screen.getByTestId("blocages-autres-semaines")).toBeTruthy();
  });

  it("disparaît quand il n'y a ni blocage ni correspondance", () => {
    const { container } = render(
      <BlocagesCelcat
        mappings={mappings({ manquants: [] })}
        occupe={false}
        erreur={null}
        onMapper={vi.fn()}
        onOublier={vi.fn()}
      />,
    );
    expect(container.querySelector(".celcat-blocages")).toBeNull();
  });

  it("montre l'échec d'un enregistrement sans effacer la liste", () => {
    poser({ erreur: "famille inconnue" });
    expect(screen.getByRole("alert").textContent).toContain("famille inconnue");
    expect(screen.getByTestId("blocage-salles")).toBeTruthy();
  });

  // Signalement de Kyllian Bresson, 25/09/2026 : « j'ai l'impression que le
  // clic sur mapper ne fonctionne pas. » Un clic qui a marché doit se voir.
  it("montre un état occupé sur le bouton pendant l'envoi", () => {
    poser({ occupe: true });
    const bouton = within(screen.getByTestId("blocage-salles")).getByRole("button", { name: /mapper/i });
    expect(bouton).toBeDisabled();
    expect(bouton.textContent).toMatch(/mapper…/i);
    expect(bouton.getAttribute("aria-busy")).toBe("true");
  });

  it("affiche une confirmation après un enregistrement réussi", () => {
    poser({ confirmation: "Correspondance enregistrée : e-102 → H.104." });
    expect(screen.getByRole("status").textContent).toContain("e-102 → H.104");
  });
});
