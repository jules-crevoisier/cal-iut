/**
 * Nouveau semestre → « Projets de modules » (19/11/2026).
 *
 * Plusieurs modules qui se déroulent dans un ordre (ex. S4 : démarrage de la
 * SAE, back, front, retour sur la SAE), sur au plus N jours par semaine.
 * Une étape peut ne viser qu’une phase d’un module (les TD 5 à 7). Ce sont
 * des préférences : le calcul les suit quand il le peut.
 */
import { useEffect, useState } from "react";

import {
  ajouterProjetModules,
  lireReglesModules,
  retirerRegleModule,
  type ReglesModulesReponse,
} from "../api/client";
import { Ligne } from "./ReglesModules";

interface EtapeSaisie {
  code: string;
  type: string;
  de: string;
  a: string;
}

const ETAPE_VIDE: EtapeSaisie = { code: "", type: "", de: "", a: "" };
const FORMULAIRE_VIDE = { nom: "", jours: "", motif: "" };

function libelleEtape(e: { course_code: string; session_type: string | null; de: number | null; a: number | null }) {
  const phase =
    e.de || e.a
      ? ` (${e.session_type ?? "séances"} ${e.de ?? 1}${e.a ? ` à ${e.a}` : " et suivants"})`
      : e.session_type
        ? ` (${e.session_type})`
        : "";
  return `${e.course_code}${phase}`;
}

export function ProjetsModules({
  groupe,
  onModifie,
}: {
  groupe: string;
  onModifie: () => void;
}) {
  const [donnees, setDonnees] = useState<ReglesModulesReponse | null>(null);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [formulaire, setFormulaire] = useState(FORMULAIRE_VIDE);
  const [etapes, setEtapes] = useState<EtapeSaisie[]>([ETAPE_VIDE, ETAPE_VIDE]);

  useEffect(() => {
    let perime = false;
    setDonnees(null);
    setErreur(null);
    lireReglesModules(groupe)
      .then((r) => {
        if (!perime && Array.isArray(r?.modules)) setDonnees(r);
      })
      .catch(() => undefined);
    return () => {
      perime = true;
    };
  }, [groupe]);

  if (!donnees || donnees.modules.length === 0) return null;

  const verrouille = donnees.verrouille !== null;
  const projets = donnees.projets ?? [];
  const modifierEtape = (i: number, partiel: Partial<EtapeSaisie>) =>
    setEtapes(etapes.map((e, j) => (j === i ? { ...e, ...partiel } : e)));
  const nombre = (texte: string) => (texte.trim() ? Number.parseInt(texte, 10) : null);
  const pret =
    formulaire.nom.trim() &&
    formulaire.motif.trim() &&
    etapes.length >= 2 &&
    etapes.every((e) => e.code);

  const agir = async (action: () => Promise<ReglesModulesReponse>, ensuite?: () => void) => {
    setOccupe(true);
    setErreur(null);
    try {
      setDonnees(await action());
      ensuite?.();
      onModifie();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "L’enregistrement a échoué");
    } finally {
      setOccupe(false);
    }
  };

  return (
    <details className="dates-sae regles-modules">
      <summary>
        <h3>Projets de modules</h3>
        <span className="muted">
          {projets.length === 0 ? "Aucun" : `${projets.length} projet${projets.length > 1 ? "s" : ""}`}
        </span>
      </summary>
      <p className="muted">
        Des modules qui se suivent dans un ordre, sur quelques jours par
        semaine. Le calcul suit ces préférences quand il le peut. Cela vaut
        pour la prochaine génération.
      </p>
      {donnees.verrouille && <p className="muted">{donnees.verrouille}</p>}
      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}

      {projets.length > 0 && (
        <ul>
          {projets.map((p) => (
            <Ligne
              key={p.id}
              titre={`${p.semestre ?? ""} · ${p.nom}`}
              detail={`${p.etapes.map(libelleEtape).join(" → ")}${
                p.jours_par_semaine ? ` · ${p.jours_par_semaine} jour${p.jours_par_semaine > 1 ? "s" : ""} par semaine` : ""
              }`}
              motif={p.motif}
              livree={false}
              retirer={
                !verrouille && (
                  <button
                    type="button"
                    className="btn btn--sm"
                    disabled={occupe}
                    aria-label={`Retirer le projet ${p.nom}`}
                    onClick={() => void agir(() => retirerRegleModule(groupe, "projets", p.id))}
                  >
                    Retirer
                  </button>
                )
              }
            />
          ))}
        </ul>
      )}

      {!verrouille && (
        <form
          className="seances-annulees-ajout"
          onSubmit={(e) => {
            e.preventDefault();
            if (!pret) return;
            void agir(
              () =>
                ajouterProjetModules(groupe, {
                  nom: formulaire.nom.trim(),
                  etapes: etapes.map((s) => ({
                    code: s.code,
                    type: s.type || null,
                    de: nombre(s.de),
                    a: nombre(s.a),
                  })),
                  jours_par_semaine: nombre(formulaire.jours),
                  motif: formulaire.motif.trim(),
                }),
              () => {
                setFormulaire(FORMULAIRE_VIDE);
                setEtapes([ETAPE_VIDE, ETAPE_VIDE]);
              },
            );
          }}
        >
          <label>
            Nom du projet
            <input
              value={formulaire.nom}
              onChange={(e) => setFormulaire({ ...formulaire, nom: e.target.value })}
            />
          </label>
          {etapes.map((etape, i) => (
            <fieldset key={i} className="projet-etape">
              <legend>Étape {i + 1}</legend>
              <label>
                Module
                <select value={etape.code} onChange={(e) => modifierEtape(i, { code: e.target.value })}>
                  <option value="">Choisir…</option>
                  {donnees.modules.map((m) => (
                    <option key={m.code} value={m.code}>
                      {m.semestre} · {m.code} {m.nom}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Type
                <select value={etape.type} onChange={(e) => modifierEtape(i, { type: e.target.value })}>
                  <option value="">Toutes les séances</option>
                  {["CM", "TD", "TP"].map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                De la séance n°
                <input
                  type="number"
                  min={1}
                  value={etape.de}
                  onChange={(e) => modifierEtape(i, { de: e.target.value })}
                />
              </label>
              <label>
                À la séance n°
                <input
                  type="number"
                  min={1}
                  value={etape.a}
                  onChange={(e) => modifierEtape(i, { a: e.target.value })}
                />
              </label>
              {etapes.length > 2 && (
                <button
                  type="button"
                  className="btn btn--sm"
                  onClick={() => setEtapes(etapes.filter((_, j) => j !== i))}
                >
                  Retirer l’étape
                </button>
              )}
            </fieldset>
          ))}
          <button type="button" className="btn btn--sm" onClick={() => setEtapes([...etapes, ETAPE_VIDE])}>
            Ajouter une étape
          </button>
          <label>
            Jours par semaine
            <select
              value={formulaire.jours}
              onChange={(e) => setFormulaire({ ...formulaire, jours: e.target.value })}
            >
              <option value="">Pas de limite</option>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label>
            Motif du projet
            <input
              value={formulaire.motif}
              onChange={(e) => setFormulaire({ ...formulaire, motif: e.target.value })}
            />
          </label>
          <button type="submit" className="btn btn--sm" disabled={occupe || !pret}>
            Ajouter le projet
          </button>
        </form>
      )}
    </details>
  );
}
