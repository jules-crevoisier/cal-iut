/**
 * Référence → Réglages (lot 6, 16/11/2026) — les réglages du quotidien que
 * l'on saisissait jusque-là dans un fichier du dépôt : une salle prise par un
 * tiers, un enseignant absent à une date et des créneaux précis.
 *
 * Ce qui est saisi s'applique tout de suite au planning en service et sera
 * lu par la prochaine génération. Rien n'est déplacé tout seul.
 */
import { useEffect, useMemo, useState } from "react";
import { Plus } from "lucide-react";

import {
  ajouterReglage,
  lireReglages,
  reglerSemaineType,
  retablirSemaineType,
  retirerReglage,
  type FamilleDeReglage,
  type IndisponibiliteDatee,
  type ReglageDate,
  type ReglagesReponse,
  type SalleReservee,
  type EvenementFixe,
  type SemaineType,
} from "../api/client";
import { useDroits } from "../contexts/Droits";
import type { AppPayload } from "../types/app";
import "./ReglagesReference.css";
import { PresencesAlternants } from "./PresencesAlternants";
import { EffectifsReglables, SallesDesModules, SallesReglables } from "./SallesEtEffectifs";

const JOUR = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short", year: "numeric" });

function dateLisible(iso: string): string {
  const d = new Date(`${iso}T12:00:00`);
  return Number.isNaN(d.getTime()) ? iso : JOUR.format(d);
}

function aujourdhui(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** « 9h30-11h, 11h-12h30 » → « 9h30-12h30 » quand les créneaux se suivent. */
export function creneauxLisibles(slots: number[], libelles: string[]): string {
  if (slots.length === libelles.length && libelles.length > 0) return "Toute la journée";
  const morceaux: string[] = [];
  const tries = [...slots].sort((a, b) => a - b);
  let debut = 0;
  for (let i = 1; i <= tries.length; i += 1) {
    const [finPrecedente] = (libelles[tries[i - 1]] ?? "").split("-").slice(-1);
    const [debutSuivant] = (libelles[tries[i]] ?? "").split("-");
    if (i < tries.length && tries[i] === tries[i - 1] + 1 && finPrecedente === debutSuivant) continue;
    const premier = (libelles[tries[debut]] ?? "").split("-")[0];
    morceaux.push(`${premier}-${finPrecedente}`);
    debut = i;
  }
  return morceaux.join(", ");
}

interface Choix {
  valeur: string;
  libelle: string;
}

function Famille<T extends ReglageDate>({
  titre,
  aide,
  famille,
  champ,
  libelleChamp,
  choix,
  entrees,
  libelleDe,
  creneaux,
  onChange,
}: {
  titre: string;
  aide: string;
  famille: FamilleDeReglage;
  champ: "salle" | "teacher_code" | "parcours";
  libelleChamp: string;
  choix: Choix[];
  entrees: T[];
  libelleDe: (e: T) => string;
  creneaux: string[];
  onChange: (r: ReglagesReponse, message: string) => void;
}) {
  const [qui, setQui] = useState("");
  const [date, setDate] = useState("");
  const [slots, setSlots] = useState<number[]>([]);
  const [motif, setMotif] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [passees, setPassees] = useState(false);

  const jour = aujourdhui();
  const visibles = entrees.filter((e) => passees || e.date >= jour);
  const nbPassees = entrees.length - entrees.filter((e) => e.date >= jour).length;
  const idTitre = `reglages-${famille}`;
  const complet = qui !== "" && date !== "" && slots.length > 0 && motif.trim() !== "";

  const basculer = (s: number) =>
    setSlots((avant) => (avant.includes(s) ? avant.filter((x) => x !== s) : [...avant, s]));

  const ajouter = async () => {
    setEnvoi(true);
    setErreur(null);
    try {
      const r = await ajouterReglage(famille, { [champ]: qui, date, slots, motif: motif.trim() });
      setDate("");
      setSlots([]);
      setMotif("");
      onChange(r, "Enregistré. Le planning en service en tient compte dès maintenant.");
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "L’enregistrement a échoué");
    } finally {
      setEnvoi(false);
    }
  };

  const retirer = async (e: T) => {
    if (!window.confirm(`Retirer « ${libelleDe(e)}, ${dateLisible(e.date)} » ?`)) return;
    setEnvoi(true);
    setErreur(null);
    try {
      onChange(await retirerReglage(famille, e), "Retiré.");
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Le retrait a échoué");
    } finally {
      setEnvoi(false);
    }
  };

  return (
    <section className="panel reglages-famille" aria-labelledby={idTitre}>
      <header>
        <h2 id={idTitre}>{titre}</h2>
        <p className="muted">{aide}</p>
      </header>

      {visibles.length === 0 ? (
        <p className="muted">Aucune entrée à venir.</p>
      ) : (
        <table className="ref">
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">{libelleChamp}</th>
              <th scope="col">Horaire</th>
              <th scope="col">Motif</th>
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visibles.map((e) => (
              <tr key={`${e.origine}-${e.cle}`} className={e.date < jour ? "reglages-passee" : undefined}>
                <th scope="row">{dateLisible(e.date)}</th>
                <td>{libelleDe(e)}</td>
                <td>{creneauxLisibles(e.slots, creneaux)}</td>
                <td>
                  {e.motif || "—"}
                  {e.demande_par && <span className="muted"> · {e.demande_par}</span>}
                </td>
                <td className="reglages-actions">
                  <button type="button" className="btn btn--sm" disabled={envoi} onClick={() => void retirer(e)}>
                    Retirer
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {nbPassees > 0 && (
        <label className="reglages-passees">
          <input type="checkbox" checked={passees} onChange={(e) => setPassees(e.target.checked)} /> Afficher aussi les{" "}
          {nbPassees} déjà passée{nbPassees > 1 ? "s" : ""}
        </label>
      )}

      <form
        className="reglages-ajout"
        onSubmit={(e) => {
          e.preventDefault();
          if (complet) void ajouter();
        }}
      >
        <h3>Ajouter</h3>
        <div className="reglages-champs">
          <label>
            {libelleChamp}
            <select value={qui} onChange={(e) => setQui(e.target.value)}>
              <option value="">Choisir…</option>
              {choix.map((c) => (
                <option key={c.valeur} value={c.valeur}>
                  {c.libelle}
                </option>
              ))}
            </select>
          </label>
          <label>
            Date
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </label>
          <label className="reglages-motif">
            Motif
            <input
              type="text"
              value={motif}
              maxLength={300}
              placeholder="Qui le demande, et pourquoi"
              onChange={(e) => setMotif(e.target.value)}
            />
          </label>
        </div>
        <fieldset className="reglages-creneaux">
          <legend>Créneaux</legend>
          {creneaux.map((libelle, i) => (
            <label key={libelle}>
              <input type="checkbox" checked={slots.includes(i)} onChange={() => basculer(i)} /> {libelle}
            </label>
          ))}
          <button
            type="button"
            className="btn btn--sm btn--ghost"
            onClick={() => setSlots(slots.length === creneaux.length ? [] : creneaux.map((_, i) => i))}
          >
            {slots.length === creneaux.length ? "Aucun" : "Toute la journée"}
          </button>
        </fieldset>
        {erreur && (
          <p className="alerte" role="alert">
            {erreur}
          </p>
        )}
        <div>
          <button type="submit" className="btn btn--primary" disabled={!complet || envoi}>
            <Plus size={16} aria-hidden="true" />
            {envoi ? "Enregistrement…" : "Ajouter"}
          </button>
        </div>
      </form>
    </section>
  );
}

const cle = (c: [number, number] | number[]) => `${c[0]}-${c[1]}`;

/** Les cases indisponibles en vigueur : l'origine, plus ce que l'écran a
 * bloqué, moins ce qu'il a libéré. */
export function semaineEnVigueur(s: SemaineType | undefined): Set<string> {
  const cases = new Set((s?.origine ?? []).map(cle));
  for (const c of s?.liberes ?? []) cases.delete(cle(c));
  for (const c of s?.bloques ?? []) cases.add(cle(c));
  return cases;
}

function SemainesTypes({
  enseignants,
  donnees,
  onChange,
}: {
  enseignants: Choix[];
  donnees: ReglagesReponse;
  onChange: (r: ReglagesReponse, message: string) => void;
}) {
  const jours = donnees.jours ?? [];
  const semaines = donnees.semaines_types ?? [];
  const [qui, setQui] = useState("");
  const [cases, setCases] = useState<Set<string>>(new Set());
  const [motif, setMotif] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const semaine = semaines.find((s) => s.teacher_code === qui);
  const origine = useMemo(() => new Set((semaine?.origine ?? []).map(cle)), [semaine]);
  const fixes = useMemo(() => new Set((semaine?.fixes ?? []).map(cle)), [semaine]);
  const enVigueur = useMemo(() => semaineEnVigueur(semaine), [semaine]);
  const modifiee = (semaine?.bloques.length ?? 0) + (semaine?.liberes.length ?? 0) > 0;

  useEffect(() => {
    setCases(new Set(enVigueur));
    setMotif(semaine?.motif ?? "");
    setErreur(null);
  }, [qui, enVigueur, semaine?.motif]);

  if (jours.length === 0) return null;

  const change = cases.size !== enVigueur.size || [...cases].some((c) => !enVigueur.has(c));
  const ecart = [...cases].some((c) => !origine.has(c)) || [...origine].some((c) => !cases.has(c));
  const basculer = (c: string) =>
    setCases((avant) => {
      const apres = new Set(avant);
      if (apres.has(c)) apres.delete(c);
      else apres.add(c);
      return apres;
    });

  const agir = async (action: () => Promise<ReglagesReponse>, message: string) => {
    setEnvoi(true);
    setErreur(null);
    try {
      onChange(await action(), message);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "L’enregistrement a échoué");
    } finally {
      setEnvoi(false);
    }
  };

  const changes = semaines.filter((s) => s.bloques.length + s.liberes.length > 0);
  const nom = (code: string) => enseignants.find((c) => c.valeur === code)?.libelle ?? code;

  return (
    <section className="panel reglages-famille" aria-labelledby="reglages-semaines-types">
      <header>
        <h2 id="reglages-semaines-types">Semaine type des enseignants</h2>
        <p className="muted">
          Les créneaux où un enseignant n’est jamais disponible, chaque semaine. Cochez une case pour la rendre
          indisponible, décochez-la pour la rendre disponible.
        </p>
      </header>
      {changes.length > 0 && (
        <p className="muted">
          Semaine modifiée ici pour : {changes.map((s) => nom(s.teacher_code)).join(", ")}.
        </p>
      )}
      <form
        className="reglages-ajout"
        onSubmit={(e) => {
          e.preventDefault();
          if (!qui || !change) return;
          const voulues = [...cases].map((c) => c.split("-").map(Number) as [number, number]);
          void agir(
            () => reglerSemaineType(qui, voulues, motif.trim()),
            "Enregistré. Le planning en service en tient compte dès maintenant.",
          );
        }}
      >
        <label>
          Enseignant
          <select value={qui} aria-label="Enseignant de la semaine type" onChange={(e) => setQui(e.target.value)}>
            <option value="">Choisir…</option>
            {enseignants.map((c) => (
              <option key={c.valeur} value={c.valeur}>
                {c.libelle}
              </option>
            ))}
          </select>
        </label>
        {qui && (
          <>
            <table className="ref reglages-semaine">
              <thead>
                <tr>
                  <td />
                  {jours.map((j) => (
                    <th key={j} scope="col">
                      {j}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {donnees.creneaux.map((libelle, creneau) => (
                  <tr key={libelle}>
                    <th scope="row">{libelle}</th>
                    {jours.map((j, jour) => {
                      const c = `${jour}-${creneau}`;
                      const pris = cases.has(c);
                      return (
                        <td
                          key={j}
                          className={
                            (pris ? "reglages-case-prise" : "") +
                            (pris !== origine.has(c) ? " reglages-case-changee" : "")
                          }
                        >
                          <input
                            type="checkbox"
                            checked={pris}
                            disabled={fixes.has(c)}
                            aria-label={`${j} ${libelle} indisponible`}
                            title={
                              fixes.has(c)
                                ? "Hors des créneaux que cet enseignant a déclarés possibles"
                                : pris !== origine.has(c)
                                  ? "Modifié ici"
                                  : undefined
                            }
                            onChange={() => basculer(c)}
                          />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted">
              {cases.size === 0
                ? "Disponible toute la semaine."
                : `${cases.size} créneau${cases.size > 1 ? "x" : ""} indisponible${cases.size > 1 ? "s" : ""} par semaine.`}
              {fixes.size > 0 &&
                " Cet enseignant a déclaré les seuls créneaux où il peut venir : les autres restent grisés."}
              {ecart && " Les cases entourées diffèrent de sa semaine d’origine."}
            </p>
            <label>
              Motif
              <input
                type="text"
                value={motif}
                maxLength={300}
                aria-label="Motif de la semaine type"
                placeholder="Qui le demande, et pourquoi"
                onChange={(e) => setMotif(e.target.value)}
              />
            </label>
          </>
        )}
        {erreur && (
          <p className="alerte" role="alert">
            {erreur}
          </p>
        )}
        {qui && (
          <div className="reglages-semaine-actions">
            <button
              type="submit"
              className="btn btn--primary"
              disabled={envoi || !change || (ecart && !motif.trim())}
            >
              {envoi ? "Enregistrement…" : "Enregistrer la semaine"}
            </button>
            {modifiee && (
              <button
                type="button"
                className="btn"
                disabled={envoi}
                onClick={() => void agir(() => retablirSemaineType(qui), "Semaine d’origine rétablie.")}
              >
                Revenir à la semaine d’origine
              </button>
            )}
          </div>
        )}
      </form>
    </section>
  );
}

export function ReglagesReference({ payload }: { payload: AppPayload }) {
  const { apresEnregistrement } = useDroits();
  const [donnees, setDonnees] = useState<ReglagesReponse | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let perime = false;
    lireReglages()
      .then((r) => {
        if (!perime) setDonnees(r);
      })
      .catch((e) => {
        if (!perime) setErreur(e instanceof Error ? e.message : "Erreur de chargement");
      });
    return () => {
      perime = true;
    };
  }, []);

  const salles = useMemo<Choix[]>(
    () =>
      [...payload.rooms]
        .map((r) => ({ valeur: r.id, libelle: r.label }))
        .sort((a, b) => a.libelle.localeCompare(b.libelle, "fr", { numeric: true })),
    [payload.rooms],
  );
  const enseignants = useMemo<Choix[]>(
    () =>
      Object.entries(payload.teacherLabels)
        .map(([code, nom]) => ({ valeur: code, libelle: nom && nom !== code ? `${nom} (${code})` : code }))
        .sort((a, b) => a.libelle.localeCompare(b.libelle, "fr")),
    [payload.teacherLabels],
  );

  const modules = useMemo<Choix[]>(() => {
    const vus = new Map<string, string>();
    for (const c of payload.courses ?? []) if (!vus.has(c.code)) vus.set(c.code, c.name);
    return [...vus.entries()]
      .map(([code, nom]) => ({ valeur: code, libelle: nom && nom !== code ? `${code} · ${nom}` : code }))
      .sort((a, b) => a.valeur.localeCompare(b.valeur, "fr", { numeric: true }));
  }, [payload.courses]);

  const promotions = useMemo<Choix[]>(
    () => [
      { valeur: "*", libelle: "Toutes les promotions" },
      ...(donnees?.parcours ?? []).map((p) => ({ valeur: p, libelle: p })),
    ],
    [donnees?.parcours],
  );

  if (erreur && !donnees) {
    return (
      <p className="alerte" role="alert">
        {erreur}
      </p>
    );
  }
  if (!donnees) return <p className="muted">Chargement…</p>;

  const apres = (r: ReglagesReponse, texte: string) => {
    setDonnees(r);
    setMessage(texte);
    apresEnregistrement();
  };
  const nomEnseignant = (code: string) => enseignants.find((c) => c.valeur === code)?.libelle ?? code;

  return (
    <div className="reglages">
      <p className="reglages-intro">
        Ce qui est saisi ici s’applique tout de suite au planning en service et sera repris par la prochaine
        génération. Aucune séance n’est déplacée toute seule : une séance déjà placée sur un créneau devenu
        indisponible reste où elle est.
      </p>
      {message && (
        <p className="reglages-message" role="status">
          {message}
        </p>
      )}
      <Famille<SalleReservee>
        titre="Salles réservées"
        aide="Une salle prise par la Direction, un jury, un autre département : elle n’est plus proposée ni attribuée sur ces créneaux."
        famille="salles-reservees"
        champ="salle"
        libelleChamp="Salle"
        choix={salles}
        entrees={donnees.salles_reservees}
        libelleDe={(e) => e.salle_libelle}
        creneaux={donnees.creneaux}
        onChange={apres}
      />
      <Famille<IndisponibiliteDatee>
        titre="Indisponibilités datées des enseignants"
        aide="Un enseignant absent à une date et des horaires précis. Pour une indisponibilité qui revient chaque semaine, utilisez la semaine type ci-dessous."
        famille="indisponibilites"
        champ="teacher_code"
        libelleChamp="Enseignant"
        choix={enseignants}
        entrees={donnees.indisponibilites}
        libelleDe={(e) => nomEnseignant(e.teacher_code)}
        creneaux={donnees.creneaux}
        onChange={apres}
      />
      <SemainesTypes enseignants={enseignants} donnees={donnees} onChange={apres} />
      {donnees.evenements_fixes && (
        <Famille<EvenementFixe>
          titre="Événements à date fixe"
          aide="Une rentrée, un forum, une journée banalisée : la promotion n’a pas cours sur ces créneaux, et le calcul n’y place rien."
          famille="evenements-fixes"
          champ="parcours"
          libelleChamp="Promotion"
          choix={promotions}
          entrees={donnees.evenements_fixes}
          libelleDe={(e) => (e.parcours === "*" ? "Toutes les promotions" : e.parcours || "Information seule")}
          creneaux={donnees.creneaux}
          onChange={apres}
        />
      )}
      <PresencesAlternants donnees={donnees} onChange={apres} />
      <SallesReglables donnees={donnees} onChange={apres} />
      <SallesDesModules modules={modules} donnees={donnees} onChange={apres} />
      <EffectifsReglables donnees={donnees} onChange={apres} />
    </div>
  );
}
