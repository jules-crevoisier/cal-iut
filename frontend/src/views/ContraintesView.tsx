/**
 * Contraintes : chaque règle globale avec son verdict, puis la contrainte
 * déclarée de chaque enseignant et son verdict recalculé sur le planning.
 *
 * Refonte du 29/09/2026 : ce qui échoue d'abord, les règles respectées
 * repliées ; les enseignants en tableau (texte déclaré visible, verdict
 * distinguant les vraies indisponibilités non respectées des compromis SAE
 * acceptés), filtrable. Refonte v2 (même jour) : sommaire chiffré en tuiles,
 * dont deux filtrent le tableau ; une carte par bloc. Pas de rouge ici (retour utilisateur 27/08/2026 :
 * « on peut enlever le rouge dans contrainte ») : l'échec est en ambre.
 */

import { useMemo, useRef, useState } from "react";
import { X } from "lucide-react";

import type { Route } from "../hooks/useHashRoute";
import type { AppPayload, TeacherInfo } from "../types/app";
import { ecrireLocal, lireLocal } from "../utils/stockageLocal";
import { ChampRecherche } from "../components/ChampRecherche";
import { Tuile, Tuiles } from "../components/Tuile";
import "../styles/outils.css";
import "./ContraintesView.css";

interface ContraintesViewProps {
  payload: AppPayload;
  setRoute: (patch: Partial<Route>) => void;
}

const CLE_TOUS = "cal-iut:contraintes:tous-les-enseignants:v1";

type FiltreVerdict = "tout" | "conflit" | "compromis";

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
  // Filtre posé par les tuiles « Indisponibilités non respectées » et
  // « Compromis SAE » (refonte v2 du 29/09/2026).
  const [verdictFiltre, setVerdictFiltre] = useState<FiltreVerdict>("tout");
  const refRegles = useRef<HTMLElement>(null);
  const refProfs = useRef<HTMLElement>(null);
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
      (tous || e.t.hasConstraint || verdictFiltre !== "tout") &&
      (verdictFiltre === "tout" ||
        (verdictFiltre === "conflit" && e.v.declarees > 0) ||
        (verdictFiltre === "compromis" && e.v.compromis > 0)) &&
      (!q ||
        normaliser(`${e.t.name} ${e.t.code} ${e.t.rawIndisponibilites} ${e.t.rawDisponibilites} ${e.t.rawContraintes}`).includes(q)),
  );
  const basculerVerdict = (v: FiltreVerdict) => {
    setVerdictFiltre((actuel) => (actuel === v ? "tout" : v));
    requestAnimationFrame(() => refProfs.current?.scrollIntoView?.({ behavior: "smooth", block: "start" }));
  };

  return (
    <section className="view contraintes">
      <Tuiles label="Sommaire des contraintes">
        <Tuile
          libelle="Règles en échec"
          valeur={echecs.length}
          detail={echecs.length ? `sur ${payload.ruleChecks.length} règles` : `les ${payload.ruleChecks.length} sont respectées`}
          ton={echecs.length ? "warn" : "good"}
          onClick={() => refRegles.current?.scrollIntoView?.({ behavior: "smooth", block: "start" })}
          action="Voir les règles"
        />
        {/* Le verdict par enseignant ne couvre pas les listes blanches : la
            règle globale peut échouer quand même, d'où deux tuiles. */}
        <Tuile
          libelle="Indisponibilités non respectées"
          valeur={nonRespectes}
          detail={nonRespectes ? `${pluriel(nonRespectes, "enseignant")} concerné${nonRespectes > 1 ? "s" : ""}` : "aucun enseignant"}
          ton={nonRespectes ? "warn" : undefined}
          nul={nonRespectes === 0}
          onClick={() => basculerVerdict("conflit")}
          actif={verdictFiltre === "conflit"}
          action={verdictFiltre === "conflit" ? "Tout afficher" : "Filtrer"}
        />
        <Tuile
          libelle="Compromis SAE acceptés"
          valeur={avecCompromis}
          detail="encadrement le jour d'un cours"
          nul={avecCompromis === 0}
          onClick={() => basculerVerdict("compromis")}
          actif={verdictFiltre === "compromis"}
          action={verdictFiltre === "compromis" ? "Tout afficher" : "Filtrer"}
        />
        <Tuile
          libelle="Contraintes déclarées"
          valeur={avecContrainte}
          detail={`sur ${pluriel(enseignants.length, "enseignant")}`}
        />
      </Tuiles>

      <section className="panel carte-tableau ctr-panneau" aria-labelledby="ctr-regles" ref={refRegles}>
        <div className="carte-tete">
          <h2 id="ctr-regles">Règles globales du solveur</h2>
          <span className="carte-tete-note">
            {echecs.length} en échec · {reussites.length} respectée{reussites.length > 1 ? "s" : ""}
          </span>
          {reussites.length > 0 && (
            <div className="carte-tete-actions">
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                aria-expanded={voirReussites}
                onClick={() => setVoirReussites((v) => !v)}
              >
                {voirReussites ? "Masquer" : "Afficher"}{" "}
                {reussites.length > 1 ? `les ${reussites.length} règles respectées` : "la règle respectée"}
              </button>
            </div>
          )}
        </div>
        <ul className="ctr-regles">
          {echecs.map((c) => (
            <li key={c.id} className="ctr-regle echec">
              <span className="ctr-statut">
                <span className="ctr-marque" aria-hidden="true" />
                En échec
              </span>
              <span className="ctr-regle-texte">
                <strong>{c.label}</strong>
                <span className="ctr-detail">{c.detail}</span>
              </span>
            </li>
          ))}
          {voirReussites &&
            reussites.map((c) => (
              <li key={c.id} className="ctr-regle ok">
                <span className="ctr-statut">
                  <span className="ctr-marque" aria-hidden="true" />
                  Respectée
                </span>
                <span className="ctr-regle-texte">
                  <strong>{c.label}</strong>
                  <span className="ctr-detail">{c.detail}</span>
                </span>
              </li>
            ))}
          {echecs.length === 0 && !voirReussites && (
            <li className="ctr-regle-rien">Toutes les règles sont respectées.</li>
          )}
        </ul>
      </section>

      <section
        className="panel carte-tableau carte-tableau--haute ctr-panneau"
        aria-labelledby="ctr-profs"
        ref={refProfs}
      >
        <div className="carte-tete">
          <h2 id="ctr-profs">
            Contraintes enseignants <span className="carte-tete-nb">{visibles.length}</span>
          </h2>
          {verdictFiltre !== "tout" && (
            <button type="button" className="pastille" aria-pressed="true" onClick={() => setVerdictFiltre("tout")}>
              {verdictFiltre === "conflit" ? "Indisponibilité non respectée" : "Compromis SAE"}
              <X size={13} aria-hidden="true" />
              <span className="sr-only">(retirer le filtre)</span>
            </button>
          )}
          <div className="carte-tete-actions">
            <ChampRecherche
              className="ctr-recherche"
              placeholder="Filtrer : nom, jour, texte déclaré…"
              libelle="Filtrer les enseignants"
              valeur={texte}
              onChange={(v) => setTexte(v)}
            />
            <label className="ctr-case">
              <input type="checkbox" checked={tous} onChange={(e) => setTous(e.target.checked)} />
              Afficher aussi {pluriel(enseignants.length - avecContrainte, "enseignant")} sans contrainte
            </label>
          </div>
        </div>
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
                      <span className="pill dot warn">{pluriel(v.declarees, "séance")} en conflit</span>
                    ) : (
                      <span className="pill dot good">Respectée</span>
                    )}
                    {v.compromis > 0 && <span className="ctr-compromis">{v.compromis} compromis SAE</span>}
                  </td>
                  <td className="num">{t.nPlaced}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {visibles.length === 0 && <p className="carte-vide">Aucun enseignant ne correspond.</p>}
        <p className="carte-note">
          Texte tel que déclaré dans le fichier CONTRAINTES ENSEIGNANTS, et verdict recalculé sur le planning actuel.
          Cliquer un nom ouvre sa Vue Enseignant.
        </p>
      </section>
    </section>
  );
}
