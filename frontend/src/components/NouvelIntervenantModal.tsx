/**
 * « Nouvel intervenant » (30/09/2026, demande d'un administrateur : « ajoute
 * la possibilité de créer un intervenant »). Jusque-là : deux fichiers de
 * configuration et un déploiement.
 *
 * Six champs — nom, code, code Celcat, mail, téléphone et type (ces deux
 * derniers depuis le 01/10/2026, onglet « Enseignants & vacataires ») —
 * validés en direct : le
 * format ici, le reste par le serveur (`POST /reference/enseignants/verifier`,
 * la même règle que la création). Les garde-fous du serveur s'affichent tels
 * quels, avec un lien vers la personne existante :
 * - code déjà pris par un enseignant connu : refus ;
 * - code présent dans Celcat pour une autre personne : « Créer quand même » ;
 * - code Celcat déjà porté par un autre enseignant : à corriger (doublon) ;
 * - nom qui ressemble à quelqu'un de connu : « Créer quand même ».
 *
 * Réservé aux administrateurs, comme le reste des données Celcat : un
 * intervenant, c'est aussi un identifiant Celcat, donc une paie.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import {
  avertissementsDeLErreur,
  creerIntervenant,
  verifierIntervenant,
  type AvertissementIntervenant,
  type IntervenantCree,
  type VerificationIntervenant,
} from "../api/client";

import { validerTelephone } from "../utils/identiteEnseignant";

import "./NouvelIntervenantModal.css";

interface Props {
  onCreated: (cree: IntervenantCree) => void;
  onCancel: () => void;
  /** Ouvre la fiche d'un enseignant existant (lien « Voir sa fiche »). */
  onVoirFiche: (code: string) => void;
}

type Champ = "nom" | "code" | "code_celcat" | "email" | "telephone" | "type";

/** Code tel que le serveur le rangera : sans espace, sans accent, en majuscules. */
export function normaliserCode(brut: string): string {
  return brut
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/\s+/g, "")
    .toUpperCase();
}

/** Les erreurs de FORME, sans attendre le serveur. */
export function erreursDeSaisie(s: {
  nom: string;
  code: string;
  codeCelcat: string;
  email: string;
  telephone?: string;
}): Partial<Record<Champ, string>> {
  const e: Partial<Record<Champ, string>> = {};
  const nom = s.nom.trim().replace(/\s+/g, " ");
  if (nom.length < 3 || !/\p{L}/u.test(nom)) e.nom = "Le nom complet est obligatoire (« Prénom Nom »).";
  const code = normaliserCode(s.code);
  if (!code) e.code = "Le code est obligatoire : 2 à 4 lettres.";
  else if (!/^[A-Z]{2,4}$/.test(code)) e.code = "2 à 4 lettres, sans chiffre ni accent (ex. AGN).";
  const celcat = s.codeCelcat.trim();
  if (celcat && !/^[1-9]\d{0,6}$/.test(celcat)) e.code_celcat = "Un nombre, tel qu’affiché dans Celcat (ex. 38999).";
  const email = s.email.trim();
  if (email && !/^[^@\s<>(),;:"[\]]+@[^@\s<>(),;:"[\]]+\.[^@\s<>(),;:"[\].]{2,}$/.test(email.replace(/^mailto:/i, ""))) {
    e.email = "Adresse mail invalide (forme attendue : prenom.nom@univ-reims.fr).";
  }
  const telephone = (s.telephone ?? "").trim();
  if (telephone) {
    const refus = validerTelephone(telephone);
    if (refus) e.telephone = refus;
  }
  return e;
}

export function NouvelIntervenantModal({ onCreated, onCancel, onVoirFiche }: Props) {
  const [nom, setNom] = useState("");
  const [code, setCode] = useState("");
  const [codeCelcat, setCodeCelcat] = useState("");
  const [email, setEmail] = useState("");
  const [telephone, setTelephone] = useState("");
  const [typeEns, setTypeEns] = useState("");
  const [touches, setTouches] = useState<Partial<Record<Champ, boolean>>>({});
  const [verif, setVerif] = useState<{ cle: string; v: VerificationIntervenant } | null>(null);
  // Avertissements rendus par un refus de création (si la vérification en
  // direct n'était pas encore arrivée) : mêmes données, même affichage.
  const [refus, setRefus] = useState<{ cle: string; avertissements: AvertissementIntervenant[] } | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);
  const numero = useRef(0);

  const saisie = useMemo(
    () => ({
      nom: nom.trim(),
      code: normaliserCode(code),
      code_celcat: codeCelcat.trim(),
      email: email.trim(),
      telephone: telephone.trim(),
      type: typeEns,
    }),
    [nom, code, codeCelcat, email, telephone, typeEns],
  );
  const cle = JSON.stringify(saisie);
  const locales = erreursDeSaisie({ nom, code, codeCelcat, email, telephone });

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  // Vérification serveur, 350 ms après la dernière frappe.
  useEffect(() => {
    if (!saisie.nom && !saisie.code) return;
    const n = ++numero.current;
    const minuteur = window.setTimeout(() => {
      verifierIntervenant(saisie)
        .then((v) => {
          if (n === numero.current) setVerif({ cle, v });
        })
        .catch(() => undefined); // la création dira la même chose
    }, 350);
    return () => window.clearTimeout(minuteur);
  }, [cle, saisie]);

  const v = verif?.cle === cle ? verif.v : null;
  // À jour : la vérification (ou le refus) de CETTE saisie. Sinon, la
  // dernière reste affichée, estompée, le temps que la suivante arrive —
  // mais ne sert ni à bloquer ni à confirmer.
  const aJour = v?.avertissements ?? (refus?.cle === cle ? refus.avertissements : null);
  const avertissements = aJour ?? verif?.v.avertissements ?? [];
  const perime = aJour === null && avertissements.length > 0;
  const bloquants = (aJour ?? []).filter((a) => a.bloquant);
  const erreursServeur = new Map((v?.erreurs ?? []).map((e) => [e.champ, e]));
  const erreurDe = (champ: Champ): { message: string; code_existant: string | null } | null => {
    const locale = locales[champ];
    if (locale) return touches[champ] ? { message: locale, code_existant: null } : null;
    const serveur = erreursServeur.get(champ);
    return serveur ? { message: serveur.message, code_existant: serveur.code_existant } : null;
  };
  const invalide = Object.keys(locales).length > 0 || erreursServeur.size > 0 || bloquants.length > 0;
  const aConfirmer = (aJour ?? []).length > 0 && bloquants.length === 0;

  const toucher = (champ: Champ) => setTouches((t) => ({ ...t, [champ]: true }));

  const creer = async () => {
    setTouches({ nom: true, code: true, code_celcat: true, email: true, telephone: true, type: true });
    if (invalide) return;
    setEnCours(true);
    setErreur(null);
    try {
      // `confirmer` seulement pour des avertissements AFFICHÉS pour cette
      // saisie-là : jamais à l'aveugle.
      const cree = await creerIntervenant({ ...saisie, confirmer: aConfirmer });
      onCreated(cree);
    } catch (e) {
      const liste = avertissementsDeLErreur(e);
      if (liste) {
        setRefus({ cle, avertissements: liste });
      } else {
        setErreur(e instanceof Error ? e.message : "Création impossible.");
      }
    } finally {
      setEnCours(false);
    }
  };

  const lienFiche = (codeExistant: string | null, libelle = "Voir sa fiche") =>
    codeExistant ? (
      <button type="button" className="linklike" onClick={() => onVoirFiche(codeExistant)}>
        {libelle} ({codeExistant})
      </button>
    ) : null;

  const champ = (
    id: Champ,
    libelle: string,
    controle: React.ReactNode,
    aide?: React.ReactNode,
  ) => {
    const err = erreurDe(id);
    return (
      <div className={`nouvint-champ${err ? " is-invalide" : ""}`}>
        <label htmlFor={`nouvint-${id}`}>{libelle}</label>
        {controle}
        {err ? (
          <p className="nouvint-erreur" id={`nouvint-${id}-erreur`} role="alert">
            {err.message} {lienFiche(err.code_existant)}
          </p>
        ) : (
          aide && <p className="nouvint-aide">{aide}</p>
        )}
      </div>
    );
  };
  const decrit = (id: Champ) => (erreurDe(id) ? `nouvint-${id}-erreur` : undefined);

  return (
    <div className="confirmmodal-overlay" role="presentation" onClick={onCancel}>
      <form
        className="panel confirmmodal nouvint"
        role="dialog"
        aria-modal="true"
        aria-labelledby="nouvint-titre"
        noValidate
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          void creer();
        }}
      >
        <h3 id="nouvint-titre">Nouvel intervenant</h3>
        <p className="nouvint-intro">
          Il apparaîtra partout où apparaissent les enseignants — annuaire, « Nouvelle séance », Codes Celcat —, sans
          déploiement. Réservé aux administrateurs, comme les codes Celcat.
        </p>

        <div className="nouvint-grille">
          {champ(
            "nom",
            "Nom complet",
            <input
              id="nouvint-nom"
              type="text"
              value={nom}
              autoFocus
              maxLength={120}
              autoComplete="off"
              placeholder="Prénom Nom"
              aria-invalid={!!erreurDe("nom")}
              aria-describedby={decrit("nom")}
              onChange={(e) => setNom(e.target.value)}
              onBlur={() => toucher("nom")}
            />,
          )}
          {champ(
            "code",
            "Code",
            <input
              id="nouvint-code"
              type="text"
              className="mono"
              value={code}
              maxLength={4}
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              placeholder="ex. AGN"
              aria-invalid={!!erreurDe("code")}
              aria-describedby={decrit("code")}
              onChange={(e) => setCode(normaliserCode(e.target.value))}
              onBlur={() => toucher("code")}
            />,
            v?.suggestion_code && v.suggestion_code !== saisie.code ? (
              <>
                Libre :{" "}
                <button type="button" className="linklike mono" onClick={() => setCode(v.suggestion_code ?? "")}>
                  {v.suggestion_code}
                </button>
              </>
            ) : (
              "2 à 4 lettres, le trigramme du planning."
            ),
          )}
          {champ(
            "code_celcat",
            "Code Celcat (facultatif)",
            <input
              id="nouvint-code_celcat"
              type="text"
              inputMode="numeric"
              className="mono"
              value={codeCelcat}
              maxLength={7}
              autoComplete="off"
              placeholder="ex. 38999"
              aria-invalid={!!erreurDe("code_celcat")}
              aria-describedby={decrit("code_celcat")}
              onChange={(e) => setCodeCelcat(e.target.value.trim())}
              onBlur={() => toucher("code_celcat")}
            />,
            "Sans lui, ses séances attendront avant de partir vers Celcat.",
          )}
          {champ(
            "email",
            "Mail (facultatif)",
            <input
              id="nouvint-email"
              type="email"
              value={email}
              maxLength={254}
              autoComplete="off"
              placeholder="prenom.nom@univ-reims.fr"
              aria-invalid={!!erreurDe("email")}
              aria-describedby={decrit("email")}
              onChange={(e) => setEmail(e.target.value)}
              onBlur={() => toucher("email")}
            />,
            "Pour lui envoyer son lien personnel.",
          )}
          {champ(
            "telephone",
            "Téléphone (facultatif)",
            <input
              id="nouvint-telephone"
              type="tel"
              inputMode="tel"
              value={telephone}
              maxLength={40}
              autoComplete="off"
              placeholder="06 12 34 56 78"
              aria-invalid={!!erreurDe("telephone")}
              aria-describedby={decrit("telephone")}
              onChange={(e) => setTelephone(e.target.value)}
              onBlur={() => toucher("telephone")}
            />,
            "Visible des comptes qui peuvent modifier, jamais sur un lien public.",
          )}
          {champ(
            "type",
            "Type",
            <select
              id="nouvint-type"
              value={typeEns}
              aria-invalid={!!erreurDe("type")}
              aria-describedby={decrit("type")}
              onChange={(e) => setTypeEns(e.target.value)}
            >
              <option value="">À préciser</option>
              <option value="enseignant">Enseignant</option>
              <option value="vacataire">Vacataire</option>
            </select>,
            "Enseignant ou vacataire.",
          )}
        </div>

        <div aria-live="polite">
          {avertissements.length > 0 && (
            <section
              className={`nouvint-avertissements${perime ? " is-perime" : ""}`}
              aria-label="À vérifier avant de créer"
              aria-busy={perime || undefined}
            >
              <h4>
                {perime
                  ? "Vérification en cours…"
                  : bloquants.length
                    ? "À corriger avant de créer"
                    : "À vérifier avant de créer"}
              </h4>
              <ul>
                {avertissements.map((a, i) => (
                  <li key={`${a.type}-${a.code_existant ?? ""}`} className={a.bloquant ? "is-bloquant" : ""}>
                    <strong>{a.titre}</strong>
                    <span>{a.message}</span>
                    <span className="nouvint-liens">
                      {/* Un seul lien par personne, au premier avertissement qui la nomme. */}
                      {a.fiche &&
                        !avertissements.slice(0, i).some((b) => b.fiche && b.code_existant === a.code_existant) &&
                        lienFiche(a.code_existant)}
                      {a.type === "code_celcat_pris" && (
                        <button type="button" className="linklike" onClick={() => setCodeCelcat("")}>
                          Retirer le code Celcat
                        </button>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>

        {erreur && (
          <p className="alerte" role="alert">
            {erreur}
          </p>
        )}

        <div className="confirmmodal-actions">
          <button type="button" className="btn btn--ghost" onClick={onCancel}>
            Annuler
          </button>
          <button type="submit" className="btn btn--primary" disabled={enCours || bloquants.length > 0}>
            {enCours ? "Création…" : aConfirmer ? "Créer quand même" : "Créer"}
          </button>
        </div>
      </form>
    </div>
  );
}
