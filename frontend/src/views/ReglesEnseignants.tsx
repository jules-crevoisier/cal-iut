/**
 * Référence → Réglages : trois règles posées à l'écran (19/11/2026) —
 * « disponible uniquement à ces dates » pour un enseignant, un module dont
 * aucun enseignement n'est dispensé cette année, et la journée compacte d'un
 * enseignant. Elles s'ajoutent aux contraintes déjà enregistrées.
 */
import { useState } from "react";
import { Plus } from "lucide-react";

import {
  ajouterRegleSimple,
  retirerRegleSimple,
  type FamilleDeRegleSimple,
  type ReglagesReponse,
} from "../api/client";

interface Choix {
  valeur: string;
  libelle: string;
}

const DATE = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short" });
const lisible = (iso: string) => DATE.format(new Date(`${iso}T12:00:00`));

function useEnvoi(onChange: (r: ReglagesReponse, message: string) => void) {
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const agir = async (action: () => Promise<ReglagesReponse>, message: string): Promise<boolean> => {
    setEnvoi(true);
    setErreur(null);
    try {
      onChange(await action(), message);
      return true;
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "L’enregistrement a échoué");
      return false;
    } finally {
      setEnvoi(false);
    }
  };
  return { envoi, erreur, agir };
}

function Retirer({ famille, cle, nom, envoi, agir }: {
  famille: FamilleDeRegleSimple;
  cle: string;
  nom: string;
  envoi: boolean;
  agir: (a: () => Promise<ReglagesReponse>, m: string) => Promise<boolean>;
}) {
  return (
    <button
      type="button"
      className="btn btn--sm"
      disabled={envoi}
      onClick={() => {
        if (window.confirm(`Retirer « ${nom} » ?`)) void agir(() => retirerRegleSimple(famille, cle), "Retiré.");
      }}
    >
      Retirer
    </button>
  );
}

export function ReglesEnseignants({
  enseignants,
  modules,
  donnees,
  onChange,
}: {
  enseignants: Choix[];
  modules: Choix[];
  donnees: ReglagesReponse;
  onChange: (r: ReglagesReponse, message: string) => void;
}) {
  const { envoi, erreur, agir } = useEnvoi(onChange);
  const nom = (code: string) => enseignants.find((c) => c.valeur === code)?.libelle ?? code;

  const [qui, setQui] = useState("");
  const [debut, setDebut] = useState("");
  const [fin, setFin] = useState("");
  const [dates, setDates] = useState<string[]>([]);
  const [prochaine, setProchaine] = useState("");
  const [motif, setMotif] = useState("");

  const [module, setModule] = useState("");
  const [motifModule, setMotifModule] = useState("");
  const [compact, setCompact] = useState("");
  const [motifCompact, setMotifCompact] = useState("");

  const exclusives = donnees.disponibilites_exclusives ?? [];
  const nonDispenses = donnees.modules_non_dispenses ?? [];
  const compacts = donnees.compacter_journee ?? [];

  return (
    <>
      <section className="panel reglages-famille" aria-labelledby="reglages-exclusives">
        <header>
          <h2 id="reglages-exclusives">Disponible uniquement à ces dates</h2>
          <p className="muted">
            Pour un enseignant qui n’intervient que certains jours d’une période : tous les autres jours ouvrés de la
            période deviennent indisponibles, pour la génération comme pour le placement à la main. S’ajoute aux
            indisponibilités déjà enregistrées.
          </p>
        </header>
        {exclusives.length === 0 ? (
          <p className="muted">Aucune règle.</p>
        ) : (
          <table className="ref">
            <thead>
              <tr>
                <th scope="col">Enseignant</th>
                <th scope="col">Période</th>
                <th scope="col">Dates disponibles</th>
                <th scope="col">Motif</th>
                <th scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {exclusives.map((e) => (
                <tr key={e.cle}>
                  <th scope="row">{nom(e.teacher_code)}</th>
                  <td>{lisible(e.debut)} → {lisible(e.fin)}</td>
                  <td>{e.dates.length} jour{e.dates.length > 1 ? "s" : ""} : {e.dates.map(lisible).join(", ")}</td>
                  <td>{e.motif}{e.demande_par && <span className="muted"> · {e.demande_par}</span>}</td>
                  <td className="reglages-actions">
                    <Retirer famille="disponibilites-exclusives" cle={e.cle} nom={nom(e.teacher_code)} envoi={envoi} agir={agir} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <form
          className="reglages-ajout"
          onSubmit={(ev) => {
            ev.preventDefault();
            void agir(
              () => ajouterRegleSimple("disponibilites-exclusives", { teacher_code: qui, debut, fin, dates, motif: motif.trim() }),
              "Enregistré. Le planning en service en tient compte dès maintenant.",
            ).then((ok) => {
              if (ok) {
                setDates([]);
                setMotif("");
              }
            });
          }}
        >
          <h3>Ajouter</h3>
          <div className="reglages-champs">
            <label>
              Enseignant
              <select value={qui} onChange={(e) => setQui(e.target.value)}>
                <option value="">Choisir…</option>
                {enseignants.map((c) => (
                  <option key={c.valeur} value={c.valeur}>{c.libelle}</option>
                ))}
              </select>
            </label>
            <label>
              Période : du
              <input type="date" value={debut} onChange={(e) => setDebut(e.target.value)} />
            </label>
            <label>
              au
              <input type="date" value={fin} onChange={(e) => setFin(e.target.value)} />
            </label>
            <label className="reglages-motif">
              Motif
              <input type="text" value={motif} maxLength={300} placeholder="Qui le demande, et pourquoi" onChange={(e) => setMotif(e.target.value)} />
            </label>
          </div>
          <div className="reglages-champs">
            <label>
              Date disponible
              <input type="date" value={prochaine} min={debut || undefined} max={fin || undefined} onChange={(e) => setProchaine(e.target.value)} />
            </label>
            <button
              type="button"
              className="btn btn--sm"
              disabled={!prochaine || dates.includes(prochaine)}
              onClick={() => {
                setDates([...dates, prochaine].sort());
                setProchaine("");
              }}
            >
              Ajouter cette date
            </button>
          </div>
          {dates.length > 0 && (
            <p>
              {dates.map((d) => (
                <button
                  key={d}
                  type="button"
                  className="btn btn--sm btn--ghost"
                  title="Retirer cette date"
                  onClick={() => setDates(dates.filter((x) => x !== d))}
                >
                  {lisible(d)} ×
                </button>
              ))}
            </p>
          )}
          {erreur && <p className="alerte" role="alert">{erreur}</p>}
          <div>
            <button
              type="submit"
              className="btn btn--primary"
              disabled={envoi || !qui || !debut || !fin || dates.length === 0 || motif.trim() === ""}
            >
              <Plus size={16} aria-hidden="true" /> Ajouter
            </button>
          </div>
        </form>
      </section>

      <section className="panel reglages-famille" aria-labelledby="reglages-non-dispenses">
        <header>
          <h2 id="reglages-non-dispenses">Modules non dispensés cette année</h2>
          <p className="muted">
            Aucune séance n’est créée pour ces modules à la prochaine génération. Les séances déjà en service ne
            sont pas touchées.
          </p>
        </header>
        {nonDispenses.length === 0 ? (
          <p className="muted">Aucun module.</p>
        ) : (
          <table className="ref">
            <tbody>
              {nonDispenses.map((e) => (
                <tr key={e.cle}>
                  <th scope="row">{modules.find((m) => m.valeur === e.course_code)?.libelle ?? e.course_code}</th>
                  <td>{e.motif}{e.demande_par && <span className="muted"> · {e.demande_par}</span>}</td>
                  <td className="reglages-actions">
                    <Retirer famille="modules-non-dispenses" cle={e.cle} nom={e.course_code} envoi={envoi} agir={agir} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <form
          className="reglages-ajout"
          onSubmit={(ev) => {
            ev.preventDefault();
            void agir(
              () => ajouterRegleSimple("modules-non-dispenses", { course_code: module, motif: motifModule.trim() }),
              "Enregistré. Pris en compte à la prochaine génération.",
            ).then((ok) => ok && setMotifModule(""));
          }}
        >
          <div className="reglages-champs">
            <label>
              Module
              <select value={module} onChange={(e) => setModule(e.target.value)}>
                <option value="">Choisir…</option>
                {modules.map((c) => (
                  <option key={c.valeur} value={c.valeur}>{c.libelle}</option>
                ))}
              </select>
            </label>
            <label className="reglages-motif">
              Motif
              <input type="text" value={motifModule} maxLength={300} onChange={(e) => setMotifModule(e.target.value)} />
            </label>
          </div>
          <button type="submit" className="btn btn--primary" disabled={envoi || !module || motifModule.trim() === ""}>
            <Plus size={16} aria-hidden="true" /> Ajouter
          </button>
        </form>
      </section>

      <section className="panel reglages-famille" aria-labelledby="reglages-compact">
        <header>
          <h2 id="reglages-compact">Journée compacte d’un enseignant</h2>
          <p className="muted">
            La génération regroupe ses séances d’une même journée, sans temps d’attente entre deux. La pause de
            12h30 à 14h n’est pas comptée comme un trou. Préférence souple : elle ne bloque jamais un placement.
          </p>
        </header>
        {compacts.length === 0 ? (
          <p className="muted">Aucun enseignant.</p>
        ) : (
          <table className="ref">
            <tbody>
              {compacts.map((e) => (
                <tr key={e.cle}>
                  <th scope="row">{nom(e.teacher_code)}</th>
                  <td>{e.motif}{e.demande_par && <span className="muted"> · {e.demande_par}</span>}</td>
                  <td className="reglages-actions">
                    <Retirer famille="compacter-journee" cle={e.cle} nom={nom(e.teacher_code)} envoi={envoi} agir={agir} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <form
          className="reglages-ajout"
          onSubmit={(ev) => {
            ev.preventDefault();
            void agir(
              () => ajouterRegleSimple("compacter-journee", { teacher_code: compact, motif: motifCompact.trim() }),
              "Enregistré. Pris en compte à la prochaine génération.",
            ).then((ok) => ok && setMotifCompact(""));
          }}
        >
          <div className="reglages-champs">
            <label>
              Enseignant
              <select value={compact} onChange={(e) => setCompact(e.target.value)}>
                <option value="">Choisir…</option>
                {enseignants.map((c) => (
                  <option key={c.valeur} value={c.valeur}>{c.libelle}</option>
                ))}
              </select>
            </label>
            <label className="reglages-motif">
              Motif
              <input type="text" value={motifCompact} maxLength={300} onChange={(e) => setMotifCompact(e.target.value)} />
            </label>
          </div>
          <button type="submit" className="btn btn--primary" disabled={envoi || !compact || motifCompact.trim() === ""}>
            <Plus size={16} aria-hidden="true" /> Ajouter
          </button>
        </form>
      </section>
    </>
  );
}
