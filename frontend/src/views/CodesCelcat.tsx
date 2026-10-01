/**
 * Référence → « Codes Celcat » (30/09/2026).
 *
 * Demande du responsable du planning : « un onglet, quelque part où on
 * pouvait renseigner les codes Celcat pour les cours et les salles aussi
 * [...] Que l'utilisateur puisse enregistrer les codes comme ça et ils sont
 * enregistrés pour Celcat. »
 *
 * Jusque-là, un code ne se saisissait que pour ce qui manquait ou bloquait.
 * Ici, TOUT ce que l'appli envoie à Celcat, par famille (sous-onglets Cours,
 * Salles, Enseignants, Groupes) : le code qui partira, son origine (fichier
 * de configuration, saisi dans l'appli, manquant), le nombre de séances.
 *
 * - administrateurs : saisir un code MANQUANT, modifier une saisie (champ en
 *   ligne, Entrée / Échap), « Revenir à manquant », ou marquer « sans code
 *   (voulu) » avec un motif ; les codes relevés dans Celcat sont proposés
 *   sous le champ. Un code CONNU (fichier de configuration, maquette) est
 *   verrouillé : « il faut pouvoir modifier QUE ceux qu'on n'a pas »
 *   (30/09/2026) ;
 * - autres comptes : la même liste, en lecture seule ;
 * - groupes : identifiant INTERNE Celcat, lecture seule pour tous — il se
 *   règle dans `celcat_groupes.yaml` (cf. `api/codes_celcat.py`).
 *
 * Un lien peut viser un sous-onglet et une ligne (`#vue=reference&onglet=
 * codes-celcat&famille=salles&cle=h018`) : « Données à compléter », les
 * blocages de l'écran Celcat y mènent.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Lock } from "lucide-react";

import {
  definirCodeCelcat,
  effacerCodeCelcat,
  fetchCodesCelcat,
  marquerSansCodeCelcat,
  retirerSansCodeCelcat,
  type CodesCelcat as DonneesCodes,
  type FamilleCodeCelcat,
  type LigneCodeCelcat,
} from "../api/client";
import { ChampEnLigne } from "../components/ChampEnLigne";
import { ChampRecherche } from "../components/ChampRecherche";
import { Onglets } from "../components/Onglets";
import { TriColonne, useTri } from "../components/TriColonne";
import { useDroits } from "../contexts/Droits";
import { confirmAsync } from "../utils/confirmDialog";
import { humaniser } from "./ReferenceView";
import "./CodesCelcat.css";

export const FAMILLES_CODES: { id: FamilleCodeCelcat; label: string }[] = [
  { id: "cours", label: "Cours" },
  { id: "salles", label: "Salles" },
  { id: "enseignants", label: "Enseignants" },
  { id: "groupes", label: "Groupes" },
];

export function estFamilleCode(v: unknown): v is FamilleCodeCelcat {
  return FAMILLES_CODES.some((f) => f.id === v);
}

type Filtre = "sans" | "voulu" | "appli" | "tous";

const FILTRES: { id: Filtre; label: string }[] = [
  { id: "sans", label: "Sans code" },
  { id: "voulu", label: "Sans code (voulu)" },
  { id: "appli", label: "Saisis dans l’appli" },
  { id: "tous", label: "Tous" },
];

type CleTri = "cle" | "libelle" | "semestre" | "parcours" | "type" | "capacite" | "nb" | "code" | "origine";

const ORDRE_ORIGINE: Record<LigneCodeCelcat["origine"], number> = {
  manquant: 0,
  appli: 1,
  voulu: 2,
  regle: 3,
  maquette: 4,
  fichier: 5,
};

const VALEURS: Record<CleTri, (l: LigneCodeCelcat) => string | number> = {
  cle: (l) => l.cle,
  libelle: (l) => l.libelle,
  semestre: (l) => l.semestre ?? "",
  parcours: (l) => l.parcours ?? "",
  type: (l) => humaniser(l.type_salle ?? ""),
  capacite: (l) => l.capacite ?? 0,
  nb: (l) => l.nb_seances,
  code: (l) => l.code ?? "",
  origine: (l) => ORDRE_ORIGINE[l.origine],
};

const TRI_INITIAL: Record<FamilleCodeCelcat, CleTri> = {
  cours: "cle",
  salles: "libelle",
  enseignants: "libelle",
  groupes: "cle",
};

const NOM_CHAMP: Record<FamilleCodeCelcat, string> = {
  cours: "Code module Celcat",
  salles: "Nom Celcat",
  enseignants: "Code Celcat",
  groupes: "Identifiant Celcat",
};

function normaliser(t: string): string {
  return t
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
}

function dateCourte(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });
}

function pluriel(n: number, un: string, plusieurs = `${un}s`): string {
  return `${n} ${n > 1 ? plusieurs : un}`;
}

interface CodesCelcatProps {
  /** Sous-onglet demandé par le lien (`famille=`). */
  famille?: string;
  /** Ligne visée par le lien (`cle=`). */
  cle?: string;
  /** Mémorise le sous-onglet dans l'adresse. */
  onFamille?: (famille: FamilleCodeCelcat) => void;
  /** « Nouvel intervenant » (administrateurs, sous-onglet Enseignants). */
  onNouvelIntervenant?: () => void;
}

export function CodesCelcat({ famille: familleRoute, cle: cleRoute, onFamille, onNouvelIntervenant }: CodesCelcatProps) {
  const { apresEnregistrement } = useDroits();
  const [donnees, setDonnees] = useState<DonneesCodes | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [familleLocale, setFamilleLocale] = useState<FamilleCodeCelcat>("cours");
  const famille: FamilleCodeCelcat = estFamilleCode(familleRoute) ? familleRoute : familleLocale;
  const [texte, setTexte] = useState("");
  const [filtre, setFiltre] = useState<Filtre>("tous");
  const [retour, setRetour] = useState("");

  const recharger = useCallback(async () => {
    try {
      setDonnees(await fetchCodesCelcat());
      setErreur(null);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Liste indisponible.");
    }
  }, []);

  useEffect(() => {
    void recharger();
  }, [recharger]);

  // Un lien vers une ligne : on la montre, quels que soient les filtres.
  useEffect(() => {
    if (!cleRoute) return;
    setTexte("");
    setFiltre("tous");
  }, [cleRoute, familleRoute]);

  const choisirFamille = (f: FamilleCodeCelcat) => {
    setFamilleLocale(f);
    setTexte("");
    setRetour("");
    onFamille?.(f);
  };

  const bloc = donnees?.familles[famille];
  const lignes = useMemo(() => bloc?.lignes ?? [], [bloc]);
  const filtrees = useMemo(() => {
    const q = normaliser(texte.trim());
    return lignes.filter((l) => {
      if (filtre === "sans" && l.origine !== "manquant") return false;
      if (filtre === "voulu" && l.origine !== "voulu") return false;
      if (filtre === "appli" && l.origine !== "appli") return false;
      if (!q) return true;
      const botte = `${l.cle} ${l.libelle} ${l.code ?? ""} ${l.semestre ?? ""} ${l.parcours ?? ""} ${humaniser(l.type_salle ?? "")}`;
      return q.split(/\s+/).every((mot) => normaliser(botte).includes(mot));
    });
  }, [lignes, texte, filtre]);
  const { triees, tri, trierPar } = useTri<LigneCodeCelcat, CleTri>(filtrees, VALEURS, {
    cle: TRI_INITIAL[famille],
    sens: 1,
  });

  // Faire défiler jusqu'à la ligne visée, une fois la liste arrivée.
  const corps = useRef<HTMLTableSectionElement>(null);
  useEffect(() => {
    if (!cleRoute || !donnees) return;
    const ligne = Array.from(corps.current?.querySelectorAll<HTMLElement>("tr[data-cle]") ?? []).find(
      (tr) => tr.dataset.cle?.toUpperCase() === cleRoute.toUpperCase(),
    );
    if (!ligne) return;
    // La carte défile d'elle-même sur poste de travail (`--haute`) : ne
    // faire défiler QU'ELLE — `scrollIntoView` décalait aussi la coque de
    // l'application. Au téléphone, c'est la page qui défile.
    const carte = ligne.closest<HTMLElement>(".carte-tableau");
    if (carte && carte.scrollHeight > carte.clientHeight + 1) {
      const ecart = ligne.getBoundingClientRect().top - carte.getBoundingClientRect().top;
      carte.scrollTop += ecart - carte.clientHeight / 2 + ligne.clientHeight / 2;
    } else {
      ligne.scrollIntoView?.({ block: "center" });
    }
  }, [cleRoute, donnees, famille]);

  const apres = async (message: string) => {
    setRetour(message);
    await recharger();
    apresEnregistrement();
  };

  const enregistrer = async (l: LigneCodeCelcat, code: string) => {
    const r = await definirCodeCelcat(famille, l.cle, code);
    await apres(`${l.libelle} : ${r.code} enregistré pour Celcat.`);
  };

  const marquerSansCode = async (l: LigneCodeCelcat, motif: string) => {
    await marquerSansCodeCelcat(famille, l.cle, motif);
    await apres(`${l.libelle} : marqué « sans code (voulu) », rien ne part vers Celcat.`);
  };

  const confirmerPuis = async (message: string, titre: string, action: () => Promise<string>) => {
    const ok = await confirmAsync(message, { title: titre, confirmLabel: titre.replace(/ \?$/, ""), cancelLabel: "Annuler" });
    if (!ok) return;
    try {
      await apres(await action());
    } catch (e) {
      setRetour("");
      setErreur(e instanceof Error ? e.message : "Action impossible.");
    }
  };

  const revenir = (l: LigneCodeCelcat) =>
    confirmerPuis(
      l.code_connu
        ? `${l.libelle} repartira vers Celcat avec le code connu : ${l.code_connu} (au lieu de ${l.code}).`
        : `${l.libelle} n’aura plus de code : ses séances ne pourront plus partir vers Celcat tant qu’il n’est pas ressaisi.`,
      l.code_connu ? "Revenir au code connu ?" : "Revenir à manquant ?",
      async () => {
        const r = await effacerCodeCelcat(famille, l.cle);
        return r.code ? `${l.libelle} : code connu rétabli (${r.code}).` : `${l.libelle} : saisie retirée, de nouveau manquant.`;
      },
    );

  const retirerSansCode = (l: LigneCodeCelcat) =>
    confirmerPuis(
      `${l.libelle} redeviendra « manquant » : il faudra lui saisir un code pour que ses séances partent vers Celcat.`,
      "Retirer « sans code (voulu) » ?",
      async () => {
        await retirerSansCodeCelcat(famille, l.cle);
        return `${l.libelle} : de nouveau manquant.`;
      },
    );

  if (!donnees) {
    return erreur ? (
      <p className="alerte" role="alert">
        Codes Celcat indisponibles : {erreur}
      </p>
    ) : (
      <p className="page-note" aria-busy="true">
        Chargement des codes Celcat…
      </p>
    );
  }

  const admin = donnees.admin;
  const colAction = admin && famille !== "groupes";
  const col = (cle: CleTri, libelle: string, num = false, className?: string) => (
    <TriColonne cle={cle} tri={tri} onTrier={trierPar} num={num} className={className}>
      {libelle}
    </TriColonne>
  );
  const compte = (f: Filtre) =>
    f === "sans"
      ? (bloc?.sans_code ?? 0)
      : f === "voulu"
        ? (bloc?.voulus ?? 0)
        : f === "appli"
          ? (bloc?.saisis ?? 0)
          : (bloc?.total ?? 0);

  return (
    <div className="codes-celcat">
      <p className="page-note">
        Le code qui part vers Celcat pour chaque cours, salle, enseignant et groupe du planning, et d’où il vient.{" "}
        Les codes connus (fichier de configuration, maquette) sont verrouillés.{" "}
        {admin
          ? "Réservé aux administrateurs : un code manquant saisi ici part au prochain envoi vers Celcat, sans déploiement ; « sans code (voulu) » dit qu’il n’y en aura pas."
          : "Lecture seule : seuls les administrateurs saisissent un code Celcat."}
      </p>

      <Onglets
        onglets={FAMILLES_CODES.map((f) => ({
          id: f.id,
          label: f.label,
          nb: donnees.familles[f.id]?.sans_code || undefined,
          titreNb: "Sans code Celcat",
        }))}
        actif={famille}
        onChoisir={choisirFamille}
        label="Familles de codes Celcat"
        prefixeId="codes-celcat-famille"
        controle="codes-celcat-panneau"
      />

      <div id="codes-celcat-panneau" role="tabpanel" aria-labelledby={`codes-celcat-famille-${famille}`} className="ref-panneau">
        <div className="page-outils ref-barre">
          <ChampRecherche
            className="ref-recherche"
            placeholder="Filtrer : code, nom, code Celcat…"
            libelle={`Filtrer les ${FAMILLES_CODES.find((f) => f.id === famille)?.label.toLowerCase()}`}
            valeur={texte}
            onChange={setTexte}
          />
          <div className="pastilles" role="group" aria-label="Afficher">
            {FILTRES.map((f) => (
              <button
                key={f.id}
                type="button"
                className="pastille"
                aria-pressed={filtre === f.id}
                onClick={() => setFiltre(f.id)}
              >
                {f.label}
                <span className="pastille-nb">{compte(f.id)}</span>
              </button>
            ))}
          </div>
          <span className="ref-resume">
            {filtrees.length === lignes.length
              ? pluriel(lignes.length, "ligne")
              : `${filtrees.length} sur ${pluriel(lignes.length, "ligne")}`}
            {bloc && bloc.sans_code_bloquants > 0 && (
              <>
                {" · "}
                <span className="codes-celcat-bloquants">
                  {pluriel(bloc.sans_code_bloquants, "bloque", "bloquent")} Celcat
                </span>
              </>
            )}
          </span>
          {admin && famille === "enseignants" && onNouvelIntervenant && (
            <span className="page-outils-actions">
              <button
                type="button"
                className="btn btn--sm"
                onClick={onNouvelIntervenant}
                title="Un enseignant que la configuration ne connaît pas encore (administrateurs)"
              >
                Nouvel intervenant
              </button>
            </span>
          )}
        </div>

        {bloc && famille !== "groupes" && <p className="ref-aide">{bloc.aide}</p>}
        {famille === "groupes" && (
          <p className="ref-aide codes-celcat-groupes">
            Lecture seule pour tous : Celcat désigne un groupe par un identifiant interne, qui ne se lit pas dans
            Celcat. Il se règle dans <span className="mono">data/config/celcat_groupes.yaml</span> (relevé dans
            Celcat, puis déploiement).
          </p>
        )}

        <p className="page-retour codes-celcat-retour" role="status" aria-live="polite">
          {retour}
        </p>
        {erreur && (
          <p className="alerte" role="alert">
            {erreur}
          </p>
        )}

        <div className="panel carte-tableau carte-tableau--haute ref-tableau">
          <table className="ref codes-celcat-table">
            <thead>
              <tr>
                {famille === "cours" && (
                  <>
                    {col("cle", "Cours")}
                    {col("libelle", "Intitulé", false, "ref-optionnel")}
                    {col("semestre", "Sem.", false, "ref-optionnel")}
                    {col("parcours", "Parcours", false, "ref-secondaire")}
                  </>
                )}
                {famille === "salles" && (
                  <>
                    {col("libelle", "Salle")}
                    {col("type", "Type", false, "ref-optionnel")}
                    {col("capacite", "Places", true, "ref-optionnel")}
                  </>
                )}
                {famille === "enseignants" && col("libelle", "Enseignant")}
                {famille === "groupes" && col("cle", "Groupe Celcat")}
                {col("nb", "Séances", true)}
                {col("code", NOM_CHAMP[famille])}
                {col("origine", "Origine")}
                {colAction && <th className="codes-celcat-action">Action</th>}
              </tr>
            </thead>
            <tbody ref={corps}>
              {triees.map((l) => (
                <tr
                  key={l.cle}
                  data-cle={l.cle}
                  className={cleRoute && cleRoute.toUpperCase() === l.cle.toUpperCase() ? "codes-celcat-visee" : undefined}
                >
                  {famille === "cours" && (
                    <>
                      <td className="mono">{l.cle}</td>
                      <td className="ref-optionnel">{l.libelle}</td>
                      <td className="ref-optionnel">{l.semestre}</td>
                      <td className="ref-doux ref-parcours ref-secondaire">{l.parcours}</td>
                    </>
                  )}
                  {famille === "salles" && (
                    <>
                      <td>
                        {l.libelle}
                        {l.libelle.toLowerCase() !== l.cle.toLowerCase() && <span className="ref-code mono"> {l.cle}</span>}
                        {l.note && <span className="codes-celcat-note">{l.note}</span>}
                      </td>
                      <td className="ref-optionnel">{humaniser(l.type_salle ?? "")}</td>
                      <td className="num ref-optionnel">{l.capacite}</td>
                    </>
                  )}
                  {famille === "enseignants" && (
                    <td>
                      {l.libelle}
                      {l.libelle !== l.cle && <span className="ref-code mono"> {l.cle}</span>}
                    </td>
                  )}
                  {famille === "groupes" && <td>{l.libelle}</td>}
                  <td className="num">{l.nb_seances || <span className="ref-zero">0</span>}</td>
                  <td className="codes-celcat-code">
                    <CelluleCode ligne={l} famille={famille} suggestions={bloc?.suggestions ?? []} onEnregistrer={enregistrer} />
                  </td>
                  <td>
                    <Origine ligne={l} admin={admin} />
                  </td>
                  {colAction && (
                    <td className="codes-celcat-action">
                      <Actions
                        ligne={l}
                        famille={famille}
                        onRevenir={() => void revenir(l)}
                        onMarquer={(motif) => marquerSansCode(l, motif)}
                        onRetirerSansCode={() => void retirerSansCode(l)}
                      />
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {triees.length === 0 && (
            <p className="ref-vide">
              {filtre === "sans" && !texte
                ? "Rien ne manque dans cette famille : tout a un code Celcat, ou « sans code (voulu) »."
                : "Aucune ligne ne correspond."}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export function CelluleCode({
  ligne: l,
  famille,
  suggestions,
  onEnregistrer,
}: {
  ligne: LigneCodeCelcat;
  famille: FamilleCodeCelcat;
  suggestions: string[];
  onEnregistrer: (l: LigneCodeCelcat, code: string) => Promise<void>;
}) {
  const libelleChamp = `${NOM_CHAMP[famille]} de ${l.libelle !== l.cle ? `${l.libelle} (${l.cle})` : l.cle}`;
  // Code de la maquette NON repris par prudence : proposé en premier, et
  // la raison dite — il reste à confirmer puis saisir.
  const proposees = !l.code && l.code_maquette ? [l.code_maquette, ...suggestions.filter((s) => s !== l.code_maquette)] : suggestions;
  const complements = (
    <>
      {famille === "cours" && !l.code && l.code_maquette && (
        <span className="codes-celcat-suggestion">
          maquette : <span className="mono">{l.code_maquette}</span>
        </span>
      )}
      {famille === "cours" && l.note && <span className="codes-celcat-note">{l.note}</span>}
      {l.alerte && <span className="codes-celcat-alerte">{l.alerte}</span>}
      {l.avertissement && <span className="codes-celcat-alerte">{l.avertissement}</span>}
    </>
  );
  if (l.modifiable) {
    return (
      <>
        <ChampEnLigne
          mode={l.code ? "modifier" : "ajouter"}
          libelleBouton="Saisir"
          libelleChamp={libelleChamp}
          valeurInitiale={l.code ?? ""}
          valeurAffichee={l.code ? <code className="mono codes-celcat-valeur">{l.code}</code> : null}
          placeholder={famille === "salles" ? "H.104" : famille === "enseignants" ? "38999" : "TSBZ1M01"}
          taille={14}
          suggestions={proposees}
          onEnregistrer={(v) => onEnregistrer(l, v)}
        />
        {complements}
      </>
    );
  }
  if (l.code) {
    // Code connu (fichier, maquette) ou saisie ancienne : verrouillé.
    const verrou = l.code_connu !== null;
    return (
      <>
        <span className="codes-celcat-verrouille" title={verrou ? "Code connu : il ne se modifie pas dans l’appli" : undefined}>
          <code className="mono codes-celcat-valeur">{l.code}</code>
          {verrou && <Lock size={12} aria-label="verrouillé" className="codes-celcat-cadenas" />}
        </span>
        {complements}
      </>
    );
  }
  if (l.origine === "voulu") return <span className="ref-zero">—</span>;
  if (l.origine === "regle") {
    // « Envoi sans module » : pas de code, et ce n'est pas un manque — la
    // note dit ce qui part (catégorie, remarque, département).
    return (
      <>
        <span className="ref-doux">sans module</span>
        {complements}
      </>
    );
  }
  return (
    <>
      <span className={`pill dot ${l.nb_seances > 0 ? "bad" : "warn"}`}>manquant</span>
      {complements}
    </>
  );
}

function Actions({
  ligne: l,
  famille,
  onRevenir,
  onMarquer,
  onRetirerSansCode,
}: {
  ligne: LigneCodeCelcat;
  famille: FamilleCodeCelcat;
  onRevenir: () => void;
  onMarquer: (motif: string) => Promise<void>;
  onRetirerSansCode: () => void;
}) {
  return (
    <span className="codes-celcat-actions">
      {l.peut_revenir && (
        <button type="button" className="btn btn--ghost btn--sm" onClick={onRevenir}>
          {l.code_connu ? "Revenir au code connu" : "Revenir à manquant"}
        </button>
      )}
      {l.peut_marquer_sans_code && (
        <ChampEnLigne
          libelleBouton="Sans code (voulu)…"
          classeBouton="btn btn--ghost btn--sm"
          libelleChamp={`Motif « sans code (voulu) » de ${l.libelle !== l.cle ? `${l.libelle} (${l.cle})` : l.cle}`}
          placeholder="Pourquoi pas de code ? (obligatoire)"
          taille={24}
          libelleEnregistrer="Marquer"
          valider={(v) => (v.trim().length < 3 ? "Le motif est obligatoire (quelques mots)." : null)}
          onEnregistrer={onMarquer}
        />
      )}
      {l.peut_retirer_sans_code && (
        <button type="button" className="btn btn--ghost btn--sm" onClick={onRetirerSansCode}>
          Retirer « sans code »
        </button>
      )}
      {famille !== "groupes" && l.origine === "voulu" && !l.peut_retirer_sans_code && (
        <span className="codes-celcat-qui">se retire dans celcat.yaml</span>
      )}
      {l.origine === "regle" && <span className="codes-celcat-qui">se règle dans celcat.yaml</span>}
    </span>
  );
}

function Origine({ ligne: l, admin }: { ligne: LigneCodeCelcat; admin: boolean }) {
  if (l.origine === "fichier") return <span className="codes-celcat-origine">Fichier de config</span>;
  if (l.origine === "maquette") {
    const corrige = l.origine_detail && l.origine_detail !== "maquette";
    return (
      <span className="codes-celcat-origine">
        Maquette
        {corrige && (
          <span className="codes-celcat-qui">
            corrigé M→C{l.code_maquette ? ` (maquette : ${l.code_maquette})` : ""}
          </span>
        )}
      </span>
    );
  }
  if (l.origine === "voulu") {
    return (
      <span className="codes-celcat-origine">
        <span className="pill dot">sans code (voulu)</span>
        <span className="codes-celcat-motif">{l.motif_sans_code}</span>
        <span className="codes-celcat-qui">
          {l.origine_detail === "celcat.yaml"
            ? "décidé dans celcat.yaml"
            : `saisi dans l’appli${admin && l.saisi_par ? ` par ${l.saisi_par}` : ""}${l.saisi_le ? ` le ${dateCourte(l.saisi_le)}` : ""}`}
        </span>
      </span>
    );
  }
  if (l.origine === "regle") {
    return (
      <span className="codes-celcat-origine">
        <span className={`pill dot ${l.origine_detail?.includes("inactive") ? "warn" : "good"}`}>
          {l.origine_detail ?? "envoi sans module (règle)"}
        </span>
        {l.motif_sans_code && <span className="codes-celcat-motif">{l.motif_sans_code}</span>}
        <span className="codes-celcat-qui">décidé dans celcat.yaml</span>
      </span>
    );
  }
  if (l.origine === "manquant") {
    return l.nb_seances > 0 ? (
      <span className="pill dot bad">manquant — bloque Celcat</span>
    ) : (
      <span className="pill dot warn">manquant</span>
    );
  }
  const quand = dateCourte(l.saisi_le);
  return (
    <span className="codes-celcat-origine">
      <span className="pill dot good">saisi dans l’appli</span>
      <span className="codes-celcat-qui">
        {admin && l.saisi_par ? `par ${l.saisi_par}` : ""}
        {quand ? ` le ${quand}` : ""}
        {l.code_connu ? ` · code connu : ${l.code_connu}` : ""}
      </span>
    </span>
  );
}
