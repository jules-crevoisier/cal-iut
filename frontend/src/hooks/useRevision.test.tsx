/**
 * `useRevision` — sondage de `GET /api/v1/version` (29/09/2026, « limiter
 * les connexions au serveur ») : un collègue voit les modifications d'un
 * autre sans F5, mais on ne recharge l'état complet QUE quand la révision a
 * bougé, et on ne sonde rien du tout quand l'onglet est caché.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { VersionEtat } from "../api/client";
import { useRevision } from "./useRevision";

const fetchVersion = vi.fn<[], Promise<VersionEtat>>();
vi.mock("../api/client", async (importOriginal) => {
  const reel = await importOriginal<typeof import("../api/client")>();
  return { ...reel, fetchVersion: () => fetchVersion() };
});

function version(revision: number): VersionEtat {
  return { revision, modifie_le: "2026-09-29T10:00:00+00:00" };
}

let visibilite: DocumentVisibilityState = "visible";

function changerVisibilite(etat: DocumentVisibilityState) {
  visibilite = etat;
  document.dispatchEvent(new Event("visibilitychange"));
}

const attendre = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe("useRevision", () => {
  beforeEach(() => {
    fetchVersion.mockReset();
    visibilite = "visible";
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibilite });
  });

  afterEach(() => {
    visibilite = "visible";
  });

  it("learns the starting revision silently, then calls onChange only when it moves", async () => {
    fetchVersion
      .mockResolvedValueOnce(version(1))
      .mockResolvedValueOnce(version(1))
      .mockResolvedValue(version(2));
    const onChange = vi.fn();

    const { result } = renderHook(() => useRevision({ actif: true, intervalleMs: 10, onChange }));

    await waitFor(() => expect(result.current.revision).toBe(2));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(version(2));
  });

  it("does not poll at all while inactive (no account yet: it would only be 401s)", async () => {
    fetchVersion.mockResolvedValue(version(1));

    renderHook(() => useRevision({ actif: false, intervalleMs: 5, onChange: vi.fn() }));
    await attendre(40);

    expect(fetchVersion).not.toHaveBeenCalled();
  });

  it("stops polling while the tab is hidden, and polls immediately when it comes back", async () => {
    fetchVersion.mockResolvedValue(version(1));
    const onChange = vi.fn();
    const { unmount } = renderHook(() => useRevision({ actif: true, intervalleMs: 10, onChange }));
    await waitFor(() => expect(fetchVersion).toHaveBeenCalled());

    act(() => changerVisibilite("hidden"));
    const appelsAvant = fetchVersion.mock.calls.length;
    await attendre(60);
    expect(fetchVersion.mock.calls.length).toBe(appelsAvant);

    // Modifié ailleurs pendant que l'onglet était caché : vu dès le retour,
    // sans attendre le tour suivant.
    fetchVersion.mockResolvedValue(version(5));
    act(() => changerVisibilite("visible"));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(version(5)));
    unmount();
  });

  it("does not start polling when mounted in a hidden tab", async () => {
    visibilite = "hidden";
    fetchVersion.mockResolvedValue(version(1));

    const { unmount } = renderHook(() => useRevision({ actif: true, intervalleMs: 5, onChange: vi.fn() }));
    await attendre(40);

    expect(fetchVersion).not.toHaveBeenCalled();
    unmount();
  });

  it("groups several verifierMaintenant() calls after local writes into one check, and reloads once", async () => {
    fetchVersion.mockResolvedValue(version(1));
    const onChange = vi.fn();
    const { result } = renderHook(() =>
      useRevision({ actif: true, intervalleMs: 60_000, onChange, delaiRegroupementMs: 20 }),
    );
    await waitFor(() => expect(result.current.revision).toBe(1));
    const appelsAvant = fetchVersion.mock.calls.length;

    fetchVersion.mockResolvedValue(version(2));
    act(() => {
      result.current.verifierMaintenant();
      result.current.verifierMaintenant();
      result.current.verifierMaintenant();
    });

    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(fetchVersion.mock.calls.length).toBe(appelsAvant + 1);
  });

  it("reloads after a local write even if the very first poll has not answered yet", async () => {
    let repondre: (v: VersionEtat) => void = () => {};
    fetchVersion.mockReturnValueOnce(new Promise<VersionEtat>((resolve) => (repondre = resolve)));
    fetchVersion.mockResolvedValue(version(3));
    const onChange = vi.fn();
    const { result } = renderHook(() =>
      useRevision({ actif: true, intervalleMs: 60_000, onChange, delaiRegroupementMs: 1 }),
    );

    act(() => result.current.verifierMaintenant());
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(version(3)));
    repondre(version(3));
  });

  it("keeps quiet on network errors and tries again on the next round", async () => {
    fetchVersion
      .mockResolvedValueOnce(version(1))
      .mockRejectedValueOnce(new Error("réseau"))
      .mockResolvedValue(version(2));
    const onChange = vi.fn();

    renderHook(() => useRevision({ actif: true, intervalleMs: 10, onChange }));

    await waitFor(() => expect(onChange).toHaveBeenCalledWith(version(2)));
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
