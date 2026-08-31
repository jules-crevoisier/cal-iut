/**
 * Contrat de hash admin : fiches prof/salle/cours/groupe, panneau Promo,
 * canonisation de #vue=aplacer, et conservation des liens personnels mode=.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useHashRoute } from "./useHashRoute";

function RouteDump() {
  const { route } = useHashRoute();
  return <pre aria-label="route">{JSON.stringify(route)}</pre>;
}

function dumpedRoute(): Record<string, unknown> {
  const text = screen.getByLabelText("route").textContent;
  if (!text) throw new Error("empty route dump");
  return JSON.parse(text) as Record<string, unknown>;
}

describe("admin hash routing", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    window.location.hash = "";
  });

  afterEach(() => {
    window.history.replaceState(null, "", "/");
    window.location.hash = "";
  });

  it.each([
    ["#vue=prof&prof=KBR", { vue: "prof", prof: "KBR" }],
    ["#vue=salle&salle=B204", { vue: "salle", salle: "B204" }],
    ["#vue=cours&cours=WR106", { vue: "cours", cours: "WR106" }],
    ["#vue=groupe&groupe=G1", { vue: "groupe", groupe: "G1" }],
  ])("should open the entity fiche when hash is %s", (hash, expected) => {
    window.history.replaceState(null, "", `/${hash}`);
    render(<RouteDump />);
    expect(dumpedRoute()).toMatchObject(expected);
  });

  it("should keep optional sem on an admin fiche hash when present", () => {
    window.history.replaceState(null, "", "/#vue=salle&salle=B204&sem=4");
    render(<RouteDump />);
    expect(dumpedRoute()).toMatchObject({ vue: "salle", salle: "B204", sem: 4 });
  });

  it("should open the placement panel when vue is promo and panel is aplacer", () => {
    window.history.replaceState(null, "", "/#vue=promo&panel=aplacer");
    render(<RouteDump />);
    expect(dumpedRoute()).toMatchObject({ vue: "promo", panel: "aplacer" });
  });

  it("should return an empty vue when the hash has no vue", () => {
    window.history.replaceState(null, "", "/");
    render(<RouteDump />);
    expect(dumpedRoute().vue).toBe("");
  });

  it("should canonicalize vue=aplacer to promo with panel=aplacer when sem and jour are present", () => {
    window.history.replaceState(null, "", "/#vue=aplacer&sem=3&jour=1");
    render(<RouteDump />);
    expect(dumpedRoute()).toMatchObject({
      vue: "promo",
      panel: "aplacer",
      sem: 3,
      jour: 1,
    });
  });

  it("should still parse a personal teacher link when mode is prof", () => {
    window.history.replaceState(null, "", "/#mode=prof&prof=KBR");
    render(<RouteDump />);
    expect(dumpedRoute()).toMatchObject({ mode: "prof", prof: "KBR" });
  });

  it("should still parse a personal group link when mode is groupe", () => {
    window.history.replaceState(null, "", "/#mode=groupe&groupe=G1");
    render(<RouteDump />);
    expect(dumpedRoute()).toMatchObject({ mode: "groupe", groupe: "G1" });
  });

  it("should parse the email-confirmation redirect (compte=confirme&statut=ok)", () => {
    window.history.replaceState(null, "", "/#compte=confirme&statut=ok");
    render(<RouteDump />);
    expect(dumpedRoute()).toMatchObject({ compte: "confirme", statut: "ok" });
  });

  it("should parse a password-reset link with its token", () => {
    window.history.replaceState(null, "", "/#compte=reinitialiser&token=abc123");
    render(<RouteDump />);
    expect(dumpedRoute()).toMatchObject({ compte: "reinitialiser", token: "abc123" });
  });

  it("should clear compte/statut/token when navigating to a normal vue", () => {
    window.history.replaceState(null, "", "/#compte=reinitialiser&token=abc123");
    function RouteDumpAvecNav() {
      const { route, setRoute } = useHashRoute();
      return (
        <>
          <pre aria-label="route">{JSON.stringify(route)}</pre>
          <button type="button" onClick={() => setRoute({ vue: "semaine" })}>
            go
          </button>
        </>
      );
    }
    render(<RouteDumpAvecNav />);
    fireEvent.click(screen.getByText("go"));
    expect(dumpedRoute()).toMatchObject({ vue: "semaine", compte: "", statut: "", token: "" });
  });
});
