/**
 * Ce que l'écran Celcat DIT de l'état des choses — calculé ici, affiché ailleurs.
 *
 * Critique design du 16/09/2026 : l'écran avait les mots pour alerter, mais
 * tout se valait visuellement. « Tout concorde » était gris, « relevé
 * périmé » s'affichait en noir (la classe `.bad` n'existait pas), les trois
 * verdicts du tableau portaient la même pastille rouge, et la seule couleur
 * forte de la page était le rouge de « ÉCRITURE ON » — l'état NORMAL.
 *
 * Règle retenue avec l'utilisateur : CALME QUAND ÇA VA. Le vert discret dit
 * « rien à faire », l'ambre dit « à regarder », le rouge est réservé aux
 * pannes et à l'irréversible. Un état sain peint en rouge apprend à ignorer
 * le rouge, et c'est ensuite la vraie panne qu'on ne voit plus.
 *
 * Tout est PUR : aucun appel réseau, aucun composant. Les décisions qui
 * gouvernent ce que l'administrateur croit de Celcat se testent sans DOM.
 */
import type { CelcatComparaison, CelcatEtat, CelcatFile, CelcatInstantane, LigneComparaison } from "../api/client";

/** Le ton d'un statut. Trois niveaux et pas davantage : au-delà, on ne sait
 * plus lequel regarder d'abord. */
export type Ton = "ok" | "attention" | "panne";

/** Classe de pastille (`.pill`) pour un ton — les jetons existants, rien de neuf. */
export const PILULE: Record<Ton, string> = { ok: "good", attention: "warn", panne: "bad" };

export function pluriel(n: number, singulier: string, pluriel?: string): string {
  return `${n} ${n > 1 ? (pluriel ?? `${singulier}s`) : singulier}`;
}

/** « 16/09 à 08:42 » — l'ISO brut (« 2026-09-16T08:42:10+02:00 ») se lisait
 * en comptant les tirets. Rend la chaîne d'origine si elle est illisible
 * plutôt qu'un « Invalid Date » qui ferait croire à une panne. */
export function dateLisible(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const deux = (n: number) => String(n).padStart(2, "0");
  return `${deux(d.getDate())}/${deux(d.getMonth() + 1)} à ${deux(d.getHours())}:${deux(d.getMinutes())}`;
}

/** « il y a 3 min », à partir d'un âge en secondes. Une seule version pour
 * tout l'écran : il en existait deux, qui ne rendaient pas le même texte. */
export function ageLisible(secondes: number | null | undefined): string {
  if (secondes === null || secondes === undefined || Number.isNaN(secondes)) return "";
  if (secondes < 60) return "il y a moins d’une minute";
  const minutes = Math.floor(secondes / 60);
  if (minutes < 60) return `il y a ${minutes} min`;
  const heures = Math.floor(minutes / 60);
  if (heures < 24) {
    const reste = minutes % 60;
    return reste ? `il y a ${heures} h ${reste} min` : `il y a ${heures} h`;
  }
  return `il y a ${pluriel(Math.floor(heures / 24), "jour")}`;
}

// ── Statut du système : écriture, worker, relevé ────────────────────────────

export interface Signal {
  cle: "ecriture" | "worker" | "releve";
  libelle: string;
  /** Le mot de la pastille — jamais la couleur seule (WCAG 1.4.1). */
  etat: string;
  ton: Ton;
  /** Ce que ça implique, en une phrase. */
  detail: string;
}

export function signauxSysteme(
  etat: CelcatEtat,
  instantane: CelcatInstantane | null,
  file: CelcatFile | null,
): Signal[] {
  const ecriture: Signal = etat.saisie_active
    ? {
        cle: "ecriture",
        libelle: "Écriture dans Celcat",
        etat: "active",
        ton: "ok",
        detail: "Chaque modification du planning part dans Celcat.",
      }
    : {
        cle: "ecriture",
        libelle: "Écriture dans Celcat",
        etat: "coupée",
        ton: "panne",
        detail: "Rien ne part dans Celcat tant qu’elle n’est pas réactivée.",
      };

  let worker: Signal;
  if (etat.worker_actif === false) {
    worker = {
      cle: "worker",
      libelle: "Worker",
      etat: "en pause",
      ton: "attention",
      detail: "Le VPN est libre ; les corrections attendent sa reprise.",
    };
  } else if (!etat.worker_ok) {
    worker = {
      cle: "worker",
      libelle: "Worker",
      etat: "muet",
      ton: "panne",
      detail: file?.passe_le
        ? `Aucun passage depuis le ${dateLisible(file.passe_le)}.`
        : "Aucun passage récent.",
    };
  } else {
    worker = {
      cle: "worker",
      libelle: "Worker",
      etat: "actif",
      ton: "ok",
      detail: file?.passe_le
        ? `Dernier passage ${ageLisible(file.age_secondes)}.`
        : "Pas encore passé depuis le démarrage.",
    };
  }

  let releve: Signal;
  if (!instantane || !instantane.releve_le) {
    releve = {
      cle: "releve",
      libelle: "Relevé de Celcat",
      etat: "aucun",
      ton: "attention",
      detail: "Celcat n’a pas encore été relu : rien à comparer.",
    };
  } else if (instantane.erreur) {
    releve = {
      cle: "releve",
      libelle: "Relevé de Celcat",
      etat: "en échec",
      ton: "panne",
      detail: instantane.erreur,
    };
  } else if (instantane.perime) {
    releve = {
      cle: "releve",
      libelle: "Relevé de Celcat",
      etat: "périmé",
      ton: "attention",
      detail: `Pris ${ageLisible(instantane.age_secondes)} : trop ancien pour corriger.`,
    };
  } else {
    releve = {
      cle: "releve",
      libelle: "Relevé de Celcat",
      etat: "à jour",
      ton: "ok",
      detail: `Pris ${ageLisible(instantane.age_secondes)}.`,
    };
  }

  return [ecriture, worker, releve];
}

// ── Verdict d'une semaine ────────────────────────────────────────────────────

/** Mot et ton de chaque verdict de ligne. Trois pastilles DISTINCTES là où
 * les trois écarts partageaient le même rouge : « à modifier » se rattrape,
 * « en trop » mène à une suppression. */
export const STATUT_LIGNE: Record<LigneComparaison["statut"], { mot: string; ton: Ton | null }> = {
  ecart: { mot: "À modifier", ton: "attention" },
  absente_celcat: { mot: "À créer", ton: "attention" },
  en_trop_celcat: { mot: "En trop", ton: "panne" },
  identique: { mot: "Identique", ton: "ok" },
  hors_celcat: { mot: "Hors Celcat", ton: null },
};

export interface Verdict {
  ton: Ton;
  titre: string;
  detail: string;
  aModifier: number;
  aCreer: number;
  enTrop: number;
  identiques: number;
  horsCelcat: number;
  /** Peut-on agir dessus ? Faux sans relevé exploitable : corriger contre une
   * photo absente ou périmée ferait créer un doublon du planning entier. */
  corrigeable: boolean;
}

export function verdictSemaine(donnees: CelcatComparaison): Verdict {
  const lignes = donnees.lignes ?? [];
  const compter = (s: LigneComparaison["statut"]) => lignes.filter((l) => l.statut === s).length;
  const base = {
    aModifier: compter("ecart"),
    aCreer: compter("absente_celcat"),
    enTrop: compter("en_trop_celcat"),
    identiques: compter("identique"),
    horsCelcat: compter("hors_celcat"),
  };

  if (!donnees.releve_le) {
    return {
      ...base,
      ton: "attention",
      titre: "Pas encore de relevé de Celcat",
      detail: "Impossible de comparer : Celcat n’a pas encore été relu.",
      corrigeable: false,
    };
  }
  if (donnees.perime) {
    return {
      ...base,
      ton: "attention",
      titre: "Relevé trop ancien pour conclure",
      detail: `Le relevé date ${ageLisible(donnees.age_secondes)}. Vérifiez à nouveau avant de corriger.`,
      corrigeable: false,
    };
  }

  const aCorriger = base.aModifier + base.aCreer;
  if (aCorriger === 0 && base.enTrop === 0) {
    return {
      ...base,
      ton: "ok",
      titre: "Tout concorde avec Celcat",
      detail: `${pluriel(base.identiques, "séance identique", "séances identiques")}, vérifié ${ageLisible(donnees.age_secondes)}.`,
      corrigeable: false,
    };
  }

  const morceaux: string[] = [];
  if (base.aModifier) morceaux.push(`${base.aModifier} à modifier`);
  if (base.aCreer) morceaux.push(`${base.aCreer} à créer`);
  if (base.enTrop) morceaux.push(`${base.enTrop} en trop`);
  const total = aCorriger + base.enTrop;
  return {
    ...base,
    ton: "attention",
    titre: `${pluriel(total, "écart")} avec Celcat`,
    detail: `${morceaux.join(" · ")} — relevé pris ${ageLisible(donnees.age_secondes)}.`,
    corrigeable: true,
  };
}

/** Jour + date d'un indice de jour (0 = lundi), relativement au lundi de la
 * semaine : « mardi 15/09 ». Un jour sans date oblige à recompter. */
export function jourDate(jour: number | null | undefined, lundi: string | null): string {
  const JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];
  if (typeof jour !== "number" || jour < 0 || jour >= JOURS.length) return "—";
  const nom = JOURS[jour];
  if (!lundi) return nom;
  const d = new Date(`${lundi}T00:00:00`);
  if (Number.isNaN(d.getTime())) return nom;
  d.setDate(d.getDate() + jour);
  return `${nom} ${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;
}
