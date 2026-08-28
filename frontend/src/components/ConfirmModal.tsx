import { useEffect, useState } from "react";

import { registerConfirmListener, resolveConfirm, type ConfirmRequest } from "../utils/confirmDialog";

/** Montée UNE fois dans App.tsx — remplace `window.confirm(...)` partout où
 * un forçage est proposé sur conflit (glisser-déposer, placement manuel).
 * Cf. utils/confirmDialog.ts pour le pourquoi. */
export function ConfirmModal() {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);

  useEffect(() => registerConfirmListener(setRequest), []);

  useEffect(() => {
    if (!request) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") resolveConfirm(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [request]);

  if (!request) return null;

  return (
    <div className="confirmmodal-overlay" role="presentation" onClick={() => resolveConfirm(false)}>
      <div
        className="panel confirmmodal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirmmodal-titre"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="confirmmodal-titre">{request.title}</h3>
        <p className="confirmmodal-message">{request.message}</p>
        <div className="confirmmodal-actions">
          <button type="button" className="btn btn--ghost" autoFocus onClick={() => resolveConfirm(false)}>
            {request.cancelLabel}
          </button>
          <button type="button" className="btn btn--accent" onClick={() => resolveConfirm(true)}>
            {request.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
