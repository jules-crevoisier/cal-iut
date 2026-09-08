/**
 * Un conflit forçable doit rester RECONNAISSABLE après son passage par
 * `messageErreur`.
 *
 * Retour utilisateur 08/09/2026 : « je clique sur une séance dans la liste
 * du select et cela ne change pas la salle », puis « semaine en cours, là
 * je veux modifier aujourd'hui, il faut pouvoir forcer ». Aucun message,
 * aucune fenêtre de confirmation : le changement disparaissait dans le
 * vide.
 *
 * La chaîne était rompue au milieu. Le serveur refuse bien un changement de
 * salle sur la semaine en cours, et il le fait EXPRÈS sous forme
 * structurée — `{"detail": {"message": "Conflit", "hard_conflicts": [...]}}`
 * — précisément pour que l'interface puisse proposer de forcer (cf.
 * `api/main.py::changer_salle`, corrigé le 31/08/2026 dans ce but).
 *
 * Mais `messageErreur` ne savait lire qu'un `detail` CHAÎNE ou TABLEAU. Sur
 * un objet, il retombait sur `res.statusText`, soit « Conflict » — un mot
 * qui ne contient plus rien. `detailConflit` tentait ensuite d'en faire du
 * JSON, échouait, rendait `null`, et `appliquerSalle` relançait l'erreur au
 * lieu d'ouvrir la modale de forçage.
 *
 * Le serveur envoyait donc l'information exacte dont l'interface avait
 * besoin, et l'interface la jetait.
 */

import { describe, expect, it } from "vitest";

import { detailConflit } from "./placement";
import { messageErreur } from "../api/client";

/** Ce que le serveur renvoie vraiment pour une salle sur la semaine en
 * cours (relevé en production le 08/09/2026). */
const CONFLIT_SEMAINE_EN_COURS = {
  detail: {
    message: "Conflit",
    hard_conflicts: ["Semaine 2 non modifiable (statut : current)"],
    soft_warnings: [],
    suggestions: [],
    suggestions_note: null,
  },
};

describe("messageErreur + detailConflit : la chaîne du forçage", () => {
  it("préserve un detail STRUCTURÉ, pour que le forçage reste proposable", () => {
    const message = messageErreur(CONFLIT_SEMAINE_EN_COURS, "Conflict");
    const detail = detailConflit(new Error(message));

    expect(detail).not.toBeNull();
    expect(detail?.hard_conflicts).toContain("Semaine 2 non modifiable (statut : current)");
  });

  it("ne rend jamais le seul statut HTTP quand le serveur a détaillé", () => {
    // « Conflict » est le repli : il signifie qu'on a perdu le détail en
    // route, et c'est exactement ce qui privait l'utilisateur du bouton.
    expect(messageErreur(CONFLIT_SEMAINE_EN_COURS, "Conflict")).not.toBe("Conflict");
  });

  it("garde un detail CHAÎNE lisible tel quel", () => {
    // L'autre forme du serveur (`PATCH /placements/{id}` sur une semaine
    // verrouillée) : elle n'est pas forçable, mais doit rester affichable.
    const message = messageErreur(
      { detail: "Semaine 2 non modifiable (statut : current)" },
      "Conflict",
    );

    expect(message).toBe("Semaine 2 non modifiable (statut : current)");
    expect(detailConflit(new Error(message))).toBeNull();
  });

  it("garde les erreurs de validation FastAPI lisibles", () => {
    // Non-régression : `detail` en TABLEAU (422 de FastAPI).
    expect(
      messageErreur({ detail: [{ msg: "champ requis" }, { msg: "valeur invalide" }] }, "Erreur"),
    ).toBe("champ requis valeur invalide");
  });

  it("retombe sur le statut HTTP quand le corps ne dit rien", () => {
    expect(messageErreur(null, "Internal Server Error")).toBe("Internal Server Error");
    expect(messageErreur({}, "Bad Gateway")).toBe("Bad Gateway");
  });
});
