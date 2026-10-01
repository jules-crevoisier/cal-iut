/**
 * Référence → « Enseignants & vacataires » (01/10/2026).
 *
 * Demande de Kyllian Bresson (responsable) : « la liste de tous les
 * enseignants et vacataires présents dans l'outil » — prénom, nom,
 * diminutif, code Celcat, adresse e-mail, numéro de téléphone —, avec la
 * distinction Enseignant / Vacataire, pour un usage quotidien : recherche,
 * tri, modification.
 *
 * UNE SEULE SOURCE : `GET /reference/enseignants` relit la liste de
 * l'annuaire (`teacherLabels`), les identités (`teacherIdentites`), les
 * mails, et la ligne même de l'onglet « Codes Celcat ». Une modification
 * ici est une surcharge de référence (`data/state/references.json`) : elle
 * se voit aussitôt dans l'annuaire de la Vue Enseignant, la fiche, « Liens
 * & partage », « Nouvelle séance », l'API v1.
 *
 * Droits : prénom, nom, mail, téléphone, type → rôle `edit` ou `admin` ;
 * code Celcat et « Nouvel intervenant » → `admin`. En lecture seule, le
 * téléphone est masqué (« — ») : le serveur ne l'envoie pas.
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  completerEnseignant,
  definirCodeCelcat,
  fetchAnnuaireEnseignants,
  retablirValeurFichier,
  type AnnuaireEnseignantsReponse,
  type LigneAnnuaireEnseignant,
  type SurchargeIdentite,
} from "../api/client";
import { ChampEnLigne } from "../components/ChampEnLigne";
import { ChampRecherche } from "../components/ChampRecherche";
import { TriColonne, useTri } from "../components/TriColonne";
import { Tuile, Tuiles } from "../components/Tuile";
import { EmailEnseignant, MarqueModifiee } from "../components/ValeursReference";
import { useDroits } from "../contexts/Droits";
import { useNarrowScreen } from "../hooks/useNarrowScreen";
import type { Route } from "../hooks/useHashRoute";
import type { TypeEnseignant } from "../types/app";
import { csvDepuis, telechargerCsv } from "../utils/csv";
import { formaterTelephone, libelleType, normaliserTelephone, validerTelephone } from "../utils/identiteEnseignant";
import { normalize } from "../utils/search";
import { ecrireLocal, lireLocal } from "../utils/stockageLocal";
import { CelluleCode } from "./CodesCelcat";

import "./EnseignantsVacataires.css";

export type FiltreType = "tous" | "enseignant" | "vacataire" | "a-preciser" | "sans-mail" | "sans-telephone";

const FILTRES_TYPE: { id: FiltreType; label: string }[] = [
  { id: "tous", label: "Tous" },
  { id: "enseignant", label: "Enseignants" },
  { id: "vacataire", label: "Vacataires" },
  { id: "a-preciser", label: "À préciser" },
];

const CLE_TRI = "cal-iut:reference:enseignants:tri:v1";
const CLE_FILTRE = "cal-iut:reference:enseignants:filtre:v1";

type CleTri = "type" | "prenom" | "nom" | "code" | "celcat" | "email" | "telephone" | "seances";

const ORDRE_TYPE: Record<string, number> = { enseignant: 0, vacataire: 1, "": 2 };

const VALEURS: Record<CleTri, (l: LigneAnnuaireEnseignant) => string | number> = {
  type: (l) => ORDRE_TYPE[l.type ?? ""] ?? 2,
  prenom: (l) => l.prenom || "￿",
  nom: (l) => l.nom || l.nom_complet,
  code: (l) => l.code,
  celcat: (l) => l.code_celcat?.code ?? "￿",
  email: (l) => l.email ?? "￿",
  telephone: (l) => l.telephone ?? "￿",
  seances: (l) => l.nb_seances,
};

function estFiltre(v: unknown): v is FiltreType {
  return typeof v === "string" && ["tous", "enseignant", "vacataire", "a-preciser", "sans-mail", "sans-telephone"].includes(v);
}

function pluriel(n: number, un: string, plusieurs = `${un}s`): string {
  return `${n} ${n > 1 ? plusieurs : un}`;
}

/** La ligne passe-t-elle la recherche (nom, prénom, diminutif, mail) ? */
export function correspondRecherche(l: LigneAnnuaireEnseignant, recherche: string): boolean {
  const q = normalize(recherche.trim());
  if (!q) return true;
  const botte = normalize(`${l.prenom} ${l.nom} ${l.nom_complet} ${l.code} ${l.email ?? ""}`);
  return q.split(/\s+/).every((mot) => botte.includes(mot));
}

export function correspondFiltre(l: LigneAnnuaireEnseignant, filtre: FiltreType): boolean {
  switch (filtre) {
    case "tous":
      return true;
    case "enseignant":
    case "vacataire":
      return l.type === filtre;
    case "a-preciser":
      return l.type === null;
    case "sans-mail":
      return !l.email;
    case "sans-telephone":
      return !l.telephone;
  }
}

/** Contenu du CSV « Annuaire » : le tableau, téléphone seulement si visible. */
export function csvAnnuaire(lignes: LigneAnnuaireEnseignant[], avecTelephone: boolean): string {
  const entetes = ["Type", "Prénom", "Nom", "Diminutif", "Code Celcat", "E-mail", ...(avecTelephone ? ["Téléphone"] : []), "Séances"];
  return csvDepuis(
    entetes,
    lignes.map((l) => [
      l.type ? libelleType(l.type) : "à préciser",
      l.prenom,
      l.nom,
      l.code,
      l.code_celcat?.code ?? "",
      l.email ?? "",
      ...(avecTelephone ? [formaterTelephone(l.telephone)] : []),
      l.nb_seances,
    ]),
  );
}

export function PastilleType({ type }: { type: TypeEnseignant | null }) {
  return (
    <span className={`pill dot type-pill type-pill--${type ?? "a-preciser"}${type ? "" : " warn"}`}>{libelleType(type)}</span>
  );
}

interface Props {
  setRoute: (patch: Partial<Route>) => void;
  /** « Nouvel intervenant » (administrateurs) : la modale de Référence. */
  onNouvelIntervenant?: () => void;
}

export function EnseignantsVacataires({ setRoute, onNouvelIntervenant }: Props) {
  const { revision, apresEnregistrement } = useDroits();
  const [donnees, setDonnees] = useState<AnnuaireEnseignantsReponse | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [texte, setTexte] = useState("");
  const [filtre, setFiltreEtat] = useState<FiltreType>(() => lireLocal(CLE_FILTRE, "tous", estFiltre));
  const [retour, setRetour] = useState("");
  const etroit = useNarrowScreen();

  const setFiltre = (f: FiltreType) => {
    setFiltreEtat(f);
    ecrireLocal(CLE_FILTRE, f);
  };

  const recharger = useCallback(async () => {
    try {
      setDonnees(await fetchAnnuaireEnseignants());
      setErreur(null);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Annuaire indisponible.");
    }
  }, []);

  // Relu à chaque avance de la révision : une modification faite ailleurs
  // (fiche, Codes Celcat, un collègue) apparaît ici aussi.
  useEffect(() => {
    void recharger();
  }, [recharger, revision]);

  const apres = async (message: string) => {
    setRetour(message);
    await recharger();
    apresEnregistrement();
  };

  const lignes = useMemo(() => donnees?.lignes ?? [], [donnees]);
  // Filtre « Sans téléphone » retenu sur ce poste, pour un compte qui ne
  // voit pas les téléphones : sans objet, on montre tout.
  const filtreEffectif: FiltreType = filtre === "sans-telephone" && donnees && !donnees.telephone_visible ? "tous" : filtre;
  const filtrees = useMemo(
    () => lignes.filter((l) => correspondFiltre(l, filtreEffectif) && correspondRecherche(l, texte)),
    [lignes, filtreEffectif, texte],
  );
  const { triees, tri, trierPar } = useTri<LigneAnnuaireEnseignant, CleTri>(filtrees, VALEURS, { cle: "nom", sens: 1 }, CLE_TRI);

  if (!donnees) {
    return erreur ? (
      <p className="alerte" role="alert">
        Annuaire des enseignants indisponible : {erreur}
      </p>
    ) : (
      <p className="page-note" aria-busy="true">
        Chargement des enseignants…
      </p>
    );
  }

  const { compteurs, peut_modifier: peutModifier, admin, telephone_visible: telVisible } = donnees;
  const col = (cle: CleTri, libelle: string, num = false, className?: string) => (
    <TriColonne key={cle} cle={cle} tri={tri} onTrier={trierPar} num={num} className={className}>
      {libelle}
    </TriColonne>
  );
  const tuile = (id: FiltreType, libelle: string, valeur: number, detail: string, ton?: "warn") => (
    <Tuile
      libelle={libelle}
      valeur={valeur}
      detail={detail}
      ton={ton && valeur > 0 ? ton : undefined}
      nul={valeur === 0}
      actif={filtre === id}
      onClick={() => setFiltre(filtre === id ? "tous" : id)}
      title={filtre === id ? "Retirer ce filtre" : `Afficher : ${libelle.toLowerCase()}`}
    />
  );

  // La liste est relue APRÈS que le champ a affiché « Enregistré » (pas
  // attendue) : le champ repasse alors au repos sur la valeur rangée par le
  // serveur (« Nino-Rossi » -> « NINO-ROSSI »), cf. `ChampEnLigne`.
  const enregistrer = (l: LigneAnnuaireEnseignant, corps: Parameters<typeof completerEnseignant>[1], quoi: string) =>
    completerEnseignant(l.code, corps).then(() => {
      void apres(`${l.nom_complet} : ${quoi} enregistré.`);
    });

  const revenir = (l: LigneAnnuaireEnseignant, champ: "prenom" | "nom_famille" | "telephone" | "type", quoi: string) =>
    retablirValeurFichier("enseignants", l.code, champ).then(() => {
      void apres(`${l.nom_complet} : ${quoi} rétabli.`);
    });

  // Colonnes, dans l'ordre de lecture ; au téléphone, les colonnes clés
  // d'abord (nom, diminutif, téléphone, mail), le reste en défilant.
  const colonnes: { cle: CleTri | "fiche"; th: ReactNode; td: (l: LigneAnnuaireEnseignant) => ReactNode; classe?: string }[] = [
    { cle: "type", th: col("type", "Type"), td: (l) => <CelluleType ligne={l} peutModifier={peutModifier} enregistrer={enregistrer} revenir={revenir} /> },
    {
      cle: "prenom",
      th: col("prenom", "Prénom"),
      td: (l) => (
        <CelluleIdentite
          ligne={l}
          champ="prenom"
          peutModifier={peutModifier}
          enregistrer={enregistrer}
          revenir={revenir}
        />
      ),
    },
    {
      cle: "nom",
      th: col("nom", "Nom", false, "ev-col-nom"),
      classe: "ev-col-nom",
      td: (l) => (
        <>
          <CelluleIdentite ligne={l} champ="nom_famille" peutModifier={peutModifier} enregistrer={enregistrer} revenir={revenir} />
          {l.cree_dans_appli && <span className="ev-note">ajouté dans l’appli</span>}
        </>
      ),
    },
    { cle: "code", th: col("code", "Diminutif"), td: (l) => <span className="mono ev-code">{l.code}</span> },
    {
      cle: "celcat",
      th: col("celcat", "Code Celcat"),
      td: (l) => <CelluleCelcat ligne={l} onEnregistre={apres} setRoute={setRoute} />,
    },
    {
      cle: "email",
      th: col("email", "E-mail"),
      td: (l) => (
        <EmailEnseignant
          code={l.code}
          nom={l.nom_complet}
          email={l.email ?? ""}
          surcharge={surchargeReference(l.surcharges.email)}
          affichage={
            <a className="ev-mail" href={`mailto:${l.email}`} title={l.email ?? undefined}>
              {l.email}
            </a>
          }
          onEnregistre={(email) => void apres(`${l.nom_complet} : adresse enregistrée (${email}).`)}
          manquant={peutModifier ? undefined : <span className="ref-zero">—</span>}
        />
      ),
    },
    {
      cle: "telephone",
      th: col("telephone", "Téléphone"),
      td: (l) =>
        telVisible ? (
          <CelluleTelephone ligne={l} peutModifier={peutModifier} enregistrer={enregistrer} revenir={revenir} />
        ) : (
          <span className="ref-zero" title="Visible pour les comptes qui peuvent modifier">
            —
          </span>
        ),
    },
    { cle: "seances", th: col("seances", "Séances", true), classe: "num", td: (l) => l.nb_seances || <span className="ref-zero">0</span> },
    {
      cle: "fiche",
      th: (
        <th key="fiche">
          <span className="sr-only">Fiche</span>
        </th>
      ),
      td: (l) => (
        <button
          type="button"
          className="btn btn--ghost btn--sm ev-fiche"
          onClick={() => setRoute({ vue: "prof", prof: l.code })}
          aria-label={`Voir la fiche de ${l.nom_complet}`}
        >
          Voir la fiche
        </button>
      ),
    },
  ];
  const ordreEtroit: (CleTri | "fiche")[] = ["nom", "code", "telephone", "email", "prenom", "type", "celcat", "seances", "fiche"];
  const visibles = etroit ? ordreEtroit.map((c) => colonnes.find((x) => x.cle === c)!) : colonnes;

  return (
    <div className="ens-vac">
      <Tuiles label="Enseignants et vacataires" className="ev-tuiles">
        {tuile("enseignant", "Enseignants", compteurs.enseignants, "type « Enseignant »")}
        {tuile("vacataire", "Vacataires", compteurs.vacataires, "type « Vacataire »")}
        {tuile("a-preciser", "À préciser", compteurs.a_preciser, "type non renseigné", "warn")}
        {tuile("sans-mail", "Sans mail", compteurs.sans_mail, "pas de lien personnel par mail", "warn")}
        {telVisible &&
          compteurs.sans_telephone !== null &&
          tuile("sans-telephone", "Sans téléphone", compteurs.sans_telephone, "numéro non renseigné")}
      </Tuiles>

      <div className="page-outils ref-barre">
        <ChampRecherche
          className="ref-recherche"
          placeholder="Nom, prénom, diminutif ou mail…"
          libelle="Rechercher un enseignant ou un vacataire"
          valeur={texte}
          onChange={setTexte}
        />
        <div className="pastilles" role="group" aria-label="Type">
          {FILTRES_TYPE.map((f) => (
            <button key={f.id} type="button" className="pastille" aria-pressed={filtre === f.id} onClick={() => setFiltre(f.id)}>
              {f.label}
              <span className="pastille-nb">
                {f.id === "tous"
                  ? compteurs.total
                  : f.id === "enseignant"
                    ? compteurs.enseignants
                    : f.id === "vacataire"
                      ? compteurs.vacataires
                      : compteurs.a_preciser}
              </span>
            </button>
          ))}
        </div>
        <span className="ref-resume" aria-live="polite">
          {filtrees.length === lignes.length ? pluriel(lignes.length, "personne") : `${filtrees.length} sur ${pluriel(lignes.length, "personne")}`}
        </span>
        <span className="page-outils-actions">
          <button
            type="button"
            className="btn btn--sm"
            onClick={() => telechargerCsv("annuaire-enseignants.csv", csvAnnuaire(triees, telVisible))}
            title={telVisible ? "Les lignes affichées, téléphone compris" : "Les lignes affichées (sans téléphone)"}
          >
            Annuaire (.csv)
          </button>
          {admin && onNouvelIntervenant && (
            <button type="button" className="btn btn--primary btn--sm" onClick={onNouvelIntervenant}>
              Nouvel intervenant
            </button>
          )}
        </span>
      </div>

      <p className="ref-aide">
        {peutModifier
          ? "Cliquez sur le crayon d’une cellule pour la modifier : Entrée enregistre, Échap annule. Le diminutif ne change pas : c’est l’identifiant de la personne partout dans l’outil."
          : "Lecture seule. Le téléphone n’est visible que des comptes qui peuvent modifier."}
        {peutModifier && !admin && " Le code Celcat se saisit par un administrateur."}
      </p>

      <p className="page-retour" role="status" aria-live="polite">
        {retour}
      </p>
      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}

      <div className="panel carte-tableau carte-tableau--haute ref-tableau ev-carte">
        <table className={`ref ev-table${etroit ? " ev-table--etroite" : ""}`}>
          <thead>
            <tr>{visibles.map((c) => c.th)}</tr>
          </thead>
          <tbody>
            {triees.map((l) => (
              <tr key={l.code} data-cle={l.code}>
                {visibles.map((c) => (
                  <td key={c.cle} className={c.classe}>
                    {c.td(l)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {triees.length === 0 && <p className="ref-vide">Aucun enseignant ne correspond.</p>}
      </div>
    </div>
  );
}

function surchargeReference(s: SurchargeIdentite | undefined) {
  return s && s.valeur !== null ? { valeur: s.valeur, origine: s.origine, modifie_le: s.modifie_le, modifie_par: s.modifie_par } : undefined;
}

type Enregistrer = (l: LigneAnnuaireEnseignant, corps: Parameters<typeof completerEnseignant>[1], quoi: string) => Promise<void>;
type Revenir = (l: LigneAnnuaireEnseignant, champ: "prenom" | "nom_famille" | "telephone" | "type", quoi: string) => Promise<void>;

function CelluleIdentite({
  ligne: l,
  champ,
  peutModifier,
  enregistrer,
  revenir,
}: {
  ligne: LigneAnnuaireEnseignant;
  champ: "prenom" | "nom_famille";
  peutModifier: boolean;
  enregistrer: Enregistrer;
  revenir: Revenir;
}) {
  const valeur = champ === "prenom" ? l.prenom : l.nom;
  const quoi = champ === "prenom" ? "prénom" : "nom";
  const libelle = `${champ === "prenom" ? "Prénom" : "Nom"} de ${l.nom_complet} (${l.code})`;
  const surcharge = surchargeReference(l.surcharges[champ]);
  const marque = surcharge ? (
    <MarqueModifiee
      surcharge={surcharge}
      libelleChamp={libelle}
      onRevenir={peutModifier ? () => revenir(l, champ, quoi) : undefined}
    />
  ) : null;
  const affichage = valeur ? (
    <span className={champ === "nom_famille" ? "ev-nom" : undefined}>{valeur}</span>
  ) : (
    <span className="ref-zero">—</span>
  );
  if (!peutModifier) {
    return (
      <span className="valeur-modifiable">
        {affichage}
        {marque}
      </span>
    );
  }
  return (
    <ChampEnLigne
      mode={valeur ? "modifier" : "ajouter"}
      libelleChamp={libelle}
      valeurInitiale={valeur}
      valeurAffichee={affichage}
      apres={marque}
      placeholder={champ === "prenom" ? "Prénom" : "NOM"}
      taille={16}
      valider={(v) => (/\p{L}/u.test(v) ? null : `Saisissez le ${quoi}.`)}
      onEnregistrer={(v) => enregistrer(l, { [champ]: v }, quoi)}
    />
  );
}

const OPTIONS_TYPE = [
  { value: "enseignant", label: "Enseignant" },
  { value: "vacataire", label: "Vacataire" },
  { value: "", label: "À préciser" },
];

function CelluleType({
  ligne: l,
  peutModifier,
  enregistrer,
  revenir,
}: {
  ligne: LigneAnnuaireEnseignant;
  peutModifier: boolean;
  enregistrer: Enregistrer;
  revenir: Revenir;
}) {
  const pastille = <PastilleType type={l.type} />;
  if (!peutModifier) return pastille;
  return (
    <ChampEnLigne
      mode="modifier"
      libelleChamp={`Type de ${l.nom_complet} (${l.code})`}
      options={OPTIONS_TYPE}
      valeurInitiale={l.type ?? ""}
      valeurAffichee={pastille}
      valider={() => null}
      onEnregistrer={async (v) => {
        if (v === (l.type ?? "")) return;
        if (!v) await revenir(l, "type", "type « à préciser »");
        else await enregistrer(l, { type: v }, "type");
      }}
    />
  );
}

function CelluleTelephone({
  ligne: l,
  peutModifier,
  enregistrer,
  revenir,
}: {
  ligne: LigneAnnuaireEnseignant;
  peutModifier: boolean;
  enregistrer: Enregistrer;
  revenir: Revenir;
}) {
  const affiche = l.telephone_affiche ?? formaterTelephone(l.telephone);
  const lien = l.telephone ? (
    <a className="ev-tel" href={`tel:${l.telephone}`}>
      {affiche}
    </a>
  ) : null;
  if (!peutModifier) return lien ?? <span className="ref-zero">—</span>;
  const libelle = `Téléphone de ${l.nom_complet} (${l.code})`;
  return (
    <ChampEnLigne
      mode={l.telephone ? "modifier" : "ajouter"}
      libelleChamp={libelle}
      type="tel"
      valeurInitiale={affiche}
      valeurAffichee={lien}
      placeholder="06 12 34 56 78"
      taille={16}
      // Vider le champ retire le numéro (il n'a pas de « valeur du fichier »).
      valider={(v) => (!v.trim() && l.telephone ? null : validerTelephone(v))}
      onEnregistrer={async (v) => {
        if (!v.trim()) {
          await revenir(l, "telephone", "téléphone retiré, numéro");
          return;
        }
        await enregistrer(l, { telephone: normaliserTelephone(v) ?? v }, "téléphone");
      }}
    />
  );
}

function CelluleCelcat({
  ligne: l,
  onEnregistre,
  setRoute,
}: {
  ligne: LigneAnnuaireEnseignant;
  onEnregistre: (message: string) => Promise<void>;
  setRoute: (patch: Partial<Route>) => void;
}) {
  const c = l.code_celcat;
  if (!c) return <span className="ref-zero">—</span>;
  // Origine discrète : le cadenas dit déjà « code connu » ; le mot n'est
  // écrit que s'il apprend quelque chose (maquette, saisi, voulu).
  const titre =
    c.origine === "fichier"
      ? "Origine : fichier de configuration (celcat.yaml)"
      : c.origine === "manquant"
        ? "Pas de code Celcat : ses séances ne partent pas vers Celcat"
        : undefined;
  const origine =
    c.origine === "fichier"
      ? null
      : c.origine === "maquette"
        ? "maquette"
        : c.origine === "appli"
          ? "saisi dans l’appli"
          : c.origine === "voulu"
            ? "sans code (voulu)"
            : null;
  return (
    <span className={`ev-celcat${c.origine === "manquant" ? " ev-celcat--manquant" : ""}`} title={titre}>
      {/* La cellule même de l'onglet « Codes Celcat » : verrou des codes
          connus, saisie réservée aux administrateurs. */}
      <CelluleCode
        ligne={c}
        famille="enseignants"
        suggestions={[]}
        onEnregistrer={async (ligne, code) => {
          const r = await definirCodeCelcat("enseignants", ligne.cle, code);
          void onEnregistre(`${l.nom_complet} : code Celcat ${r.code} enregistré.`);
        }}
      />
      {origine && <span className="ev-origine">{origine}</span>}
      {c.origine === "manquant" && (
        <button
          type="button"
          className="linklike ev-lien-codes"
          onClick={() => setRoute({ vue: "reference", onglet: "codes-celcat", famille: "enseignants", cle: l.code })}
        >
          Codes Celcat →
        </button>
      )}
    </span>
  );
}
