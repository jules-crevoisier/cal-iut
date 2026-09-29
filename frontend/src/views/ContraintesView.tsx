/**
 * Contraintes : chaque règle globale avec son verdict, puis la contrainte
 * déclarée de chaque enseignant et son verdict recalculé sur le planning.
 *
 * Refonte du 29/09/2026 : ce qui échoue d'abord, les règles respectées
 * repliées ; les enseignants en tableau (texte déclaré visible, verdict
 * distinguant les vraies indisponibilités non respectées des compromis SAE
 * acceptés), filtrable. Pas de rouge ici (retour utilisateur 27/08/2026 :
 * « on peut enlever le rouge dans contrainte ») : l'échec est en ambre.
 */

import { useMemo, useState } from "react";

import type { Route } from "../hooks/useHashRoute";
import type { AppPayload, TeacherInfo } from "../types/app";
import { ecrireLocal, lireLocal } from "../utils/stockageLocal";
import "./ContraintesView.css";

interface ContraintesViewProps {
  payload: AppPayload;
  setRoute: (patch: Partial<Route>) => void;
}

const CLE_TOUS = "cal-iut:contraintes:tous-les-enseignants:v1";

function normaliser(t: string): string {
  return t
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
}

interface Verdict {
  rang: number;
  declarees: number;
  compromis: number;
}

function verdict(t: TeacherInfo): Verdict {
  const compromis = t.violations.filter((v) => v.reason === "sae_supervision").length;
  const declarees = t.violations.length - compromis;
  const rang = declarees > 0 ? 0 : compromis > 0 ? 1 : t.hasConstraint ? 2 : 3;
  return { rang, declarees, compromis };
}

function pluriel(n: number, mot: string): string {
  return `${n} ${mot}${n > 1 ? "s" : ""}`;
}

export function ContraintesView({ payload, setRoute }: ContraintesViewProps) {
  const echecs = payload.ruleChecks.filter((c) => c.status !== "pass");
  const reussites = payload.ruleChecks.filter((c) => c.status === "pass");
  const [voirReussites, setVoirReussites] = useState(false);

  const [texte, setTexte] = useState("");
  const [tous, setTousState] = useState<boolean>(() => lireLocal(CLE_TOUS, false, (v): v is boolean => typeof v === "boolean"));
  const setTous = (v: boolean) => {
    setTousState(v);
    ecrireLocal(CLE_TOUS, v);
  };

  const enseignants = useMemo(
    () =>
      payload.teachers
        .map((t) => ({ t, v: verdict(t) }))
        .sort((a, b) => a.v.rang - b.v.rang || b.v.declarees - a.v.declarees || a.t.name.localeCompare(b.t.name, "fr")),
    [payload.teachers],
  );
  const avecContrainte = enseignants.filter((e) => e.t.hasConstraint).length;
  const nonRespectes = enseignants.filter((e) => e.v.declarees > 0).length;
  const avecCompromis = enseignants.filter((e) => e.v.compromis > 0).length;
  const q = normaliser(texte.trim());
  const visibles = enseignants.filter(
    (e) =>
      (tous || e.t.hasConstraint) &&
      (!q ||
        normaliser(`${e.t.name} ${e.t.code} ${e.t.rawIndisponibilites} ${e.t.rawDisponibilites} ${e.t.rawContraintes}`).includes(q)),
  );

  return (
    <section className="view contraintes">
      <p className="ctr-resume">
        <span className={echecs.length ? "ctr-resume-warn" : "ctr-resume-ok"}>
          {echecs.length
            ? `${pluriel(echecs.length, "règle")} en échec sur ${payload.ruleChecks.length}`
            : `Les ${payload.ruleChecks.length} règles sont respectées`}
        </span>
        {/* Seulement s'il y en a : le verdict par enseignant ne couvre pas les
            listes blanches, la règle globale peut échouer quand même, et
            « tout est respecté » serait alors faux. */}
        {nonRespectes > 0 && (
          <>
            <span className="ctr-sep" aria-hidden="true">
              ·
            </span>
            <span className="ctr-resume-warn">
              {pluriel(nonRespectes, "enseignant")} dont une indisponibilité n'est pas respectée
            </span>
          </>
        )}
        {avecCompromis > 0 && (
          <>
            <span className="ctr-sep" aria-hidden="true">
              ·
            </span>
            <span>{pluriel(avecCompromis, "enseignant")} avec un compromis SAE accepté</span>
          </>
        )}
      </p>

      <section className="panel ctr-panneau" aria-labelledby="ctr-regles">
        <h3 id="ctr-regles">Règles globales du solveur</h3>
        <ul className="ctr-regles">
          {echecs.map((c) => (
            <li key={c.id} className="ctr-regle echec">
              <span className="ctr-statut">En échec</span>
              <span className="ctr-regle-texte">
                <strong>{c.label}</strong>
                <span className="ctr-detail">{c.detail}</span>
              </span>
            </li>
          ))}
          {voirReussites &&
            reussites.map((c) => (
              <li key={c.id} className="ctr-regle ok">
                <span className="ctr-statut">Respectée</span>
                <span className="ctr-regle-texte">
                  <strong>{c.label}</strong>
                  <span className="ctr-detail">{c.detail}</span>
                </span>
              </li>
            ))}
        </ul>
        {reussites.length > 0 && (
          <button
            type="button"
            className="btn btn--ghost btn--sm ctr-bascule"
            aria-expanded={voirReussites}
            onClick={() => setVoirReussites((v) => !v)}
          >
            {voirReussites ? "Masquer" : "Afficher"}{" "}
            {reussites.length > 1 ? `les ${reussites.length} règles respectées` : "la règle respectée"}
          </button>
        )}
      </section>

      <section className="panel ctr-panneau ctr-panneau--tableau" aria-labelledby="ctr-profs">
        <div className="ctr-tete">
          <h3 id="ctr-profs">Contraintes enseignants</h3>
          <input
            type="search"
            placeholder="Filtrer : nom, jour, texte déclaré…"
            aria-label="Filtrer les enseignants"
            value={texte}
            onChange={(e) => setTexte(e.target.value)}
          />
          <label className="ctr-case">
            <input type="checkbox" checked={tous} onChange={(e) => setTous(e.target.checked)} />
            Afficher aussi {pluriel(enseignants.length - avecContrainte, "enseignant")} sans contrainte
          </label>
        </div>
        <p className="ctr-aide">
          Texte tel que déclaré dans le fichier CONTRAINTES ENSEIGNANTS, et verdict recalculé sur le planning actuel.
          Cliquer un nom ouvre sa Vue Enseignant.
        </p>
        <div className="ref-table-wrap">
          <table className="ref ctr-table">
            <thead>
              <tr>
                <th>Enseignant</th>
                <th>Déclaré</th>
                <th>Verdict</th>
                <th className="num">Séances</th>
              </tr>
            </thead>
            <tbody>
              {visibles.map(({ t, v }) => {
                const declare = [
                  t.rawIndisponibilites && `Indisponible : ${t.rawIndisponibilites}`,
                  t.rawDisponibilites && `Disponible : ${t.rawDisponibilites}`,
                  t.rawContraintes,
                ].filter(Boolean) as string[];
                return (
                  <tr key={t.code}>
                    <td>
                      <button type="button" className="ctr-nom" onClick={() => setRoute({ vue: "prof", prof: t.code })}>
                        {t.name}
                      </button>{" "}
                      <span className="mono ctr-code">{t.code}</span>
                    </td>
                    <td className="ctr-declare">
                      {declare.length ? declare.map((l, i) => <div key={i}>{l}</div>) : <span className="ctr-faible">—</span>}
                    </td>
                    <td className="ctr-verdict">
                      {!t.hasConstraint ? (
                        <span className="ctr-faible">Aucune contrainte</span>
                      ) : v.declarees > 0 ? (
                        <span className="pill warn">{pluriel(v.declarees, "séance")} en conflit</span>
                      ) : (
                        <span className="pill good">Respectée</span>
                      )}
                      {v.compromis > 0 && <span className="ctr-compromis">{v.compromis} compromis SAE</span>}
                    </td>
                    <td className="num">{t.nPlaced}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {visibles.length === 0 && <p className="ctr-vide">Aucun enseignant ne correspond.</p>}
        </div>
      </section>
    </section>
  );
}
