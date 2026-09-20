/**
 * Ce que le worker écarte à chaque passage, et comment le débloquer.
 *
 * Le 20/09/2026, la production tournait avec trente corrections bloquées
 * depuis des jours — deux salles sans équivalent Celcat, trois séances dont
 * l'enseignante n'avait pas de code, vingt-cinq séances disparues de la
 * maquette. Le worker les réécartait toutes les quatre-vingt-dix secondes, et
 * **rien n'apparaissait dans l'application** : l'information vivait dans
 * `docker compose logs`. La file ne descendait pas, sans que rien ne dise
 * pourquoi.
 *
 *     « il faut faire en sorte d'avoir des logs sur ce qu'il se passe,
 *       exemple : prof non attribué dans Celcat, salle non mappée »
 *     « pour la salle il faut avoir une option pour mapper »
 *
 * Deux principes ici :
 *
 *   - CHAQUE BLOCAGE PORTE SON GESTE. Une salle sans équivalent se règle sur
 *     place ; une séance disparue de la maquette ne se mappe pas, et l'écran
 *     le dit plutôt que de proposer un champ inutile.
 *   - ON CHOISIT DANS UNE LISTE RÉELLE. Les salles proposées sont celles que
 *     le relevé a vues dans Celcat : inventer un nom ferait échouer
 *     l'écriture plus tard, loin de la saisie.
 */
import { useState } from "react";

import type { CelcatBlocage, CelcatMappings } from "../api/client";
import { dateLisible, pluriel } from "../utils/celcatStatut";

/** Que faire d'un blocage qu'aucune correspondance ne règle.
 *
 * « Rien à mapper » ne suffit pas : il faut dire OÙ regarder. Le 20/09/2026,
 * sept séances de WR303D étaient annoncées « inconnues de la maquette »
 * alors qu'elles y figuraient toutes — elles n'avaient simplement plus de
 * place au planning. */
function conseil(motif: string): string {
  if (motif.includes("sans placement")) {
    return (
      "Rien à mapper ici : cette séance n’a plus de place au planning. Replacez-la depuis " +
      "« À placer » si elle doit aller dans Celcat ; sinon, reconstruisez la file depuis les " +
      "réglages — cela ne retire que les jobs des semaines enregistrées."
    );
  }
  if (motif.includes("suppression refusée")) {
    return "Un garde-fou a refusé cette suppression : l’évènement est protégé, férié ou fantôme.";
  }
  if (motif.includes("event_id")) {
    return "Ce job vise un évènement Celcat sans identifiant : reconstruisez la file pour le recalculer.";
  }
  return "Rien à mapper ici.";
}

const AIDE_FAMILLE: Record<string, string> = {
  salles: "Sous quel nom Celcat connaît-il cette salle ?",
  enseignants: "Identifiant Celcat de cet enseignant (un nombre, visible dans Celcat).",
};

function FormulaireMapping({
  blocage,
  sallesCelcat,
  occupe,
  onMapper,
}: {
  blocage: CelcatBlocage;
  sallesCelcat: string[];
  occupe: boolean;
  onMapper: (famille: "salles" | "enseignants", cle: string, valeur: string) => void;
}) {
  const [valeur, setValeur] = useState("");
  const famille = blocage.famille as "salles" | "enseignants";
  const listeId = `celcat-salles-connues`;

  return (
    <form
      className="celcat-mapping-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (valeur.trim()) onMapper(famille, blocage.cle, valeur.trim());
      }}
    >
      <label>
        <span className="celcat-sous-texte">{AIDE_FAMILLE[famille]}</span>
        <input
          type="text"
          value={valeur}
          list={famille === "salles" ? listeId : undefined}
          placeholder={famille === "salles" ? "H.104" : "38999"}
          aria-label={`Équivalent Celcat de ${blocage.cle}`}
          disabled={occupe}
          onChange={(e) => setValeur(e.target.value)}
        />
      </label>
      <button type="submit" className="btn btn--accent" disabled={occupe || !valeur.trim()}>
        Mapper
      </button>
      {famille === "salles" ? (
        <datalist id={listeId}>
          {sallesCelcat.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      ) : null}
    </form>
  );
}

export function BlocagesCelcat({
  mappings,
  occupe,
  erreur,
  onMapper,
  onOublier,
}: {
  mappings: CelcatMappings | null;
  occupe: boolean;
  erreur: string | null;
  onMapper: (famille: "salles" | "enseignants", cle: string, valeur: string) => void;
  onOublier: (famille: "salles" | "enseignants", cle: string) => void;
}) {
  if (!mappings) return null;
  const blocages = mappings.manquants ?? [];
  const correspondances = [
    ...mappings.salles.map((m) => ({ ...m, famille: "salles" as const })),
    ...mappings.enseignants.map((m) => ({ ...m, famille: "enseignants" as const })),
  ];
  if (blocages.length === 0 && correspondances.length === 0 && !(mappings.bloques_autres_semaines ?? 0))
    return null;

  const seances = blocages.reduce((n, b) => n + b.seances.length, 0);
  const ailleurs = mappings.bloques_autres_semaines ?? 0;

  return (
    <section className="panel celcat-blocages" aria-labelledby="celcat-blocages-titre">
      <h2 id="celcat-blocages-titre">
        {blocages.length === 0
          ? "Correspondances ajoutées"
          : `${pluriel(seances, "séance bloquée", "séances bloquées")} cette semaine`}
      </h2>
      {blocages.length > 0 ? (
        <p className="celcat-aide">
          Le worker les écarte à chaque passage : il leur manque une correspondance. Une fois
          réglée, elles repartent d’elles-mêmes — elles n’ont jamais quitté la file.
        </p>
      ) : null}

      {/* Filtrer sans le dire ferait croire que le reste s'est réglé. */}
      {ailleurs > 0 ? (
        <p className="celcat-sous-texte" data-testid="blocages-autres-semaines">
          {pluriel(ailleurs, "autre blocage", "autres blocages")} sur d’autres semaines — changez de
          semaine pour les traiter.
        </p>
      ) : null}

      {erreur ? (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      ) : null}

      <ul className="celcat-liste">
        {blocages.map((b) => (
          <li key={b.motif} className="celcat-blocage" data-testid={`blocage-${b.famille || "autre"}`}>
            <div className="celcat-blocage-entete">
              <strong>{b.motif}</strong>
              <span className="celcat-sous-texte">
                {pluriel(b.seances.length, "séance")} · {pluriel(b.tentatives, "tentative")}
              </span>
            </div>
            <div className="celcat-sous-texte">{b.seances.slice(0, 6).join(", ")}
              {b.seances.length > 6 ? ` et ${b.seances.length - 6} autre(s)` : ""}
            </div>
            {b.famille && b.cle ? (
              <FormulaireMapping
                blocage={b}
                sallesCelcat={mappings.salles_celcat ?? []}
                occupe={occupe}
                onMapper={onMapper}
              />
            ) : (
              <p className="celcat-sous-texte">{conseil(b.motif)}</p>
            )}
          </li>
        ))}
      </ul>

      {correspondances.length > 0 ? (
        <details className="celcat-repli" data-testid="mappings-existants">
          <summary>{pluriel(correspondances.length, "correspondance ajoutée", "correspondances ajoutées")}</summary>
          <ul className="celcat-liste">
            {correspondances.map((m) => (
              <li key={`${m.famille}-${m.cle}`} className="celcat-liste-ligne">
                <span>
                  <strong>{m.cle}</strong> → {m.valeur}
                </span>
                <span className="celcat-sous-texte">
                  {m.ajoute_par ? `${m.ajoute_par}, ` : ""}
                  {dateLisible(m.ajoute_le)}
                </span>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  disabled={occupe}
                  aria-label={`Retirer la correspondance ${m.cle}`}
                  onClick={() => onOublier(m.famille, m.cle)}
                >
                  Retirer
                </button>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
