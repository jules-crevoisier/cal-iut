import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";

interface ContraintesViewProps {
  payload: AppPayload;
  setRoute: (patch: Partial<Route>) => void;
}

export function ContraintesView({ payload, setRoute }: ContraintesViewProps) {
  return (
    <section className="view">
      <div className="panel">
        <h3>Règles globales du solveur</h3>
        <div className="rule-grid">
          {payload.ruleChecks.map((c) => (
            <div key={c.id} className={`check ${c.status === "pass" ? "pass" : "fail"}`}>
              <span className="icon">{c.status === "pass" ? "✓" : "!"}</span>
              <span className="txt">
                <b>{c.label}</b>
                <div className="sub">{c.detail}</div>
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <h3>Contraintes enseignants</h3>
        <p className="muted">
          Texte brut tel que déclaré dans le fichier CONTRAINTES ENSEIGNANTS, et verdict recalculé depuis la sortie
          brute du solveur.
        </p>
        <div className="teacherlist">
          {payload.teachers.map((t) => (
            <button
              key={t.code}
              type="button"
              className={`check clickable ${!t.hasConstraint ? "" : t.violations.length ? "fail" : "pass"}`}
              onClick={() => setRoute({ vue: "prof", prof: t.code })}
            >
              <span className="icon">{!t.hasConstraint ? "i" : t.violations.length ? "!" : "✓"}</span>
              <span className="txt">
                <b>{t.name}</b>
                <div className="sub">
                  {!t.hasConstraint
                    ? "Aucune contrainte déclarée."
                    : t.violations.length
                      ? `${t.violations.length} violation(s) sur ${t.nPlaced} séance(s).`
                      : `Respectée sur ${t.nPlaced} séance(s).`}
                </div>
              </span>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
