/**
 * « À traiter » → « Données à compléter » (29/09/2026, « quand on a un email
 * manquant, peut-être un numéro de salle Celcat manquant, etc., il faut
 * pouvoir ajouter l'info et l'enregistrer »).
 *
 * La liste vient du serveur (`GET /reference/manques`, la même que l'API v1
 * et les fiches) : mail, nom et correspondance Celcat des enseignants,
 * correspondance Celcat et type des salles, intitulé et code Celcat des
 * matières, identifiants Celcat des groupes. Une ligne par donnée, groupées
 * par famille, chacune avec son champ en ligne — ou, quand ce compte ne peut
 * pas la compléter, qui le peut et où.
 *
 * Les séances placées sans salle font partie de la liste serveur mais ont
 * déjà leur section (« Séances sans salle ») : une seule ligne de renvoi
 * ici, pour ne pas les montrer deux fois.
 */

import { ChevronDown } from "lucide-react";
import { useMemo } from "react";

import type { FamilleManque, Manque } from "../api/client";
import { CompleterManque, PastilleGravite } from "../components/CompleterManque";
import type { Route } from "../hooks/useHashRoute";
import { pluriel } from "../utils/planning";
import { normalize } from "../utils/search";
import type { FiltresTodo } from "../utils/todo";

export const TITRE_COMPLETER = "Données à compléter";

const FAMILLES: { id: Exclude<FamilleManque, "seance">; titre: string }[] = [
  { id: "enseignant", titre: "Enseignants" },
  { id: "salle", titre: "Salles" },
  { id: "cours", titre: "Matières" },
  { id: "groupe", titre: "Groupes (Celcat)" },
];

/** Les données de référence (sans les séances sans salle, déjà traitées ailleurs). */
export function manquesDeReference(manques: Manque[] | null): Manque[] {
  return (manques ?? []).filter((m) => m.famille !== "seance");
}

/** Filtres de l'écran qui ont un sens ici : texte, gravité, enseignant. */
export function filtrerManques(manques: Manque[], filtres: FiltresTodo): Manque[] {
  const q = normalize(filtres.texte.trim());
  return manques.filter((m) => {
    if (q && !q.split(/\s+/).every((mot) => normalize(`${m.libelle} ${m.cle} ${m.champ_libelle}`).includes(mot))) return false;
    if (filtres.gravite === "bad" && m.gravite !== "bloque_celcat") return false;
    if (filtres.gravite === "warn" && m.gravite === "bloque_celcat") return false;
    if (filtres.enseignant && !(m.famille === "enseignant" && m.cle === filtres.enseignant)) return false;
    return true;
  });
}

/** Ton de la tuile et de la pastille : le plus grave l'emporte. */
export function tonManques(manques: Manque[]): "bad" | "warn" | undefined {
  if (manques.some((m) => m.gravite === "bloque_celcat")) return "bad";
  if (manques.some((m) => m.gravite === "bloque_envoi_liens")) return "warn";
  return undefined;
}

interface SectionCompleterProps {
  manques: Manque[] | null;
  filtres: FiltresTodo;
  filtresActifs: boolean;
  replie: boolean;
  onBasculer: () => void;
  refSection: (el: HTMLElement | null) => void;
  setRoute: (patch: Partial<Route>) => void;
  /** Aller à la section « Séances sans salle ». */
  onVoirSansSalle: () => void;
}

export function SectionCompleter({
  manques,
  filtres,
  filtresActifs,
  replie,
  onBasculer,
  refSection,
  setRoute,
  onVoirSansSalle,
}: SectionCompleterProps) {
  const reference = useMemo(() => manquesDeReference(manques), [manques]);
  const visibles = useMemo(() => filtrerManques(reference, filtres), [reference, filtres]);
  const sansSalle = (manques ?? []).filter((m) => m.famille === "seance").length;
  const nb = visibles.length;
  const chargement = manques === null;
  const vide = !chargement && nb === 0 && !(filtresActifs && reference.length > 0);
  const ton = tonManques(visibles);
  const idCorps = "todo-corps-completer";

  return (
    <section
      className={`todo-section todo-completer${replie && !vide ? " replie" : ""}${vide ? " vide" : ""}`}
      ref={refSection}
      aria-labelledby="todo-titre-completer"
    >
      <header className="todo-section-tete">
        <button
          type="button"
          className="todo-section-bascule"
          aria-expanded={vide ? undefined : !replie}
          aria-controls={vide ? undefined : idCorps}
          onClick={vide ? undefined : onBasculer}
          disabled={vide}
        >
          <ChevronDown size={16} className="todo-chevron" aria-hidden="true" />
          <h3 id="todo-titre-completer">{TITRE_COMPLETER}</h3>
          {nb > 0 && (
            <span className={`pill ${ton ?? ""}`.trim()} aria-label={pluriel(nb, "donnée")}>
              {nb}
            </span>
          )}
          {filtresActifs && reference.length !== nb && <span className="muted small">sur {reference.length}</span>}
        </button>
        {vide && (
          <span className="todo-section-rien" role="status">
            Aucune donnée de référence ne manque.
          </span>
        )}
        {!replie && !vide && (
          <p className="todo-section-aide">
            Mail, nom, correspondance Celcat, type de salle, intitulé : ce qui manque se complète ici, sans
            déploiement. La correspondance Celcat reste réservée aux administrateurs.
          </p>
        )}
      </header>

      {!replie && !vide && (
        <div className="todo-section-corps" id={idCorps}>
          {chargement && (
            <p className="muted todo-vide" role="status">
              Chargement…
            </p>
          )}
          {!chargement && nb === 0 && (
            <p className="muted todo-vide" role="status">
              Aucune donnée ne correspond aux filtres.
            </p>
          )}
          {nb > 0 && (
            <ul className="todo-liste completer-liste">
              {FAMILLES.map((f) => {
                const lignes = visibles.filter((m) => m.famille === f.id);
                if (lignes.length === 0) return null;
                return [
                  <li key={`t-${f.id}`} className="todo-semaine">
                    <span>{f.titre}</span>
                    <span className="todo-semaine-nb">{lignes.length}</span>
                  </li>,
                  ...lignes.map((m) => <LigneManque key={m.id} manque={m} setRoute={setRoute} />),
                ];
              })}
            </ul>
          )}
          {sansSalle > 0 && (
            <p className="completer-renvoi">
              <span>
                Et {pluriel(sansSalle, "séance placée", "séances placées")} sans salle : la salle se choisit en Vue Promo.
              </span>
              <button type="button" className="btn btn--ghost btn--sm" onClick={onVoirSansSalle}>
                Voir « Séances sans salle »
              </button>
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function LigneManque({ manque: m, setRoute }: { manque: Manque; setRoute: (patch: Partial<Route>) => void }) {
  const ouvrable = m.famille === "enseignant" || m.famille === "salle" || m.famille === "cours";
  const ecran: Partial<Route> =
    m.famille === "enseignant" ? { vue: "prof", prof: m.cle } : m.famille === "salle" ? { vue: "salle", salle: m.cle } : { vue: "cours", cours: m.cle };
  return (
    <li className="completer-ligne">
      <span className="completer-qui">
        {ouvrable ? (
          <button type="button" className="completer-nom" onClick={() => setRoute(ecran)} title="Ouvrir la fiche">
            {m.libelle}
          </button>
        ) : (
          <strong className="completer-nom completer-nom--texte">{m.libelle}</strong>
        )}
        {m.libelle !== m.cle && <span className="mono completer-cle">{m.cle}</span>}
      </span>
      <span className="completer-quoi">
        <span className="completer-champ">{m.champ_libelle}</span>
        <span className="todo-detail">{m.usage}</span>
      </span>
      <PastilleGravite gravite={m.gravite} />
      <span className="completer-action">
        <CompleterManque manque={m} setRoute={setRoute} />
      </span>
    </li>
  );
}
