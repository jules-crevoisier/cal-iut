/**
 * Annuaires des écrans de consultation (refonte v2 du 29/09/2026, cf.
 * docs/DESIGN.md « Gabarit de page », point 4) : ouverts sans entité
 * choisie, la Vue Enseignant, la Vue TD / TP, la Vue Cours et la Vue Salle
 * ne montrent plus une boîte vide « Choisissez… » mais la liste de leurs
 * entités, filtrable, triable, avec les chiffres de la semaine choisie dans
 * la barre supérieure. Un clic ouvre la fiche.
 *
 * Les calculs sont dans `utils/annuaires.ts` (purs, testés à part).
 */

import { useMemo, useState, type ReactNode } from "react";

import { ChampRecherche as ChampRechercheCommun } from "../components/ChampRecherche";
import { ActionsDePage } from "../components/TopBar";
import { TriColonne, useTri } from "../components/TriColonne";
import { useNarrowScreen } from "../hooks/useNarrowScreen";
import type { AppPayload } from "../types/app";
import {
  annuaireCours,
  annuaireEnseignants,
  annuaireGroupes,
  annuaireSalles,
  CRENEAUX_SEMAINE,
  libelleTypeGroupe,
  libelleTypeSalle,
  type LigneCours,
  type LigneEnseignant,
  type LigneGroupe,
  type LigneSalle,
} from "../utils/annuaires";
import { decouperLibelleSemaine, formatHeures, pluriel } from "../utils/planning";
import { normalize } from "../utils/search";

import { EmailEnseignant, MailManquant } from "../components/ValeursReference";
import { PastilleType } from "./EnseignantsVacataires";

import "./annuaires.css";

// Déplacé dans `components/ValeursReference.tsx` (29/09/2026) ; réexporté
// pour les écrans qui l'importaient d'ici.
export { MailManquant };

interface AnnuaireProps {
  payload: AppPayload;
  /** Index d'AFFICHAGE de la semaine (barre supérieure). */
  displayWeek: number;
  /** Actions à droite de la barre d'outils (ex. « Tous les liens »). */
  actions?: ReactNode;
}

/** « Semaine 6 », ou null quand la semaine n'a pas cours (vacances). */
function semaineDe(payload: AppPayload, displayWeek: number): { titre: string; solver: number | null } {
  const row = payload.weekRows[displayWeek];
  return {
    titre: decouperLibelleSemaine(row?.label ?? `Semaine ${displayWeek + 1}`).titre,
    solver: row?.weekIndex ?? null,
  };
}

function correspond(q: string, ...champs: string[]): boolean {
  if (!q) return true;
  const texte = normalize(champs.join(" "));
  return q.split(/\s+/).every((mot) => texte.includes(mot));
}

function ChampRecherche(props: { valeur: string; onChange: (v: string) => void; libelle: string; placeholder: string }) {
  return <ChampRechercheCommun {...props} className="annuaire-recherche" />;
}

/** Valeur + barre proportionnelle : la charge relative se lit d'un coup
 *  d'œil en descendant la colonne. */
function Jauge({ valeur, max, texte, etat }: { valeur: number; max: number; texte: string; etat?: "warn" | "bad" }) {
  const pct = max > 0 ? Math.min(100, Math.round((valeur / max) * 100)) : 0;
  return (
    <span className={`jauge${etat ? ` jauge--${etat}` : ""}${valeur === 0 ? " jauge--nulle" : ""}`}>
      <span className="jauge-texte">{texte}</span>
      <span className="jauge-barre" aria-hidden="true">
        <span style={{ width: `${pct}%` }} />
      </span>
    </span>
  );
}

function SemaineSansCours() {
  return (
    <p className="annuaire-note" role="status">
      Pas de cours cette semaine (vacances ou fermeture) : les chiffres de la semaine sont vides.
    </p>
  );
}

/** Ligne cliquable : le nom est un vrai bouton (clavier, lecteur d'écran),
 *  le reste de la ligne suit le même clic à la souris. */
function useOuvrirLigne(onOuvrir: (id: string) => void) {
  return (id: string) => ({
    className: "annuaire-ligne",
    onClick: (e: React.MouseEvent) => {
      // Un champ de saisie en ligne (« Ajouter » un mail) vit DANS la ligne :
      // cliquer dedans ne doit pas ouvrir la fiche.
      if ((e.target as HTMLElement).closest("button, a, input, select, textarea, form, [data-pas-ouvrir]")) return;
      onOuvrir(id);
    },
  });
}

// ══════════════ Enseignants ══════════════

type FiltreEnseignant = "tous" | "semaine" | "sans-mail" | "ecarts";
/** Filtre par type (01/10/2026) : Enseignant / Vacataire / à préciser. */
type FiltreTypeEnseignant = "" | "enseignant" | "vacataire" | "a-preciser";
type CleEnseignant = "nom" | "code" | "semaine" | "semestre" | "matieres";

const VALEURS_ENSEIGNANT: Record<CleEnseignant, (l: LigneEnseignant) => string | number> = {
  nom: (l) => l.nom,
  code: (l) => l.code,
  semaine: (l) => l.heuresSemaine,
  semestre: (l) => l.heuresSemestre,
  matieres: (l) => l.nMatieres,
};

export function AnnuaireEnseignants({
  payload,
  displayWeek,
  actions,
  onOuvrir,
}: AnnuaireProps & { onOuvrir: (code: string) => void }) {
  const { titre, solver } = semaineDe(payload, displayWeek);
  const lignes = useMemo(() => annuaireEnseignants(payload, solver), [payload, solver]);
  const [recherche, setRecherche] = useState("");
  const [filtre, setFiltre] = useState<FiltreEnseignant>("tous");
  const [filtreType, setFiltreType] = useState<FiltreTypeEnseignant>("");
  const q = normalize(recherche.trim());
  const visibles = useMemo(
    () =>
      lignes.filter(
        (l) =>
          correspond(q, l.nom, l.code, l.email) &&
          (!filtreType || (filtreType === "a-preciser" ? l.type === null : l.type === filtreType)) &&
          (filtre === "tous" ||
            (filtre === "semaine" && l.heuresSemaine > 0) ||
            (filtre === "sans-mail" && !l.email) ||
            (filtre === "ecarts" && l.nEcarts > 0)),
      ),
    [lignes, q, filtre, filtreType],
  );
  // Trié d'abord par heures de la semaine : on voit tout de suite qui
  // enseigne beaucoup. Un clic sur « Nom » revient à l'ordre alphabétique.
  const { triees, tri, trierPar } = useTri<LigneEnseignant, CleEnseignant>(visibles, VALEURS_ENSEIGNANT, { cle: "semaine", sens: -1 });
  const ouvrir = useOuvrirLigne(onOuvrir);
  // Au téléphone, la colonne « Mail » est masquée : le mail manquant (et son
  // « Ajouter ») passe sous le nom, plutôt que de disparaître.
  const etroit = useNarrowScreen();
  // Retour d'enregistrement tenu au niveau de l'annuaire : filtré sur
  // « Adresse mail manquante », la ligne complétée disparaît aussitôt —
  // avec elle, le « Enregistré » du champ.
  const [retour, setRetour] = useState("");
  const enregistre = (nom: string) => (email: string) => setRetour(`Adresse de ${nom} enregistrée : ${email}`);

  const maxSemaine = Math.max(0, ...lignes.map((l) => l.heuresSemaine));
  const actifs = lignes.filter((l) => l.heuresSemaine > 0);
  const sansMail = lignes.filter((l) => !l.email).length;
  const totalSemaine = actifs.reduce((n, l) => n + l.heuresSemaine, 0);

  return (
    <>
      <div className="page-outils">
        <ChampRecherche
          valeur={recherche}
          onChange={setRecherche}
          libelle="Rechercher un enseignant"
          placeholder="Nom, code ou adresse…"
        />
        <label>
          Afficher
          <select value={filtre} onChange={(e) => setFiltre(e.target.value as FiltreEnseignant)}>
            <option value="tous">Tous les enseignants</option>
            <option value="semaine">Avec cours en {titre.toLowerCase()}</option>
            <option value="sans-mail">Adresse mail manquante</option>
            <option value="ecarts">Contrainte non respectée</option>
          </select>
        </label>
        <label>
          Type
          <select value={filtreType} onChange={(e) => setFiltreType(e.target.value as FiltreTypeEnseignant)}>
            <option value="">Enseignants et vacataires</option>
            <option value="enseignant">Enseignants</option>
            <option value="vacataire">Vacataires</option>
            <option value="a-preciser">Type à préciser</option>
          </select>
        </label>
        {actions && <ActionsDePage>{actions}</ActionsDePage>}
      </div>

      <section className="panel annuaire" aria-label="Annuaire des enseignants">
        <header className="annuaire-tete">
          <h2>{pluriel(lignes.length, "enseignant")}</h2>
          <p className="annuaire-faits">
            {solver !== null && (
              <span>
                <strong>{actifs.length}</strong> en cours en {titre.toLowerCase()} ·{" "}
                <strong>{formatHeures(totalSemaine)}</strong>
              </span>
            )}
            {sansMail > 0 && (
              <button type="button" className="linklike annuaire-alerte" onClick={() => setFiltre("sans-mail")}>
                {pluriel(sansMail, "adresse mail manquante", "adresses mail manquantes")}
              </button>
            )}
            <span className="annuaire-retour" role="status" aria-live="polite">
              {retour && <span className="pill dot good">{retour}</span>}
            </span>
          </p>
        </header>
        {solver === null && <SemaineSansCours />}
        <div className="annuaire-defile">
          <table className="ref annuaire-table annuaire-table--enseignants">
            <thead>
              <tr>
                <TriColonne cle="nom" tri={tri} onTrier={trierPar}>
                  Nom
                </TriColonne>
                <TriColonne cle="code" tri={tri} onTrier={trierPar}>
                  Code
                </TriColonne>
                <TriColonne cle="semaine" tri={tri} onTrier={trierPar} num>
                  {titre}
                </TriColonne>
                <TriColonne cle="semestre" tri={tri} onTrier={trierPar} num>
                  Semestre
                </TriColonne>
                <TriColonne cle="matieres" tri={tri} onTrier={trierPar} num>
                  Matières
                </TriColonne>
                <th className="col-etat">Contrainte</th>
                <th className="col-mail">Mail</th>
              </tr>
            </thead>
            <tbody>
              {triees.map((l) => (
                <tr key={l.code} {...ouvrir(l.code)}>
                  <td>
                    <button type="button" className="annuaire-nom" onClick={() => onOuvrir(l.code)}>
                      {l.nom}
                    </button>
                    {l.type && <PastilleType type={l.type} />}
                    {l.nNonPlacees > 0 && (
                      <span className="pill dot warn annuaire-pastille">
                        {pluriel(l.nNonPlacees, "non placée", "non placées")}
                      </span>
                    )}
                    {etroit && !l.email && (
                      <span className="annuaire-mail-telephone">
                        <MailManquant
                          code={l.code}
                          nom={l.nom}
                          libelleBouton="Ajouter le mail"
                          libelleLectureSeule="mail manquant"
                          onEnregistre={enregistre(l.nom)}
                        />
                      </span>
                    )}
                  </td>
                  <td className="mono annuaire-code">{l.code}</td>
                  <td className="num col-jauge">
                    <Jauge valeur={l.heuresSemaine} max={maxSemaine} texte={l.heuresSemaine ? formatHeures(l.heuresSemaine) : "—"} />
                  </td>
                  <td className="num">{l.heuresSemestre ? formatHeures(l.heuresSemestre) : "—"}</td>
                  <td className="num">{l.nMatieres || "—"}</td>
                  <td className="col-etat">
                    <EtatContrainte ligne={l} />
                  </td>
                  <td className="col-mail">
                    {l.email ? (
                      <EmailEnseignant
                        code={l.code}
                        nom={l.nom}
                        email={l.email}
                        surcharge={payload.surchargesReference?.enseignants?.[l.code]?.email}
                        affichage={
                          <span className="annuaire-mail" title={l.email}>
                            {l.email}
                          </span>
                        }
                        onEnregistre={enregistre(l.nom)}
                      />
                    ) : (
                      !etroit && <MailManquant code={l.code} nom={l.nom} onEnregistre={enregistre(l.nom)} />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {triees.length === 0 && <p className="annuaire-vide">Aucun enseignant ne correspond.</p>}
        </div>
      </section>
    </>
  );
}

function EtatContrainte({ ligne }: { ligne: LigneEnseignant }) {
  switch (ligne.contrainte) {
    case "aucune":
      return <span className="muted">—</span>;
    case "respectee":
      return <span className="pill dot good">respectée</span>;
    case "sae":
      return <span className="pill dot">compromis SAE</span>;
    case "ecarts":
      return <span className="pill dot bad">{pluriel(ligne.nEcarts, "écart")}</span>;
  }
}

// ══════════════ Groupes ══════════════

export function AnnuaireGroupes({
  payload,
  displayWeek,
  actions,
  onOuvrir,
}: AnnuaireProps & { onOuvrir: (id: string) => void }) {
  const { titre, solver } = semaineDe(payload, displayWeek);
  const lignes = useMemo(() => annuaireGroupes(payload, solver), [payload, solver]);
  const [recherche, setRecherche] = useState("");
  const q = normalize(recherche.trim());
  const visibles = lignes.filter((l) => correspond(q, l.parcours, l.libelle, libelleTypeGroupe(l.type), l.id));
  const maxSemaine = Math.max(0, ...lignes.map((l) => l.heuresSemaine));

  const parParcours = new Map<string, LigneGroupe[]>();
  for (const l of visibles) {
    const liste = parParcours.get(l.parcours) ?? [];
    liste.push(l);
    parParcours.set(l.parcours, liste);
  }

  return (
    <>
      <div className="page-outils">
        <ChampRecherche
          valeur={recherche}
          onChange={setRecherche}
          libelle="Rechercher un groupe"
          placeholder="Parcours ou groupe (ex. BUT2 TP A)…"
        />
        <span className="annuaire-compte">
          {pluriel(lignes.length, "groupe")} · heures de cours en {titre.toLowerCase()}
        </span>
        {actions && <ActionsDePage>{actions}</ActionsDePage>}
      </div>
      {solver === null && <SemaineSansCours />}
      {parParcours.size === 0 ? (
        <p className="annuaire-vide panel">Aucun groupe ne correspond.</p>
      ) : (
        <div className="annuaire-cartes">
          {[...parParcours.entries()].map(([parcours, groupes]) => {
            return (
              <section key={parcours || "?"} className="panel annuaire-carte" aria-label={parcours || "Sans parcours"}>
                <header className="annuaire-carte-tete">
                  <h2>{parcours || "Sans parcours"}</h2>
                  <span className="annuaire-carte-sous">
                    {pluriel(groupes.length, "groupe")}
                  </span>
                </header>
                <ul className="annuaire-liste">
                  {groupes.map((g) => (
                    <li key={g.id}>
                      <button type="button" className="annuaire-item" onClick={() => onOuvrir(g.id)}>
                        <span className={`annuaire-type annuaire-type--${g.type}`}>{libelleTypeGroupe(g.type)}</span>
                        <span className="annuaire-item-nom" title={g.libelle}>
                          {g.type === "promo" || g.type === "cm" ? "Toute la promo" : g.libelle}
                        </span>
                        <Jauge
                          valeur={g.heuresSemaine}
                          max={maxSemaine}
                          texte={g.heuresSemaine ? formatHeures(g.heuresSemaine) : "—"}
                        />
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </>
  );
}

// ══════════════ Cours ══════════════

type FiltreCours = "toutes" | "semaine" | "incompletes";
type CleCours = "code" | "nom" | "semaine" | "placees" | "heures";

const VALEURS_COURS: Record<CleCours, (l: LigneCours) => string | number> = {
  code: (l) => l.code,
  nom: (l) => l.nom,
  semaine: (l) => l.heuresSemaine,
  placees: (l) => (l.prevues ? l.placees / l.prevues : 1),
  heures: (l) => l.heuresPlacees,
};

export function AnnuaireCours({
  payload,
  displayWeek,
  actions,
  onOuvrir,
}: AnnuaireProps & { onOuvrir: (code: string) => void }) {
  const { titre, solver } = semaineDe(payload, displayWeek);
  const lignes = useMemo(() => annuaireCours(payload, solver), [payload, solver]);
  const parcoursDispo = useMemo(() => [...new Set(lignes.map((l) => l.parcours))], [lignes]);
  const [recherche, setRecherche] = useState("");
  const [parcours, setParcours] = useState("");
  const [filtre, setFiltre] = useState<FiltreCours>("toutes");
  const q = normalize(recherche.trim());
  const visibles = useMemo(
    () =>
      lignes.filter(
        (l) =>
          (!parcours || l.parcours === parcours) &&
          correspond(q, l.code, l.nom, ...l.enseignants.map((t) => payload.teacherLabels[t] ?? t)) &&
          (filtre === "toutes" ||
            (filtre === "semaine" && l.heuresSemaine > 0) ||
            (filtre === "incompletes" && (l.nonPlacees > 0 || l.placees < l.prevues))),
      ),
    [lignes, parcours, q, filtre, payload.teacherLabels],
  );
  const { triees, tri, trierPar } = useTri<LigneCours, CleCours>(visibles, VALEURS_COURS, { cle: "code", sens: 1 });
  const ouvrir = useOuvrirLigne(onOuvrir);
  const maxSemaine = Math.max(0, ...lignes.map((l) => l.heuresSemaine));

  // Sections par parcours · semestre, dans l'ordre d'affichage des
  // parcours ; le tri choisi s'applique à l'intérieur de chacune.
  const sections = new Map<string, LigneCours[]>();
  for (const p of parcoursDispo) sections.set(p, []);
  for (const l of triees) sections.get(l.parcours)?.push(l);
  const incompletes = lignes.filter((l) => l.nonPlacees > 0 || l.placees < l.prevues).length;

  return (
    <>
      <div className="page-outils">
        <ChampRecherche
          valeur={recherche}
          onChange={setRecherche}
          libelle="Rechercher une matière"
          placeholder="Code, intitulé ou enseignant…"
        />
        <label>
          Parcours
          <select value={parcours} onChange={(e) => setParcours(e.target.value)}>
            <option value="">Tous</option>
            {parcoursDispo.map((p) => (
              <option key={p} value={p}>
                {p || "Sans parcours"}
              </option>
            ))}
          </select>
        </label>
        <label>
          Afficher
          <select value={filtre} onChange={(e) => setFiltre(e.target.value as FiltreCours)}>
            <option value="toutes">Toutes les matières</option>
            <option value="semaine">Avec séances en {titre.toLowerCase()}</option>
            <option value="incompletes">Pas entièrement placées</option>
          </select>
        </label>
        {actions && <ActionsDePage>{actions}</ActionsDePage>}
      </div>

      <section className="panel annuaire" aria-label="Annuaire des matières">
        <header className="annuaire-tete">
          <h2>{pluriel(new Set(lignes.map((l) => l.code)).size, "matière")}</h2>
          <p className="annuaire-faits">
            {incompletes > 0 && (
              <button type="button" className="linklike annuaire-alerte" onClick={() => setFiltre("incompletes")}>
                {pluriel(incompletes, "maquette pas entièrement placée", "maquettes pas entièrement placées")}
              </button>
            )}
          </p>
        </header>
        {solver === null && <SemaineSansCours />}
        <div className="annuaire-defile">
          <table className="ref annuaire-table">
            <thead>
              <tr>
                <TriColonne cle="code" tri={tri} onTrier={trierPar}>
                  Code
                </TriColonne>
                <TriColonne cle="nom" tri={tri} onTrier={trierPar}>
                  Matière
                </TriColonne>
                <th className="col-profs">Enseignants</th>
                <TriColonne cle="semaine" tri={tri} onTrier={trierPar} num className="col-optionnelle">
                  {titre}
                </TriColonne>
                <TriColonne cle="placees" tri={tri} onTrier={trierPar} num>
                  Séances placées
                </TriColonne>
                <TriColonne cle="heures" tri={tri} onTrier={trierPar} num className="col-optionnelle">
                  Volume placé
                </TriColonne>
              </tr>
            </thead>
            {[...sections.entries()]
              .filter(([, l]) => l.length > 0)
              .map(([p, liste]) => (
                <tbody key={p || "?"}>
                  <tr className="annuaire-section">
                    <th colSpan={6} scope="colgroup">
                      {p || "Sans parcours"}
                      <span>
                        {[...new Set(liste.map((l) => l.semestre))].join(", ")} · {pluriel(liste.length, "matière")}
                      </span>
                    </th>
                  </tr>
                  {liste.map((l) => {
                    const complet = l.placees >= l.prevues && l.nonPlacees === 0;
                    return (
                      <tr key={`${l.code}-${l.parcours}`} {...ouvrir(l.code)}>
                        <td className="mono">
                          <button type="button" className="annuaire-nom mono" onClick={() => onOuvrir(l.code)}>
                            {l.code}
                          </button>
                        </td>
                        <td className="col-matiere">{l.nom}</td>
                        <td className="col-profs">
                          <span className="annuaire-profs">
                            {l.enseignants.map((t) => payload.teacherLabels[t] ?? t).join(", ") || "—"}
                          </span>
                        </td>
                        <td className="num col-jauge col-optionnelle">
                          <Jauge
                            valeur={l.heuresSemaine}
                            max={maxSemaine}
                            texte={l.heuresSemaine ? formatHeures(l.heuresSemaine) : "—"}
                          />
                        </td>
                        <td className="num col-jauge">
                          {/* La mention « N non placées » va dans une case de
                              largeur fixe APRÈS la jauge : les nombres restent
                              alignés d'une ligne à l'autre. */}
                          <span className="jauge-ligne">
                            <Jauge
                              valeur={l.placees}
                              max={l.prevues}
                              texte={`${l.placees} / ${l.prevues}`}
                              etat={complet ? undefined : "warn"}
                            />
                            <span className="jauge-mention">
                              {l.nonPlacees > 0 && (
                                <span className="pill dot warn">{pluriel(l.nonPlacees, "non placée", "non placées")}</span>
                              )}
                            </span>
                          </span>
                        </td>
                        <td className="num col-optionnelle">{l.heuresPlacees ? formatHeures(l.heuresPlacees) : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              ))}
          </table>
          {triees.length === 0 && <p className="annuaire-vide">Aucune matière ne correspond.</p>}
        </div>
      </section>
    </>
  );
}

// ══════════════ Salles ══════════════

type CleSalle = "libelle" | "type" | "capacite" | "occupation" | "semestre";

const VALEURS_SALLE: Record<CleSalle, (l: LigneSalle) => string | number> = {
  libelle: (l) => l.libelle,
  type: (l) => libelleTypeSalle(l.type),
  capacite: (l) => l.capacite,
  occupation: (l) => l.creneauxOccupes,
  semestre: (l) => l.seancesSemestre,
};

/** Au-delà, la salle est dite « saturée » (mot + couleur, jamais la couleur
 *  seule) : il ne reste que 4 créneaux libres sur 30. */
export const SEUIL_SATUREE = 26 / CRENEAUX_SEMAINE;

export function AnnuaireSalles({
  payload,
  displayWeek,
  actions,
  onOuvrir,
}: AnnuaireProps & { onOuvrir: (id: string) => void }) {
  const { titre, solver } = semaineDe(payload, displayWeek);
  const lignes = useMemo(() => annuaireSalles(payload, solver), [payload, solver]);
  const types = useMemo(() => [...new Set(lignes.map((l) => l.type))].sort((a, b) => libelleTypeSalle(a).localeCompare(libelleTypeSalle(b), "fr")), [lignes]);
  const [recherche, setRecherche] = useState("");
  const [type, setType] = useState("");
  const q = normalize(recherche.trim());
  const visibles = useMemo(
    () => lignes.filter((l) => (!type || l.type === type) && correspond(q, l.libelle, l.id, libelleTypeSalle(l.type))),
    [lignes, type, q],
  );
  // Les plus occupées d'abord : la salle saturée saute aux yeux.
  const { triees, tri, trierPar } = useTri<LigneSalle, CleSalle>(visibles, VALEURS_SALLE, { cle: "occupation", sens: -1 });
  const ouvrir = useOuvrirLigne(onOuvrir);
  const saturees = lignes.filter((l) => l.taux >= SEUIL_SATUREE).length;
  const tauxParc = lignes.length ? lignes.reduce((n, l) => n + l.taux, 0) / lignes.length : 0;

  return (
    <>
      <div className="page-outils">
        <ChampRecherche valeur={recherche} onChange={setRecherche} libelle="Rechercher une salle" placeholder="Nom de la salle…" />
        <label>
          Type
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">Tous les types</option>
            {types.map((t) => (
              <option key={t} value={t}>
                {libelleTypeSalle(t)}
              </option>
            ))}
          </select>
        </label>
        {actions && <ActionsDePage>{actions}</ActionsDePage>}
      </div>

      <section className="panel annuaire" aria-label="Annuaire des salles">
        <header className="annuaire-tete">
          <h2>{pluriel(lignes.length, "salle")}</h2>
          {solver !== null && (
            <p className="annuaire-faits">
              <span>
                Parc occupé à <strong>{Math.round(tauxParc * 100)} %</strong> en {titre.toLowerCase()}
              </span>
              {saturees > 0 && <span className="annuaire-alerte">{pluriel(saturees, "salle saturée", "salles saturées")}</span>}
            </p>
          )}
        </header>
        {solver === null && <SemaineSansCours />}
        <div className="annuaire-defile">
          <table className="ref annuaire-table">
            <thead>
              <tr>
                <TriColonne cle="libelle" tri={tri} onTrier={trierPar}>
                  Salle
                </TriColonne>
                <TriColonne cle="type" tri={tri} onTrier={trierPar} className="col-optionnelle">
                  Type
                </TriColonne>
                <TriColonne cle="capacite" tri={tri} onTrier={trierPar} num>
                  Places
                </TriColonne>
                <TriColonne cle="occupation" tri={tri} onTrier={trierPar} num>
                  Occupation {titre.toLowerCase()}
                </TriColonne>
                <TriColonne cle="semestre" tri={tri} onTrier={trierPar} num className="col-optionnelle">
                  Séances au semestre
                </TriColonne>
              </tr>
            </thead>
            <tbody>
              {triees.map((l) => {
                const saturee = l.taux >= SEUIL_SATUREE;
                return (
                  <tr key={l.id} {...ouvrir(l.id)}>
                    <td>
                      <button type="button" className="annuaire-nom" onClick={() => onOuvrir(l.id)}>
                        {l.libelle}
                      </button>
                      {!l.placementAuto && (
                        <span className="pill annuaire-pastille" title="Choisissable à la main, jamais retenue par le placement automatique">
                          hors auto
                        </span>
                      )}
                    </td>
                    <td className="muted col-optionnelle">{libelleTypeSalle(l.type)}</td>
                    <td className="num">{l.capacite}</td>
                    <td className="num col-jauge col-jauge--large">
                      <span className="jauge-ligne">
                        <Jauge
                          valeur={l.creneauxOccupes}
                          max={CRENEAUX_SEMAINE}
                          texte={solver === null ? "—" : `${l.creneauxOccupes} / ${CRENEAUX_SEMAINE} · ${Math.round(l.taux * 100)} %`}
                          etat={saturee ? "warn" : undefined}
                        />
                        <span className="jauge-mention jauge-mention--court">
                          {saturee && <span className="pill dot warn">saturée</span>}
                        </span>
                      </span>
                    </td>
                    <td className="num col-optionnelle">{l.seancesSemestre || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {triees.length === 0 && <p className="annuaire-vide">Aucune salle ne correspond.</p>}
        </div>
      </section>
    </>
  );
}
