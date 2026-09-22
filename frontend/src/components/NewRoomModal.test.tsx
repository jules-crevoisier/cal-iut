/**
 * Case « Proposée au placement automatique » — retour utilisateur
 * 22/09/2026 : « supprimer la BU du placement automatique des salles car
 * elle est utilisée pour un seul module, celui de Valérie Mariot ».
 * Cochée par défaut ; décochée, `creerSalle` doit recevoir
 * `placement_auto: false`.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NewRoomModal } from "./NewRoomModal";

const creerSalle = vi.fn().mockResolvedValue({
  id: "amphi-descartes",
  label: "Amphi Descartes",
  capacity: 120,
  room_type: "standard",
  placement_auto: true,
});
vi.mock("../api/client", async (importOriginal) => {
  const reel = await importOriginal<typeof import("../api/client")>();
  return { ...reel, creerSalle: (...args: unknown[]) => creerSalle(...args) };
});

describe("NewRoomModal", () => {
  it("should have the placement-automatique checkbox checked by default", () => {
    render(<NewRoomModal onCreated={vi.fn()} onCancel={vi.fn()} />);
    const case_ = screen.getByRole("checkbox", { name: /placement automatique/i });
    expect(case_).toBeChecked();
  });

  it("should send placement_auto: true by default", async () => {
    render(<NewRoomModal onCreated={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/amphi descartes/i), { target: { value: "Amphi X" } });
    fireEvent.click(screen.getByRole("button", { name: /créer et utiliser/i }));
    await vi.waitFor(() => expect(creerSalle).toHaveBeenCalled());
    expect(creerSalle).toHaveBeenCalledWith(
      expect.objectContaining({ label: "Amphi X", placement_auto: true }),
    );
  });

  it("should send placement_auto: false once the checkbox is unchecked (ex. BU)", async () => {
    render(<NewRoomModal onCreated={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/amphi descartes/i), { target: { value: "BU / A.123" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /placement automatique/i }));
    fireEvent.click(screen.getByRole("button", { name: /créer et utiliser/i }));
    await vi.waitFor(() => expect(creerSalle).toHaveBeenCalled());
    expect(creerSalle).toHaveBeenCalledWith(
      expect.objectContaining({ label: "BU / A.123", placement_auto: false }),
    );
  });

  it("should show the hint explaining what unchecking means", () => {
    render(<NewRoomModal onCreated={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByText(/réservée à un usage précis/i)).toBeInTheDocument();
  });
});
