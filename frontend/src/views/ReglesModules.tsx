/**
 * Nouveau semestre → « Règles de modules » (lot 6, 16/11/2026).
 *
 * Deux règles que les enseignants demandent à chaque semestre et qui
 * passaient par un fichier et un développeur :
 * - des séances longues (les TP de tel module durent 3 h, pas 1 h 30) ;
 * - une période imposée (tel module ne commence pas avant telle date, ou
 *   doit être terminé avant telle autre).
 */
import { useEffect, useState, type ReactNode } from "react";

import {
  ajouterPeriodeModule,
  ajouterSeancesLongues,
  lireReglesModules,
  retirerRegleModule,
  type ModuleRegle,
  type PeriodeModule,
  type ReglesModulesReponse,
} from "../api/client";

const JOUR = new Intl.DateTimeFormat("fr-FR", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

function jour(iso: string): string {
  return JOUR.format(new Date(`${iso}T12:00:00`));
}

/** « du 1 mars 2027 au 2 avr. 2027 », « à partir du… », « jusqu’au… ». */
export function libellePeriode(p: PeriodeModule): string {
  if (p.dates.length > 0)
    return `uniquement ${p.dates.length > 1 ? "les" : "le"} ${p.dates.map(jour).join(", ")}`;
  if (p.debut && p.fin) return `du ${jour(p.debut)} au ${jour(p.fin)}`;
  if (p.debut) return `à partir du ${jour(p.debut)}`;
  if (p.fin) return `jusqu’au ${jour(p.fin)}`;
  return "";
}

function cible(p: PeriodeModule): string {
  const quoi = p.type ? `les ${p.type}` : "toutes les séances";
  return p.rangs.length > 0 ? `${quoi} n° ${p.rangs.join(", ")}` : quoi;
}

export function ChoixModule({
  modules,
  valeur,
  onChange,
}: {
  modules: ModuleRegle[];
  valeur: string;
  onChange: (code: string) => void;
}) {
  return (
    <label>
      Module
      <select value={valeur} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choisir…</option>
        {modules.map((m) => (
          <option key={m.code} value={m.code}>
            {m.semestre} · {m.code} {m.nom}
          </option>
        ))}
      </select>
    </label>
  );
}

export function Ligne({
  titre,
  detail,
  motif,
  livree,
  retirer,
}: {
  titre: ReactNode;
  detail: string;
  motif: string;
  livree: boolean;
  retirer: ReactNode;
}) {
  return (
    <li className="dates-sae-ligne">
      <div className="dates-sae-quoi">
        <div className="dates-sae-titre">
          {titre}
          <span className="muted"> · {detail}</span>
        </div>
        {motif && <div className="muted regles-modules-motif">{motif}</div>}
      </div>
      {livree ? (
        <span className="pill" title="Règle livrée avec l’application">
          D’origine
        </span>
      ) : (
        retirer
      )}
    </li>
  );
}

export function ReglesModules({
  groupe,
  onModifie,
}: {
  groupe: string;
  onModifie: () => void;
}) {
  const [donnees, setDonnees] = useState<ReglesModulesReponse | null>(null);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [longue, setLongue] = useState({ code: "", type: "", creneaux: 2, motif: "" });
  const [periode, setPeriode] = useState({ code: "", type: "", debut: "", fin: "", motif: "" });

  useEffect(() => {
    let perime = false;
    setDonnees(null);
    setErreur(null);
    lireReglesModules(groupe)
      .then((r) => {
        if (
          !perime &&
          Array.isArray(r?.modules) &&
          Array.isArray(r?.seances_longues) &&
          Array.isArray(r?.periodes)
        )
          setDonnees(r);
      })
      .catch(() => undefined);
    return () => {
      perime = true;
    };
  }, [groupe]);

  if (!donnees || donnees.modules.length === 0) return null;

  const verrouille = donnees.verrouille !== null;
  const n = donnees.seances_longues.length + donnees.periodes.length;
  const typesDe = (code: string) =>
    donnees.modules.find((m) => m.code === code)?.types ?? {};

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
    nom: "seances-longues" | "periodes",
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

  // Un bloc de 3 h demande au moins deux séances de ce type.
  const typesLongs = Object.entries(typesDe(longue.code)).filter(
    ([type, nb]) => ["CM", "TD", "TP"].includes(type) && nb >= 2,
  );
  const typesPeriode = Object.keys(typesDe(periode.code)).filter((t) =>
    ["CM", "TD", "TP"].includes(t),
  );
  const longuePrete = longue.code && longue.type && longue.motif.trim();
  const periodePrete =
    periode.code && (periode.debut || periode.fin) && periode.motif.trim();

  return (
    <details className="dates-sae regles-modules">
      <summary>
        <h3>Règles de modules</h3>
        <span className="muted">
          {n === 0 ? "Aucune" : `${n} règle${n > 1 ? "s" : ""}`}
        </span>
      </summary>
      <p className="muted">
        Des séances longues ou une période imposée pour un module. Le calcul
        les respecte strictement. Cela vaut pour la prochaine génération.
      </p>
      {donnees.verrouille && <p className="muted">{donnees.verrouille}</p>}
      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}

      <h4>Séances longues</h4>
      {donnees.seances_longues.length > 0 && (
        <ul>
          {donnees.seances_longues.map((r) => (
            <Ligne
              key={`${r.code}-${r.type}`}
              titre={
                <>
                  <strong>{r.code}</strong> <span>{r.nom}</span>
                </>
              }
              detail={`les ${r.type} par blocs de ${r.duree}`}
              motif={r.motif}
              livree={r.origine === "livree"}
              retirer={boutonRetirer("seances-longues", r.id, `${r.code} ${r.type}`)}
            />
          ))}
        </ul>
      )}
      {!verrouille && (
        <form
          className="seances-annulees-ajout"
          onSubmit={(e) => {
            e.preventDefault();
            if (!longuePrete) return;
            void agir(
              () =>
                ajouterSeancesLongues(groupe, {
                  ...longue,
                  motif: longue.motif.trim(),
                }),
              () => setLongue({ code: "", type: "", creneaux: 2, motif: "" }),
            );
          }}
        >
          <ChoixModule
            modules={donnees.modules}
            valeur={longue.code}
            onChange={(code) => setLongue({ ...longue, code, type: "" })}
          />
          <label>
            Séances
            <select
              value={longue.type}
              disabled={typesLongs.length === 0}
              aria-label="Type des séances longues"
              onChange={(e) => setLongue({ ...longue, type: e.target.value })}
            >
              <option value="">Choisir…</option>
              {typesLongs.map(([type, nb]) => (
                <option key={type} value={type}>
                  {type} ({nb})
                </option>
              ))}
            </select>
          </label>
          <label>
            Durée
            <select
              value={longue.creneaux}
              onChange={(e) =>
                setLongue({ ...longue, creneaux: Number(e.target.value) })
              }
            >
              <option value={2}>3 h</option>
              <option value={3}>4 h 30</option>
            </select>
          </label>
          <label className="seances-annulees-motif">
            Motif
            <input
              type="text"
              value={longue.motif}
              maxLength={300}
              aria-label="Motif des séances longues"
              placeholder="Qui le demande, et pourquoi"
              onChange={(e) => setLongue({ ...longue, motif: e.target.value })}
            />
          </label>
          <button
            type="submit"
            className="btn btn--sm"
            disabled={occupe || !longuePrete}
          >
            Ajouter les séances longues
          </button>
        </form>
      )}

      <h4>Période imposée</h4>
      {donnees.periodes.length > 0 && (
        <ul>
          {donnees.periodes.map((p, i) => (
            <Ligne
              key={p.id ?? `livree-${i}`}
              titre={
                <>
                  <strong>{p.code}</strong> <span>{p.nom}</span>
                </>
              }
              detail={`${cible(p)}, ${libellePeriode(p)}`}
              motif={p.motif}
              livree={p.origine === "livree"}
              retirer={boutonRetirer("periodes", p.id, `${p.code} ${libellePeriode(p)}`)}
            />
          ))}
        </ul>
      )}
      {!verrouille && (
        <form
          className="seances-annulees-ajout"
          onSubmit={(e) => {
            e.preventDefault();
            if (!periodePrete) return;
            void agir(
              () =>
                ajouterPeriodeModule(groupe, {
                  code: periode.code,
                  type: periode.type || null,
                  debut: periode.debut || null,
                  fin: periode.fin || null,
                  motif: periode.motif.trim(),
                }),
              () =>
                setPeriode({ code: "", type: "", debut: "", fin: "", motif: "" }),
            );
          }}
        >
          <ChoixModule
            modules={donnees.modules}
            valeur={periode.code}
            onChange={(code) => setPeriode({ ...periode, code, type: "" })}
          />
          <label>
            Séances
            <select
              value={periode.type}
              aria-label="Séances concernées par la période"
              onChange={(e) => setPeriode({ ...periode, type: e.target.value })}
            >
              <option value="">Toutes</option>
              {typesPeriode.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </label>
          <label>
            Pas avant le
            <input
              type="date"
              value={periode.debut}
              onChange={(e) => setPeriode({ ...periode, debut: e.target.value })}
            />
          </label>
          <label>
            Pas après le
            <input
              type="date"
              value={periode.fin}
              min={periode.debut || undefined}
              onChange={(e) => setPeriode({ ...periode, fin: e.target.value })}
            />
          </label>
          <label className="seances-annulees-motif">
            Motif
            <input
              type="text"
              value={periode.motif}
              maxLength={300}
              aria-label="Motif de la période"
              placeholder="Qui le demande, et pourquoi"
              onChange={(e) => setPeriode({ ...periode, motif: e.target.value })}
            />
          </label>
          <button
            type="submit"
            className="btn btn--sm"
            disabled={occupe || !periodePrete}
          >
            Ajouter la période
          </button>
        </form>
      )}
    </details>
  );
}
