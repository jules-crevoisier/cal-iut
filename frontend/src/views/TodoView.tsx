import { useMemo } from "react";

import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { buildTodoList } from "../utils/todo";

interface TodoViewProps {
  payload: AppPayload;
  setRoute: (patch: Partial<Route>) => void;
}

export function TodoView({ payload, setRoute }: TodoViewProps) {
  const items = useMemo(() => buildTodoList(payload), [payload]);

  return (
    <section className="view">
      <div className="panel">
        <h3>Ce qui demande une décision</h3>
        <p className="muted">
          Agrégé depuis la sortie brute du solveur : contraintes enseignantes violées, journées trouées. Chaque
          ligne ouvre le créneau concerné.
        </p>
        {items.length === 0 ? (
          <p className="muted">Rien à signaler : aucune contrainte violée, aucune journée trouée.</p>
        ) : (
          <div className="todolist">
            {items.map((it, i) => (
              <button key={i} type="button" className={`todo-item ${it.sev}`} onClick={() => setRoute(it.route)}>
                <span className="sev">{it.sev === "bad" ? "à corriger" : "à revoir"}</span>
                <span>
                  <strong>{it.title}</strong>
                  <div className="sub">{it.sub}</div>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
