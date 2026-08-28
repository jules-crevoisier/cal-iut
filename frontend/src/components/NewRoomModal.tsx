import { useEffect, useState } from "react";

import { creerSalle } from "../api/client";

interface NewRoomModalProps {
  /** Appelé avec la salle créée — l'appelant s'en sert pour l'appliquer
   * immédiatement à la séance en cours d'édition. */
  onCreated: (room: { id: string; label: string }) => void;
  onCancel: () => void;
}

/** Création d'une salle hors bâtiment — retour utilisateur 28/08/2026 :
 * « il se peut que l'on utilise des salles autres que dans le bâtiment, il
 * faut donc laisser la possibilité de créer une salle ».
 *
 * Vraie modale interne (mêmes styles que `ConfirmModal`) et pas
 * `window.prompt` : les popups navigateur sont désactivées chez
 * l'utilisateur, `prompt` y renvoie `null` en silence — c'est exactement le
 * bug qui avait motivé `utils/confirmDialog.ts`. */
export function NewRoomModal({ onCreated, onCancel }: NewRoomModalProps) {
  const [label, setLabel] = useState("");
  const [capacity, setCapacity] = useState(30);
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  const valider = async () => {
    const nom = label.trim();
    if (!nom) {
      setErreur("Donnez un nom à la salle.");
      return;
    }
    setEnCours(true);
    setErreur(null);
    try {
      const salle = await creerSalle({ label: nom, capacity });
      onCreated({ id: salle.id, label: salle.label });
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Création impossible");
    } finally {
      setEnCours(false);
    }
  };

  return (
    <div className="confirmmodal-overlay" role="presentation" onClick={onCancel}>
      <form
        className="panel confirmmodal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="newroom-titre"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          void valider();
        }}
      >
        <h3 id="newroom-titre">Nouvelle salle</h3>
        <p className="muted small">
          Pour une salle hors bâtiment (autre site, salle empruntée…). Elle sera proposée au choix manuel de
          salle, mais la génération automatique ne l'utilisera jamais d'elle-même.
        </p>

        <label className="newroom-field">
          Nom de la salle
          <input
            type="text"
            value={label}
            autoFocus
            maxLength={80}
            placeholder="ex. Amphi Descartes"
            onChange={(e) => setLabel(e.target.value)}
          />
        </label>

        <label className="newroom-field">
          Capacité
          <input
            type="number"
            min={1}
            max={1000}
            value={capacity}
            onChange={(e) => setCapacity(Math.max(1, Number(e.target.value) || 1))}
          />
        </label>

        {erreur && <p className="alerte">{erreur}</p>}

        <div className="confirmmodal-actions">
          <button type="button" className="btn btn--ghost" onClick={onCancel}>
            Annuler
          </button>
          <button type="submit" className="btn btn--accent" disabled={enCours}>
            {enCours ? "Création…" : "Créer et utiliser"}
          </button>
        </div>
      </form>
    </div>
  );
}
