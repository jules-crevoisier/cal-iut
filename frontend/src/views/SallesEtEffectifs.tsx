/**
 * Référence → Réglages : capacité, type et placement automatique des
 * salles, et effectifs des groupes (17/11/2026). Ces valeurs décident de
 * la salle attribuée à chaque séance et du contrôle des capacités.
 */
import { useEffect, useState } from "react";

import {
  ajouterRegleDeSalle,
  retirerRegleDeSalle,
  reglerEffectif,
  reglerSalle,
  retablirEffectif,
  retablirSalle,
  type EffectifDeGroupe,
  type ReglagesReponse,
  type SalleReglable,
} from "../api/client";
import { libelleTypeGroupe, libelleTypeSalle } from "../utils/annuaires";

type ApresChangement = (r: ReglagesReponse, message: string) => void;

function useEnvoi(onChange: ApresChangement) {
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
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
  return { envoi, erreur, agir };
}

function LigneSalle({ salle, types, onChange }: { salle: SalleReglable; types: string[]; onChange: ApresChangement }) {
  const [capacite, setCapacite] = useState(String(salle.capacite));
  const [type, setType] = useState(salle.type);
  const [auto, setAuto] = useState(salle.placement_auto);
  const { envoi, erreur, agir } = useEnvoi(onChange);

  useEffect(() => {
    setCapacite(String(salle.capacite));
    setType(salle.type);
    setAuto(salle.placement_auto);
  }, [salle.capacite, salle.type, salle.placement_auto]);

  const places = Number(capacite);
  const valide = Number.isInteger(places) && places >= 1 && places <= 1000;
  const change = places !== salle.capacite || type !== salle.type || auto !== salle.placement_auto;
  const choix = salle.type_fixe ? [salle.type] : types.includes(salle.type) ? types : [salle.type, ...types];

  return (
    <tr>
      <th scope="row">
        {salle.label}
        {salle.ajoutee && <span className="muted"> (ajoutée)</span>}
      </th>
      <td>
        <input
          type="number"
          min={1}
          max={1000}
          value={capacite}
          aria-label={`Capacité de ${salle.label}`}
          onChange={(e) => setCapacite(e.target.value)}
        />
      </td>
      <td>
        <select
          value={type}
          aria-label={`Type de ${salle.label}`}
          disabled={salle.type_fixe}
          onChange={(e) => setType(e.target.value)}
        >
          {choix.map((t) => (
            <option key={t} value={t}>
              {libelleTypeSalle(t)}
            </option>
          ))}
        </select>
      </td>
      <td>
        <input
          type="checkbox"
          checked={auto}
          aria-label={`Placement automatique en ${salle.label}`}
          onChange={(e) => setAuto(e.target.checked)}
        />
      </td>
      <td className="reglages-table-actions">
        <button
          type="button"
          className="btn btn--primary"
          disabled={envoi || !change || !valide}
          onClick={() =>
            agir(
              () => reglerSalle(salle.id, { capacite: places, type, placement_auto: auto }),
              `${salle.label} enregistrée.`,
            )
          }
        >
          Enregistrer
        </button>
        {salle.modifiee && salle.origine && (
          <button
            type="button"
            disabled={envoi}
            title={`D’origine : ${salle.origine.capacite} places, ${libelleTypeSalle(salle.origine.type)}`}
            onClick={() => agir(() => retablirSalle(salle.id), `${salle.label} : valeurs d’origine reprises.`)}
          >
            Revenir à l’origine
          </button>
        )}
        {erreur && (
          <span className="alerte" role="alert">
            {erreur}
          </span>
        )}
      </td>
    </tr>
  );
}

export function SallesReglables({ donnees, onChange }: { donnees: ReglagesReponse; onChange: ApresChangement }) {
  const salles = donnees.salles ?? [];
  if (salles.length === 0) return null;
  return (
    <section className="panel reglages-famille" aria-labelledby="reglages-salles">
      <header>
        <h2 id="reglages-salles">Salles : capacité, type et placement automatique</h2>
        <p className="muted">
          Le type décide des cours que la salle reçoit en priorité, la capacité des groupes qu’elle peut accueillir.
          Une salle sans placement automatique n’est jamais attribuée toute seule, mais reste choisissable à la
          main. Pour ajouter une salle, utilisez « Nouvelle salle » dans la liste des salles.
        </p>
      </header>
      <div className="reglages-table-defilante">
        <table className="reglages-table">
          <thead>
            <tr>
              <th scope="col">Salle</th>
              <th scope="col">Places</th>
              <th scope="col">Type</th>
              <th scope="col">Placement automatique</th>
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {salles.map((s) => (
              <LigneSalle key={s.id} salle={s} types={donnees.types_de_salle ?? []} onChange={onChange} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function LigneEffectif({ groupe, onChange }: { groupe: EffectifDeGroupe; onChange: ApresChangement }) {
  const [valeur, setValeur] = useState(String(groupe.effectif));
  const { envoi, erreur, agir } = useEnvoi(onChange);

  useEffect(() => setValeur(String(groupe.effectif)), [groupe.effectif]);

  const effectif = Number(valeur);
  const valide = Number.isInteger(effectif) && effectif >= 1 && effectif <= 500;
  const nom = `${groupe.parcours} ${groupe.label}`;

  return (
    <tr>
      <th scope="row">{groupe.label}</th>
      <td>{libelleTypeGroupe(groupe.kind)}</td>
      <td>
        <input
          type="number"
          min={1}
          max={500}
          value={valeur}
          aria-label={`Effectif de ${nom}`}
          onChange={(e) => setValeur(e.target.value)}
        />
      </td>
      <td className="reglages-table-actions">
        <button
          type="button"
          className="btn btn--primary"
          disabled={envoi || !valide || effectif === groupe.effectif}
          onClick={() => agir(() => reglerEffectif(groupe.id, effectif), `Effectif de ${nom} enregistré.`)}
        >
          Enregistrer
        </button>
        {groupe.modifie && (
          <button
            type="button"
            disabled={envoi}
            title={`D’origine : ${groupe.origine} étudiants`}
            onClick={() => agir(() => retablirEffectif(groupe.id), `Effectif de ${nom} : valeur d’origine reprise.`)}
          >
            Revenir à l’origine
          </button>
        )}
        {erreur && (
          <span className="alerte" role="alert">
            {erreur}
          </span>
        )}
      </td>
    </tr>
  );
}

/** Les groupes rangés par parcours, dans l'ordre reçu. */
export function parParcours(groupes: EffectifDeGroupe[]): [string, EffectifDeGroupe[]][] {
  const ordre = { promo: 0, td: 1, tp: 2 } as Record<string, number>;
  const rangs = new Map<string, EffectifDeGroupe[]>();
  for (const g of groupes) rangs.set(g.parcours, [...(rangs.get(g.parcours) ?? []), g]);
  return [...rangs.entries()].map(([p, gs]) => [
    p,
    [...gs].sort((a, b) => (ordre[a.kind] ?? 9) - (ordre[b.kind] ?? 9)),
  ]);
}

export function EffectifsReglables({ donnees, onChange }: { donnees: ReglagesReponse; onChange: ApresChangement }) {
  const groupes = donnees.effectifs ?? [];
  if (groupes.length === 0) return null;
  return (
    <section className="panel reglages-famille" aria-labelledby="reglages-effectifs">
      <header>
        <h2 id="reglages-effectifs">Effectifs des groupes</h2>
        <p className="muted">
          Le nombre d’étudiants de chaque groupe. Il sert à choisir une salle assez grande et à signaler les salles
          trop petites. À mettre à jour à chaque rentrée.
        </p>
      </header>
      {parParcours(groupes).map(([parcours, liste]) => (
        <details key={parcours} className="reglages-parcours">
          <summary>
            {parcours}
            {liste.some((g) => g.modifie) && <span className="muted"> (modifié)</span>}
          </summary>
          <table className="reglages-table">
            <thead>
              <tr>
                <th scope="col">Groupe</th>
                <th scope="col">Type</th>
                <th scope="col">Étudiants</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {liste.map((g) => (
                <LigneEffectif key={g.id} groupe={g} onChange={onChange} />
              ))}
            </tbody>
          </table>
        </details>
      ))}
    </section>
  );
}

const TYPES_DE_SEANCE = ["CM", "TD", "TP"];

export function SallesDesModules({
  modules,
  donnees,
  onChange,
}: {
  modules: { valeur: string; libelle: string }[];
  donnees: ReglagesReponse;
  onChange: ApresChangement;
}) {
  const types = donnees.types_de_salle ?? [];
  const regles = donnees.regles_salles ?? [];
  const [module, setModule] = useState("");
  const [seances, setSeances] = useState<string[]>(["TD", "TP"]);
  const [prefere, setPrefere] = useState("");
  const [repli, setRepli] = useState("");
  const { envoi, erreur, agir } = useEnvoi(onChange);

  if (types.length === 0) return null;
  const nom = (code: string) => modules.find((m) => m.valeur === code)?.libelle ?? code;
  const pret = module !== "" && prefere !== "" && seances.length > 0;

  return (
    <section className="panel reglages-famille" aria-labelledby="reglages-salles-modules">
      <header>
        <h2 id="reglages-salles-modules">Type de salle d’un module</h2>
        <p className="muted">
          Pour envoyer les séances d’un module dans un type de salle précis. La règle saisie ici passe devant les
          règles livrées avec l’application ; les évaluations gardent leur salle d’examen. Elle compte pour les
          prochaines attributions de salle, pas pour les séances déjà placées.
        </p>
      </header>
      {regles.length === 0 ? (
        <p className="muted">Aucune règle saisie : les règles livrées avec l’application s’appliquent.</p>
      ) : (
        <ul className="reglages-regles-salles">
          {regles.map((r) => (
            <li key={r.id}>
              <span>
                <strong>{nom(r.course_code)}</strong>, {r.session_types.join(" et ")} : {libelleTypeSalle(r.type_prefere)}
                {r.type_repli ? `, sinon ${libelleTypeSalle(r.type_repli)}` : ""}
              </span>
              <button
                type="button"
                disabled={envoi}
                aria-label={`Retirer la règle de ${r.course_code} ${r.session_types.join(" ")}`}
                onClick={() => agir(() => retirerRegleDeSalle(r.id), `Règle de ${r.course_code} retirée.`)}
              >
                Retirer
              </button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="reglages-ajout"
        onSubmit={(e) => {
          e.preventDefault();
          if (!pret) return;
          void agir(
            () =>
              ajouterRegleDeSalle({
                course_code: module,
                session_types: seances,
                type_prefere: prefere,
                type_repli: repli,
              }),
            `Règle de ${module} enregistrée.`,
          );
        }}
      >
        <h3>Ajouter</h3>
        <div className="reglages-champs">
          <label>
            Module
            <select value={module} onChange={(e) => setModule(e.target.value)}>
              <option value="">Choisir…</option>
              {modules.map((m) => (
                <option key={m.valeur} value={m.valeur}>
                  {m.libelle}
                </option>
              ))}
            </select>
          </label>
          <label>
            Type de salle préféré
            <select value={prefere} onChange={(e) => setPrefere(e.target.value)}>
              <option value="">Choisir…</option>
              {types.map((t) => (
                <option key={t} value={t}>
                  {libelleTypeSalle(t)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Sinon (facultatif)
            <select value={repli} onChange={(e) => setRepli(e.target.value)}>
              <option value="">Aucun</option>
              {types
                .filter((t) => t !== prefere)
                .map((t) => (
                  <option key={t} value={t}>
                    {libelleTypeSalle(t)}
                  </option>
                ))}
            </select>
          </label>
        </div>
        <fieldset className="reglages-creneaux">
          <legend>Séances concernées</legend>
          {TYPES_DE_SEANCE.map((t) => (
            <label key={t}>
              <input
                type="checkbox"
                checked={seances.includes(t)}
                onChange={(e) =>
                  setSeances((avant) =>
                    TYPES_DE_SEANCE.filter((x) => (x === t ? e.target.checked : avant.includes(x))),
                  )
                }
              />
              {t}
            </label>
          ))}
        </fieldset>
        {erreur && (
          <p className="alerte" role="alert">
            {erreur}
          </p>
        )}
        <div className="reglages-actions">
          <button type="submit" className="btn btn--primary" disabled={envoi || !pret}>
            Ajouter la règle
          </button>
        </div>
      </form>
    </section>
  );
}
