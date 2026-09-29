/**
 * Onglets en contrôle segmenté (refonte v2 du 29/09/2026, direction
 * « Lumière / Nuit ») : une rangée compacte, l'onglet actif blanc sur fond
 * gris léger. ← / → passent d'un onglet à l'autre (motif ARIA « tabs »,
 * activation automatique).
 */

import "../styles/outils.css";

export interface Onglet<T extends string> {
  id: T;
  label: string;
  nb?: number;
  /** Infobulle du compteur (« Tâches non terminées »…). */
  titreNb?: string;
}

export function Onglets<T extends string>({
  onglets,
  actif,
  onChoisir,
  label,
  prefixeId,
  controle,
}: {
  onglets: Onglet<T>[];
  actif: T;
  onChoisir: (id: T) => void;
  label: string;
  /** Préfixe des `id` des onglets (`${prefixeId}-${id}`). */
  prefixeId: string;
  /** `id` du panneau commandé. */
  controle: string;
}) {
  return (
    <div className="segmente" role="tablist" aria-label={label}>
      {onglets.map((o, i) => (
        <button
          key={o.id}
          type="button"
          role="tab"
          id={`${prefixeId}-${o.id}`}
          aria-selected={actif === o.id}
          aria-controls={controle}
          tabIndex={actif === o.id ? 0 : -1}
          onClick={() => onChoisir(o.id)}
          onKeyDown={(e) => {
            const sens = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
            if (!sens) return;
            e.preventDefault();
            const suivant = onglets[(i + sens + onglets.length) % onglets.length];
            onChoisir(suivant.id);
            document.getElementById(`${prefixeId}-${suivant.id}`)?.focus();
          }}
        >
          {o.label}
          {o.nb !== undefined && (
            <span className="segmente-nb" title={o.titreNb}>
              {o.nb}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
