/**
 * Une donnée manquante (`GET /reference/manques`) et le moyen de la
 * compléter — le même rendu dans « À traiter » (section « Données à
 * compléter »), sur la fiche d'un enseignant et sur celle d'une salle.
 *
 * Selon le champ et le rôle du compte :
 * - un champ en ligne (`ChampEnLigne`) qui appelle la route de la famille ;
 * - un lien vers l'écran où l'on complète (Vue Promo pour une salle de
 *   séance, écran Celcat pour une correspondance, réservé aux admins) ;
 * - ou seulement le manque et où il se complète, en lecture seule.
 */

import { ArrowRight } from "lucide-react";

import {
  completerContactEnseignant,
  completerCours,
  completerEnseignant,
  completerSalle,
  type GraviteManque,
  type Manque,
} from "../api/client";
import { peutCompleterManque, useDroits, useManques } from "../contexts/Droits";
import type { Route } from "../hooks/useHashRoute";
import { libelleTypeSalle } from "../utils/annuaires";
import { ChampEnLigne, validerEmail, type OptionChamp } from "./ChampEnLigne";

import "./CompleterManque.css";

/** Types proposés pour une salle ajoutée à la main — ni « réservée » ni
 *  « salles réunies », qui ne se choisissent pas (cf. `api/reference.py`). */
const TYPES_CHOISISSABLES = [
  "standard",
  "tp_standard",
  "td_design",
  "tp_mac",
  "studio_av",
  "tp_anglais",
  "tp_vr_reseaux",
  "evaluation",
  "amphi",
];

const OPTIONS_TYPE: OptionChamp[] = TYPES_CHOISISSABLES.map((t) => ({ value: t, label: libelleTypeSalle(t) }));

export const LIBELLES_GRAVITE: Record<GraviteManque, { court: string; ton: "bad" | "warn" | "" }> = {
  bloque_celcat: { court: "bloque Celcat", ton: "bad" },
  bloque_envoi_liens: { court: "bloque l'envoi du lien", ton: "warn" },
  cosmetique: { court: "affichage", ton: "" },
};

export function PastilleGravite({ gravite }: { gravite: GraviteManque }) {
  const g = LIBELLES_GRAVITE[gravite];
  return <span className={`pill dot${g.ton ? ` ${g.ton}` : ""}`}>{g.court}</span>;
}

async function enregistrer(m: Manque, valeur: string): Promise<unknown> {
  switch (`${m.famille}:${m.champ}`) {
    case "enseignant:email":
      return completerContactEnseignant(m.cle, valeur);
    case "enseignant:nom":
      return completerEnseignant(m.cle, { nom: valeur });
    case "enseignant:code_celcat":
      return completerEnseignant(m.cle, { code_celcat: valeur });
    case "salle:code_celcat":
      return completerSalle(m.cle, { code_celcat: valeur });
    case "salle:type":
      return completerSalle(m.cle, { type: valeur });
    case "salle:capacite":
      return completerSalle(m.cle, { capacite: Number(valeur) });
    case "cours:intitule":
      return completerCours(m.cle, valeur);
    default:
      throw new Error("Cette donnée ne se complète pas depuis l'appli.");
  }
}

/** Réglages du champ en ligne par champ ; `null` = pas de saisie en ligne. */
function reglages(m: Manque): {
  type?: "email" | "text" | "number";
  options?: OptionChamp[];
  placeholder?: string;
  valider?: (v: string) => string | null;
  taille?: number;
} | null {
  switch (`${m.famille}:${m.champ}`) {
    case "enseignant:email":
      return { type: "email", placeholder: "prenom.nom@univ-reims.fr", valider: validerEmail };
    case "enseignant:nom":
      return { placeholder: "Prénom Nom", valider: (v) => (v.trim().length < 2 ? "Saisissez le prénom et le nom." : null) };
    case "enseignant:code_celcat":
      return { placeholder: "Code Celcat (ex. 16041)", taille: 14 };
    case "salle:code_celcat":
      return { placeholder: "Nom dans Celcat (ex. H.104)", taille: 16 };
    case "salle:type":
      return { options: OPTIONS_TYPE };
    case "salle:capacite":
      return {
        type: "number",
        placeholder: "Places",
        valider: (v) => (/^\d+$/.test(v) && Number(v) >= 1 && Number(v) <= 1000 ? null : "Entre 1 et 1000 places."),
      };
    case "cours:intitule":
      return { placeholder: "Intitulé de la matière" };
    default:
      return null;
  }
}

/** Nom accessible du champ : « Adresse mail de Kyllian Bresson ». */
function libelleAcces(m: Manque): string {
  return `${m.champ_libelle} de ${m.libelle}`;
}

/**
 * Les manques d'UNE entité, en tête de sa fiche (enseignant, salle) — ce
 * que le bandeau d'identité ne montre pas déjà (`exclure`). Rien du tout
 * quand rien ne manque, ou pour un lien public.
 */
export function ManquesDeLaFiche({
  famille,
  cle,
  exclure = [],
  setRoute,
}: {
  famille: Manque["famille"];
  cle: string;
  exclure?: Manque["champ"][];
  setRoute?: (patch: Partial<Route>) => void;
}) {
  const tous = useManques();
  const liste = (tous ?? []).filter((m) => m.famille === famille && m.cle === cle && !exclure.includes(m.champ));
  if (liste.length === 0) return null;
  return (
    <section className="manques-fiche" aria-label="Données à compléter">
      <h3 className="manques-fiche-titre">À compléter</h3>
      <ul className="manques-fiche-liste">
        {liste.map((m) => (
          <li key={m.id}>
            <span className="manques-fiche-champ">{m.champ_libelle}</span>
            <PastilleGravite gravite={m.gravite} />
            <CompleterManque manque={m} setRoute={setRoute} />
          </li>
        ))}
      </ul>
    </section>
  );
}

interface CompleterManqueProps {
  manque: Manque;
  setRoute?: (patch: Partial<Route>) => void;
}

/** Le moyen de compléter UN manque, selon le rôle du compte. */
export function CompleterManque({ manque: m, setRoute }: CompleterManqueProps) {
  const { role, estAdmin, apresEnregistrement } = useDroits();
  const celcat = m.champ === "code_celcat" || m.champ === "id_celcat";
  const lienCelcat =
    celcat && estAdmin && setRoute ? (
      <button type="button" className="btn btn--ghost btn--sm" onClick={() => setRoute({ vue: "celcat" })}>
        Écran Celcat <ArrowRight size={13} aria-hidden="true" />
      </button>
    ) : null;

  if (m.famille === "seance") {
    return setRoute && role ? (
      <button type="button" className="btn btn--ghost btn--sm" onClick={() => setRoute(m.ecran as Partial<Route>)}>
        Choisir en Vue Promo <ArrowRight size={13} aria-hidden="true" />
      </button>
    ) : null;
  }

  const r = reglages(m);
  if (r && peutCompleterManque(role, m)) {
    return (
      <span className="completer-manque">
        <ChampEnLigne
          libelleBouton="Ajouter"
          libelleChamp={libelleAcces(m)}
          {...r}
          onEnregistrer={async (v) => {
            await enregistrer(m, v);
            apresEnregistrement();
          }}
        />
        {lienCelcat}
      </span>
    );
  }
  if (!role) return null;
  // Pas complétable par ce compte : on dit par qui, ou où.
  const note =
    m.role_requis === "admin"
      ? "Réservé aux administrateurs."
      : m.role_requis === null
        ? m.ou_completer
        : null;
  return (
    <span className="completer-manque">
      {note && <span className="completer-manque-note">{note}</span>}
      {lienCelcat}
    </span>
  );
}
