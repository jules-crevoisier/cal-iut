/**
 * Reprise au montage — retour utilisateur du 25/09/2026 : « si on quitte et
 * qu'on revient sur l'onglet Celcat, ça le remet en mode qu'on peut le
 * recorriger. » `useBoucleCelcat` lit désormais `GET /celcat/comparaison/
 * en-cours` au montage et REPREND l'attente plutôt que de repartir à zéro.
 *
 * Ces tests isolent le hook (via `renderHook`) de l'écran : le comportement
 * qu'ils protègent est exactement celui que `VerdictCelcat` lit ensuite
 * (`occupe` désactive « Corriger », `etat.message` porte le texte affiché).
 */
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CelcatCorrectionEnCours } from "../api/client";
import { useBoucleCelcat } from "./useBoucleCelcat";

const fetchCelcatCorrectionEnCours = vi.fn<[number], Promise<CelcatCorrectionEnCours>>();
vi.mock("../api/client", async (importOriginal) => {
  const reel = await importOriginal<typeof import("../api/client")>();
  return { ...reel, fetchCelcatCorrectionEnCours: (semaine: number) => fetchCelcatCorrectionEnCours(semaine) };
});

const CADENCE = { intervalleMs: 5, limiteWorkerMs: 200, limiteReleveMs: 200 };

function correction(etat: CelcatCorrectionEnCours["etat"], extra: Partial<CelcatCorrectionEnCours> = {}): CelcatCorrectionEnCours {
  return {
    semaine: 7,
    etat,
    mise_en_file_le: etat === "absente" ? null : "2026-09-25T10:00:00+00:00",
    par: "jules@iut",
    total: etat === "absente" ? 0 : 3,
    message: "",
    ...extra,
  };
}

describe("useBoucleCelcat — reprise au montage", () => {
  beforeEach(() => {
    fetchCelcatCorrectionEnCours.mockReset();
  });

  it("mounting with none in flight (« absente ») shows the normal, idle screen", async () => {
    fetchCelcatCorrectionEnCours.mockResolvedValue(correction("absente"));

    const onVerifie = vi.fn();
    const { result } = renderHook(() => useBoucleCelcat(7, { onVerifie, ...CADENCE }));

    await waitFor(() => expect(fetchCelcatCorrectionEnCours).toHaveBeenCalledWith(7));

    expect(result.current.etat.etape).toBe("repos");
    expect(result.current.occupe).toBe(false);
    expect(onVerifie).not.toHaveBeenCalled();
  });

  it("mounting with a correction in flight (« en_cours ») shows the waiting state — no fresh « Corriger » offered", async () => {
    fetchCelcatCorrectionEnCours.mockResolvedValue(
      correction("en_cours", { message: "Corrections envoyées — en attente du passage du worker…" }),
    );

    const onVerifie = vi.fn();
    const { result } = renderHook(() => useBoucleCelcat(7, { onVerifie, ...CADENCE }));

    await waitFor(() => expect(result.current.etat.etape).toBe("attente_worker"));
    // `occupe` est ce que `VerdictCelcat` lit pour désactiver « Corriger » —
    // repris sans qu'aucun clic n'ait eu lieu dans CE montage.
    expect(result.current.occupe).toBe(true);
    expect(result.current.etat.message).toMatch(/en attente du passage du worker/i);
    expect(result.current.etat.correction).toBeNull();
  });

  it("resumes until the server reports « termine », then re-reads comparaison/état/file like a normal correction", async () => {
    fetchCelcatCorrectionEnCours
      .mockResolvedValueOnce(correction("en_cours"))
      .mockResolvedValueOnce(correction("en_cours"))
      .mockResolvedValueOnce(correction("termine"));

    const onVerifie = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useBoucleCelcat(7, { onVerifie, ...CADENCE }));

    await waitFor(() => expect(result.current.etat.etape).toBe("verifie"), { timeout: 3000 });
    expect(onVerifie).toHaveBeenCalledTimes(1);
    expect(result.current.occupe).toBe(false);
  });

  it("an expired tracking record (« expire ») says the corrections are still queued — never that they failed", async () => {
    fetchCelcatCorrectionEnCours.mockResolvedValue(
      correction("expire", {
        message: "Les corrections envoyées restent en file — le worker n'est pas encore repassé. Rien n'est perdu.",
      }),
    );

    const { result } = renderHook(() => useBoucleCelcat(7, { onVerifie: vi.fn(), ...CADENCE }));

    await waitFor(() => expect(result.current.etat.etape).toBe("interrompu"));
    expect(result.current.etat.message.toLowerCase()).not.toContain("échec");
    expect(result.current.etat.message.toLowerCase()).not.toContain("échoué");
    // « interrompu » ne bloque pas le bouton — recliquer est sûr (la file
    // déduplique) : c'est le même choix que l'arrêt local du worker.
    expect(result.current.occupe).toBe(false);
  });

  it("a null semaine never triggers a lookup", async () => {
    renderHook(() => useBoucleCelcat(null, { onVerifie: vi.fn(), ...CADENCE }));
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchCelcatCorrectionEnCours).not.toHaveBeenCalled();
  });
});
