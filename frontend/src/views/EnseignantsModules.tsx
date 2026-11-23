/**
 * Nouveau semestre → « Enseignants d’un module » (17/11/2026).
 *
 * Trois règles qui passaient par un fichier et un développeur, pour les
 * modules assurés par plusieurs enseignants :
 * - la répartition des TD et des TP entre eux (à tour de rôle, par groupes
 *   entiers, l’un après l’autre) ;
 * - l’ordre dans le semestre (les séances de l’un plutôt avant celles de
 *   l’autre) ;
 * - les duos : deux enseignants font leurs TP en même temps, dans deux
 *   salles voisines.
 */
import { useEffect, useState } from "react";

import {
  ajouterDuoModule,
  ajouterOrdreModule,
  ajouterRepartitionModule,
  lireReglesModules,
  retirerRegleModule,
  type DuoModule,
  type EnseignantRegle,
  type ModuleRegle,
  type ReglesModulesReponse,
} from "../api/client";
import { ChoixModule, Ligne } from "./ReglesModules";

const REPARTITION_VIDE = {
  code: "",
  type: "",
  mode: "alterne",
  premier: "",
  motif: "",
};
const ORDRE_VIDE = { code: "", premier: "", second: "", motif: "" };
const DUO_VIDE = {
  code: "",
  un: "",
  deux: "",
  salleUn: "",
  salleDeux: "",
  type: "TP",
  de: "",
  a: "",
  groupes: {} as Record<string, string>,
  motif: "",
};

function noms(liste: EnseignantRegle[], lien = ", "): string {
  return liste.map((e) => e.nom).join(lien);
}

/** « Kyllian BRESSON (TP A, C) et Kévin NGO (TP B, D), en H.017 et H.022 ». */
export function libelleDuo(d: DuoModule): string {
  const type = d.type ?? "TP";
  const qui = d.enseignants
    .map((e) => {
      const groupes = d.groupes[e.code] ?? [];
      return groupes.length > 0
        ? `${e.nom} (${type} ${groupes.join(", ")})`
        : e.nom;
    })
    .join(" et ");
  const lieu =
    d.salles.length > 0
      ? `, en ${d.salles.map((s) => s.label).join(" et ")}`
      : "";
  const rangs =
    d.de || d.a
      ? ` · ${type} ${d.de ?? 1}${d.a ? ` à ${d.a}` : " et suivants"}`
      : type === "TD"
        ? " · TD"
        : "";
  return `${qui}${lieu}${rangs}`;
}

function ChoixEnseignant({
  titre,
  enseignants,
  valeur,
  vide,
  onChange,
}: {
  titre: string;
  enseignants: EnseignantRegle[];
  valeur: string;
  vide: string;
  onChange: (code: string) => void;
}) {
  return (
    <label>
      {titre}
      <select
        value={valeur}
        disabled={enseignants.length === 0}
        aria-label={titre}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{vide}</option>
        {enseignants.map((e) => (
          <option key={e.code} value={e.code}>
            {e.nom}
          </option>
        ))}
      </select>
    </label>
  );
}

function Motif({
  quoi,
  valeur,
  onChange,
}: {
  quoi: string;
  valeur: string;
  onChange: (motif: string) => void;
}) {
  return (
    <label className="seances-annulees-motif">
      Motif
      <input
        type="text"
        value={valeur}
        maxLength={300}
        aria-label={`Motif ${quoi}`}
        placeholder="Qui le demande, et pourquoi"
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

export function EnseignantsModules({
  groupe,
  onModifie,
}: {
  groupe: string;
  onModifie: () => void;
}) {
  const [donnees, setDonnees] = useState<ReglesModulesReponse | null>(null);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [repartition, setRepartition] = useState(REPARTITION_VIDE);
  const [ordre, setOrdre] = useState(ORDRE_VIDE);
  const [duo, setDuo] = useState(DUO_VIDE);

  useEffect(() => {
    let perime = false;
    setDonnees(null);
    setErreur(null);
    lireReglesModules(groupe)
      .then((r) => {
        if (
          !perime &&
          Array.isArray(r?.modules) &&
          Array.isArray(r?.repartitions) &&
          Array.isArray(r?.ordres) &&
          Array.isArray(r?.duos)
        )
          setDonnees(r);
      })
      .catch(() => undefined);
    return () => {
      perime = true;
    };
  }, [groupe]);

  if (!donnees) return null;

  // Seuls les modules à plusieurs enseignants ont quelque chose à régler.
  const tdTp = (m: ModuleRegle) => (m.enseignants ?? []).filter((e) => e.td_tp);
  // Les SAE ont leurs propres réglages (dates, référent) : pas ici.
  const aPlusieurs = donnees.modules.filter(
    (m) =>
      (m.enseignants ?? []).length >= 2 &&
      ["CM", "TD", "TP"].some((t) => (m.types[t] ?? 0) > 0),
  );
  const aRepartir = donnees.modules.filter((m) => tdTp(m).length >= 2);
  const enDuo = aRepartir.filter(
    (m) => (m.types.TP ?? 0) > 0 || (m.types.TD ?? 0) > 0,
  );
  const n =
    donnees.repartitions.length + donnees.ordres.length + donnees.duos.length;
  if (aPlusieurs.length === 0 && n === 0) return null;

  const verrouille = donnees.verrouille !== null;
  const module = (code: string) => donnees.modules.find((m) => m.code === code);

  const agir = async (
    action: () => Promise<ReglesModulesReponse>,
    ensuite?: () => void,
  ) => {
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

  const boutonRetirer = (
    nom: "repartitions" | "ordres" | "duos",
    id: string | null,
    quoi: string,
  ) =>
    !verrouille &&
    id && (
      <button
        type="button"
        className="btn btn--sm"
        disabled={occupe}
        aria-label={`Retirer la règle ${quoi}`}
        onClick={() => void agir(() => retirerRegleModule(groupe, nom, id))}
      >
        Retirer
      </button>
    );

  const titre = (r: { code: string; nom: string }) => (
    <>
      <strong>{r.code}</strong> <span>{r.nom}</span>
    </>
  );

  const moduleRepartition = module(repartition.code);
  const typesRepartition = Object.keys(moduleRepartition?.types ?? {}).filter(
    (t) => ["TD", "TP"].includes(t),
  );
  const repartitionPrete = repartition.code && repartition.motif.trim();

  const enseignantsOrdre = module(ordre.code)?.enseignants ?? [];
  const ordrePret =
    ordre.code &&
    ordre.premier &&
    ordre.second &&
    ordre.premier !== ordre.second &&
    ordre.motif.trim();

  const moduleDuo = module(duo.code);
  const enseignantsDuo = moduleDuo ? tdTp(moduleDuo) : [];
  // Les groupes déjà confiés à un autre duo du module ne sont plus à prendre.
  const typesDuo = ["TD", "TP"].filter((t) => (moduleDuo?.types[t] ?? 0) > 0);
  const groupesPris = new Set(
    donnees.duos
      .filter((d) => d.code === duo.code && (d.type ?? "TP") === duo.type)
      .flatMap((d) => Object.values(d.groupes).flat()),
  );
  const groupesLibres =
    (duo.type === "TD"
      ? moduleDuo?.groupes_td
      : (moduleDuo?.groupes_tp ?? [])) ?? [];
  const groupesAPrendre = groupesLibres.filter((g) => !groupesPris.has(g));
  // Les TP se font dans deux salles voisines ; les TD, dans les salles habituelles.
  const sallesDuo = duo.type === "TP";
  const duoPret =
    duo.code &&
    duo.un &&
    duo.deux &&
    duo.un !== duo.deux &&
    (!sallesDuo ||
      (duo.salleUn && duo.salleDeux && duo.salleUn !== duo.salleDeux)) &&
    duo.motif.trim();
  const groupesDe = (code: string) =>
    Object.entries(duo.groupes)
      .filter(([, qui]) => qui === code)
      .map(([g]) => g);

  return (
    <details className="dates-sae regles-modules">
      <summary>
        <h3>Enseignants d’un module</h3>
        <span className="muted">
          {n === 0 ? "Aucune règle" : `${n} règle${n > 1 ? "s" : ""}`}
        </span>
      </summary>
      <p className="muted">
        Pour les modules assurés par plusieurs enseignants : qui prend quelles
        séances, dans quel ordre, et qui travaille en même temps que qui. Le
        nombre d’heures de chacun ne change pas. Cela vaut pour la prochaine
        génération.
      </p>
      {donnees.verrouille && <p className="muted">{donnees.verrouille}</p>}
      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}

      <h4>Répartition des TD et des TP</h4>
      <p className="muted regles-modules-motif">
        Sans règle, les enseignants se suivent : le premier assure toutes ses
        séances, puis le suivant.
      </p>
      {donnees.repartitions.length > 0 && (
        <ul>
          {donnees.repartitions.map((r, i) => (
            <Ligne
              key={r.id ?? `livree-${i}`}
              titre={titre(r)}
              detail={
                `${r.type ? `les ${r.type}` : "les TD et les TP"} : ${r.libelle.toLowerCase()}` +
                (r.ordre.length > 0
                  ? `, en commençant par ${noms(r.ordre, " puis ")}`
                  : "")
              }
              motif={r.motif}
              livree={r.origine === "livree"}
              retirer={boutonRetirer(
                "repartitions",
                r.id,
                `de répartition de ${r.code}`,
              )}
            />
          ))}
        </ul>
      )}
      {!verrouille && aRepartir.length > 0 && (
        <form
          className="seances-annulees-ajout"
          onSubmit={(e) => {
            e.preventDefault();
            if (!repartitionPrete) return;
            void agir(
              () =>
                ajouterRepartitionModule(groupe, {
                  code: repartition.code,
                  type: repartition.type || null,
                  mode: repartition.mode,
                  // Le premier choisi passe devant, les autres gardent leur ordre.
                  ordre: repartition.premier
                    ? [
                        repartition.premier,
                        ...tdTp(moduleRepartition!)
                          .map((x) => x.code)
                          .filter((c) => c !== repartition.premier),
                      ]
                    : [],
                  motif: repartition.motif.trim(),
                }),
              () => setRepartition(REPARTITION_VIDE),
            );
          }}
        >
          <ChoixModule
            modules={aRepartir}
            valeur={repartition.code}
            onChange={(code) =>
              setRepartition({ ...repartition, code, type: "", premier: "" })
            }
          />
          <label>
            Séances
            <select
              value={repartition.type}
              aria-label="Séances à répartir"
              onChange={(e) =>
                setRepartition({ ...repartition, type: e.target.value })
              }
            >
              <option value="">TD et TP</option>
              {typesRepartition.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label>
            Répartition
            <select
              value={repartition.mode}
              aria-label="Façon de répartir"
              onChange={(e) =>
                setRepartition({ ...repartition, mode: e.target.value })
              }
            >
              {donnees.modes.map((m) => (
                <option key={m.mode} value={m.mode}>
                  {m.libelle}
                </option>
              ))}
            </select>
          </label>
          <ChoixEnseignant
            titre="Qui commence"
            enseignants={moduleRepartition ? tdTp(moduleRepartition) : []}
            valeur={repartition.premier}
            vide="Comme dans la maquette"
            onChange={(premier) => setRepartition({ ...repartition, premier })}
          />
          <Motif
            quoi="de la répartition"
            valeur={repartition.motif}
            onChange={(motif) => setRepartition({ ...repartition, motif })}
          />
          <button
            type="submit"
            className="btn btn--sm"
            disabled={occupe || !repartitionPrete}
          >
            Ajouter la répartition
          </button>
        </form>
      )}

      <h4>Ordre dans le semestre</h4>
      <p className="muted regles-modules-motif">
        Les séances du premier se placent plutôt avant celles du second. C’est
        une préférence : le calcul la suit quand il le peut.
      </p>
      {donnees.ordres.length > 0 && (
        <ul>
          {donnees.ordres.map((r, i) => (
            <Ligne
              key={r.id ?? `livree-${i}`}
              titre={titre(r)}
              detail={`d’abord ${noms(r.ordre, ", puis ")}`}
              motif={r.motif}
              livree={r.origine === "livree"}
              retirer={boutonRetirer("ordres", r.id, `d’ordre de ${r.code}`)}
            />
          ))}
        </ul>
      )}
      {!verrouille && aPlusieurs.length > 0 && (
        <form
          className="seances-annulees-ajout"
          onSubmit={(e) => {
            e.preventDefault();
            if (!ordrePret) return;
            void agir(
              () =>
                ajouterOrdreModule(groupe, {
                  code: ordre.code,
                  ordre: [ordre.premier, ordre.second],
                  motif: ordre.motif.trim(),
                }),
              () => setOrdre(ORDRE_VIDE),
            );
          }}
        >
          <ChoixModule
            modules={aPlusieurs}
            valeur={ordre.code}
            onChange={(code) =>
              setOrdre({ ...ORDRE_VIDE, code, motif: ordre.motif })
            }
          />
          <ChoixEnseignant
            titre="D’abord"
            enseignants={enseignantsOrdre}
            valeur={ordre.premier}
            vide="Choisir…"
            onChange={(premier) => setOrdre({ ...ordre, premier })}
          />
          <ChoixEnseignant
            titre="Ensuite"
            enseignants={enseignantsOrdre.filter(
              (e) => e.code !== ordre.premier,
            )}
            valeur={ordre.second}
            vide="Choisir…"
            onChange={(second) => setOrdre({ ...ordre, second })}
          />
          <Motif
            quoi="de l’ordre"
            valeur={ordre.motif}
            onChange={(motif) => setOrdre({ ...ordre, motif })}
          />
          <button
            type="submit"
            className="btn btn--sm"
            disabled={occupe || !ordrePret}
          >
            Ajouter l’ordre
          </button>
        </form>
      )}

      <h4>Duos d’enseignants</h4>
      <p className="muted regles-modules-motif">
        Deux enseignants font leurs séances du module en même temps, chacun avec
        ses groupes : les TP dans deux salles voisines, les TD dans leurs salles
        habituelles, pour toutes les séances ou seulement certaines.
      </p>
      {donnees.duos.length > 0 && (
        <ul>
          {donnees.duos.map((d, i) => (
            <Ligne
              key={d.id ?? `livree-${i}`}
              titre={titre(d)}
              detail={libelleDuo(d)}
              motif={d.motif}
              livree={d.origine === "livree"}
              retirer={boutonRetirer(
                "duos",
                d.id,
                `de duo ${d.code} ${noms(d.enseignants, " et ")}`,
              )}
            />
          ))}
        </ul>
      )}
      {!verrouille && enDuo.length > 0 && (
        <form
          className="seances-annulees-ajout"
          onSubmit={(e) => {
            e.preventDefault();
            if (!duoPret) return;
            const partage = {
              [duo.un]: groupesDe(duo.un),
              [duo.deux]: groupesDe(duo.deux),
            };
            void agir(
              () =>
                ajouterDuoModule(groupe, {
                  code: duo.code,
                  enseignants: [duo.un, duo.deux],
                  salles: sallesDuo ? [duo.salleUn, duo.salleDeux] : [],
                  groupes:
                    partage[duo.un].length > 0 && partage[duo.deux].length > 0
                      ? partage
                      : {},
                  type: duo.type as "TD" | "TP",
                  de: duo.de.trim() ? Number.parseInt(duo.de, 10) : null,
                  a: duo.a.trim() ? Number.parseInt(duo.a, 10) : null,
                  motif: duo.motif.trim(),
                }),
              () => setDuo(DUO_VIDE),
            );
          }}
        >
          <ChoixModule
            modules={enDuo}
            valeur={duo.code}
            onChange={(code) => {
              const types = ["TD", "TP"].filter(
                (t) => (module(code)?.types[t] ?? 0) > 0,
              );
              setDuo({
                ...DUO_VIDE,
                code,
                type: types.includes("TP") ? "TP" : (types[0] ?? "TP"),
                motif: duo.motif,
              });
            }}
          />
          <label>
            Type de séance
            <select
              value={duo.type}
              aria-label="Type de séance du duo"
              onChange={(e) =>
                setDuo({
                  ...duo,
                  type: e.target.value,
                  groupes: {},
                  salleUn: "",
                  salleDeux: "",
                })
              }
            >
              {(typesDuo.length > 0 ? typesDuo : ["TP"]).map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label>
            De la séance n° (facultatif)
            <input
              type="number"
              min={1}
              value={duo.de}
              onChange={(e) => setDuo({ ...duo, de: e.target.value })}
            />
          </label>
          <label>
            À la séance n° (facultatif)
            <input
              type="number"
              min={1}
              value={duo.a}
              onChange={(e) => setDuo({ ...duo, a: e.target.value })}
            />
          </label>
          <ChoixEnseignant
            titre="Premier enseignant"
            enseignants={enseignantsDuo}
            valeur={duo.un}
            vide="Choisir…"
            onChange={(un) => setDuo({ ...duo, un, groupes: {} })}
          />
          {sallesDuo && (
            <label>
              Sa salle
              <select
                value={duo.salleUn}
                aria-label="Salle du premier enseignant"
                onChange={(e) => setDuo({ ...duo, salleUn: e.target.value })}
              >
                <option value="">Choisir…</option>
                {donnees.salles.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <ChoixEnseignant
            titre="Second enseignant"
            enseignants={enseignantsDuo.filter((e) => e.code !== duo.un)}
            valeur={duo.deux}
            vide="Choisir…"
            onChange={(deux) => setDuo({ ...duo, deux, groupes: {} })}
          />
          {sallesDuo && (
            <label>
              Sa salle
              <select
                value={duo.salleDeux}
                aria-label="Salle du second enseignant"
                onChange={(e) => setDuo({ ...duo, salleDeux: e.target.value })}
              >
                <option value="">Choisir…</option>
                {donnees.salles
                  .filter((s) => s.id !== duo.salleUn)
                  .map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
              </select>
            </label>
          )}
          {duo.un && duo.deux && groupesAPrendre.length > 0 && (
            <fieldset className="enseignants-modules-groupes">
              <legend>
                Groupes de {duo.type} de chacun (facultatif : sans choix, le
                partage de la maquette s’applique)
              </legend>
              {groupesAPrendre.map((g) => (
                <label key={g}>
                  {duo.type} {g}
                  <select
                    value={duo.groupes[g] ?? ""}
                    aria-label={`Enseignant du ${duo.type} ${g}`}
                    onChange={(e) =>
                      setDuo({
                        ...duo,
                        groupes: { ...duo.groupes, [g]: e.target.value },
                      })
                    }
                  >
                    <option value="">—</option>
                    {enseignantsDuo
                      .filter((x) => x.code === duo.un || x.code === duo.deux)
                      .map((x) => (
                        <option key={x.code} value={x.code}>
                          {x.nom}
                        </option>
                      ))}
                  </select>
                </label>
              ))}
            </fieldset>
          )}
          <Motif
            quoi="du duo"
            valeur={duo.motif}
            onChange={(motif) => setDuo({ ...duo, motif })}
          />
          <button
            type="submit"
            className="btn btn--sm"
            disabled={occupe || !duoPret}
          >
            Ajouter le duo
          </button>
        </form>
      )}
    </details>
  );
}
