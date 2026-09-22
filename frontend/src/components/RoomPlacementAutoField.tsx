import { useEffect, useState } from "react";

import { fetchMoi, modifierSalle } from "../api/client";

interface RoomPlacementAutoFieldProps {
  roomId: string;
  placementAuto: boolean;
  /** Appelé après une sauvegarde réussie — permet à l'appelant de mettre à
   * jour son propre état local (le payload global n'est rafraîchi qu'au
   * prochain chargement complet). */
  onSaved?: (placementAuto: boolean) => void;
}

/**
 * Case « Proposée au placement automatique », réservée admin (`PATCH
 * /rooms/{room_id}`) — retour utilisateur 22/09/2026 : « supprimer la BU du
 * placement automatique des salles car elle est utilisée pour un seul
 * module, celui de Valérie Mariot ». La salle reste choisissable à la main
 * dans tous les cas, cette case ne pilote QUE le placement automatique.
 *
 * Interroge `fetchMoi()` elle-même (plutôt qu'un rôle reçu en prop) : la
 * fiche salle (`SalleView.tsx`) n'a pas accès au rôle courant sans passer
 * par `App.tsx`, hors de mon périmètre de fichiers sur cet item.
 */
export function RoomPlacementAutoField({ roomId, placementAuto, onSaved }: RoomPlacementAutoFieldProps) {
  const [estAdmin, setEstAdmin] = useState(false);
  const [valeur, setValeur] = useState(placementAuto);
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    setValeur(placementAuto);
  }, [placementAuto]);

  useEffect(() => {
    let annule = false;
    fetchMoi().then((moi) => {
      if (!annule) setEstAdmin(moi?.role === "admin");
    });
    return () => {
      annule = true;
    };
  }, []);

  if (!estAdmin) return null;

  const basculer = async (coche: boolean) => {
    const precedent = valeur;
    setValeur(coche);
    setEnCours(true);
    setErreur(null);
    try {
      const salle = await modifierSalle(roomId, { placement_auto: coche });
      setValeur(salle.placement_auto);
      onSaved?.(salle.placement_auto);
    } catch (e) {
      setValeur(precedent);
      setErreur(e instanceof Error ? e.message : "Modification impossible");
    } finally {
      setEnCours(false);
    }
  };

  return (
    <div className="newroom-field newroom-field--checkbox">
      <label>
        <input
          type="checkbox"
          checked={valeur}
          disabled={enCours}
          onChange={(e) => void basculer(e.target.checked)}
        />
        Proposée au placement automatique
      </label>
      <p className="muted small">
        Décochez pour une salle réservée à un usage précis (ex. BU) : elle reste choisissable à la main.
      </p>
      {erreur && <p className="alerte small">{erreur}</p>}
    </div>
  );
}
