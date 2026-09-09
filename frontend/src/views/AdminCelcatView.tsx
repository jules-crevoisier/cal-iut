/**
 * Administration Celcat — bandeau Live, 3 étapes, lot de nuit, extras, journal.
 * Chrome identique à Comptes (panels, boutons, pills).
 */
import { useCallback, useEffect, useState } from "react";

import { ComparaisonCelcat } from "../components/ComparaisonCelcat";
import { CopyButton } from "../components/CopyButton";
import { EtatFileCelcat } from "../components/EtatFileCelcat";
import { confirmAsync } from "../utils/confirmDialog";

import {
  ajouterExtraCelcat,
  fetchCelcatEtat,
  fetchCelcatExtras,
  fetchAppState,
  fetchCelcatInstantane,
  fetchCelcatLogs,
  rafraichirCelcatInstantane,
  ignorerExtraCelcat,
  lancerNuitCelcat,
  patchCelcatSaisie,
  patchCelcatWorker,
  resynchroniserFileCelcat,
  validerSemainesCelcat,
  type CelcatEtat,
  type CelcatExtra,
  type CelcatInstantane,
  type CelcatLog,
} from "../api/client";

const SEMAINES = Array.from({ length: 30 }, (_, i) => i + 1);

function classesSemaine(
  n: number,
  draft: number[],
  validees: number[],
  passees: number[],
  lancees: number[],
  completes: number[],
): string {
  const cochee = draft.includes(n);
  const validee = validees.includes(n);
  const passee = passees.includes(n);
  const lancee = lancees.includes(n);
  const complete = completes.includes(n);
  const classes = ["celcat-semaine"];
  if (cochee) classes.push("celcat-semaine--cochee");
  if (validee) classes.push("celcat-semaine--validee");
  if (validee && !cochee) classes.push("celcat-semaine--retiree");
  if (passee) classes.push("celcat-semaine--passee");
  if (lancee) classes.push("celcat-semaine--lancee");
  if (complete && !validee && !passee && !lancee) classes.push("celcat-semaine--complete");
  if (passee || lancee) classes.push("celcat-semaine--disabled");
  return classes.join(" ");
}

function libelleSemaine(
  n: number,
  passees: number[],
  lancees: number[],
  validees: number[],
  completes: number[],
): string {
  if (passees.includes(n)) return `Semaine ${n} passée`;
  if (lancees.includes(n)) return `Semaine ${n} lancée`;
  if (validees.includes(n)) return `Semaine ${n} validée`;
  // "planning complet", pas "placée dans Celcat" — retour utilisateur
  // (03/09/2026) : la formulation précédente laissait croire que ces
  // semaines étaient déjà envoyées à Celcat, alors que ça ne dit que « plus
  // aucune séance manquante côté planning », rien sur Celcat.
  if (completes.includes(n)) return `Semaine ${n} — planning complet, pas encore envoyé à Celcat`;
  return `Semaine ${n}`;
}

/** Colonnes de la vue d'activité, dans l'ordre de lecture : ce qui s'est
 * bien passé d'abord, ce qui coince en dernier — c'est là que le regard doit
 * s'arrêter. */
const COLONNES: Array<{ kind: string; titre: string; ton: string }> = [
  { kind: "created", titre: "Créées", ton: "good" },
  { kind: "modified", titre: "Modifiées", ton: "good" },
  { kind: "deleted", titre: "Supprimées", ton: "" },
  { kind: "echec", titre: "Échecs", ton: "bad" },
  { kind: "blocked", titre: "Bloquées", ton: "bad" },
];

/** « il y a 47 min » — l'âge d'un relevé compte autant que son contenu :
 * présenté sans lui, un relevé de trois heures passerait pour l'état
 * courant. */
function ageLisible(secondes: number | null): string {
  if (secondes === null) return "";
  if (secondes < 60) return "il y a moins d’une minute";
  const minutes = Math.floor(secondes / 60);
  if (minutes < 60) return `il y a ${minutes} min`;
  const heures = Math.floor(minutes / 60);
  const reste = minutes % 60;
  return reste ? `il y a ${heures} h ${reste} min` : `il y a ${heures} h`;
}

/** Ce qu'on colle dans un message ou un ticket : l'identifiant de séance,
 * l'évènement Celcat pour aller vérifier, le nombre de tentatives pour
 * juger de l'ampleur, et le motif. Relire à l'écran pour retaper à côté est
 * exactement la friction qui fait qu'un problème n'est pas signalé. */
function texteColonne(titre: string, lignes: CelcatLog[]): string {
  const entete = `${titre} (${lignes.length})`;
  const corps = lignes.map((l) => {
    const morceaux = [l.session_id ?? l.course_code ?? "?"];
    if (l.event_id) morceaux.push(`event_id=${l.event_id}`);
    if (l.repetitions && l.repetitions > 1) morceaux.push(`${l.repetitions} tentatives`);
    if (l.at) morceaux.push(l.at);
    if (l.motif) morceaux.push(l.motif);
    return `- ${morceaux.join(" | ")}`;
  });
  return [entete, ...corps].join("\n");
}

function libelleExtra(extra: CelcatExtra): string {
  return extra.course_code || extra.libelle || extra.module_nom || extra.id;
}

export function AdminCelcatView() {
  const [etat, setEtat] = useState<CelcatEtat | null>(null);
  const [extras, setExtras] = useState<CelcatExtra[]>([]);
  const [logs, setLogs] = useState<CelcatLog[]>([]);
  const [semaines, setSemaines] = useState<number[]>([]);
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);
  const [instantane, setInstantane] = useState<CelcatInstantane | null>(null);
  const [messageReleve, setMessageReleve] = useState<string | null>(null);
  // Semaine comparée. Par défaut la première validée : c'est celle qui
  // compte pour la synchro, pas forcément la semaine courante.
  // Indice INTERNE (0-based), comme partout ailleurs : l'affichage montre
  // `indice + 1`. Le sélecteur envoyait l'indice affiché, donc comparait la
  // semaine suivante — repéré par Jules le 08/09/2026 (« semaine 1 égale
  // semaine 2 dans vue promo non ? »).
  const [semaineComparee, setSemaineComparee] = useState(0);
  // Trois onglets plutôt qu'une page de six panneaux empilés (retour
  // utilisateur 08/09/2026 : « là c'est illisible, trop de choses »). Le
  // découpage suit l'usage, pas la technique : on VIENT pour piloter la
  // saisie, ou pour vérifier ce qui s'est passé, ou pour confronter à
  // Celcat — rarement pour les trois à la fois.
  // Libellés RÉELS des semaines (« Semaine 3 (7–11 sept. 2026) ») plutôt
  // qu'un « Semaine N » recalculé : l'app numérote les semaines autrement
  // que l'indice interne — `weekRows[0]` s'appelle « Semaine 2 ». Deux
  // numérotations pour la même chose, c'est la garantie de comparer la
  // mauvaise semaine sans s'en apercevoir (constaté le 08/09/2026).
  const [libellesSemaines, setLibellesSemaines] = useState<string[]>([]);
  const [onglet, setOnglet] = useState<"pilotage" | "activite" | "celcat">("pilotage");
  const [messageResync, setMessageResync] = useState<string | null>(null);

  const charger = useCallback(async () => {
    try {
      const [e, x, l, i] = await Promise.all([
        fetchCelcatEtat(),
        fetchCelcatExtras("ouvert"),
        fetchCelcatLogs(50),
        // L'instantané ne doit pas faire échouer tout l'écran : le reste
        // reste utile même si le sidecar n'a encore rien déposé.
        fetchCelcatInstantane().catch(() => null),
      ]);
      // Sans bloquer l'écran si le planning n'est pas résolu.
      fetchAppState()
        .then((p) => setLibellesSemaines((p.weekRows ?? []).map((w) => w.label)))
        .catch(() => setLibellesSemaines([]));
      setEtat(e);
      setSemaines(e.semaines_validees);
      setExtras(x.extras);
      setLogs(l.items);
      setInstantane(i);
      setErreur(null);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur de chargement");
    }
  }, []);

  useEffect(() => {
    void charger();
  }, [charger]);

  const basculerSaisie = async (active: boolean) => {
    setEnCours(true);
    try {
      setEtat(await patchCelcatSaisie(active));
      setErreur(null);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur");
    } finally {
      setEnCours(false);
    }
  };

  const basculerWorker = async (actif: boolean) => {
    setEnCours(true);
    try {
      setEtat(await patchCelcatWorker(actif));
      setErreur(null);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur");
    } finally {
      setEnCours(false);
    }
  };

  const valider = async () => {
    setEnCours(true);
    try {
      setEtat(await validerSemainesCelcat(semaines));
      setErreur(null);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur");
    } finally {
      setEnCours(false);
    }
  };

  const lancerMaintenant = async () => {
    setEnCours(true);
    try {
      // Bug utilisateur du 05/09/2026 : cocher des semaines puis cliquer
      // directement « Lancer maintenant » (sans passer par « Enregistrer
      // le lot de nuit » d'abord) ne faisait RIEN — ce bouton appelait
      // /celcat/lancer-nuit tout seul, qui ne connaît que le DERNIER lot
      // déjà enregistré côté serveur (semaines_validees), jamais la
      // sélection à l'écran. « Lancer maintenant » enregistre donc d'abord
      // la sélection courante, exactement comme « Enregistrer le lot de
      // nuit » le ferait, avant de lancer — un seul clic suffit désormais.
      await validerSemainesCelcat(semaines);
      setEtat(await lancerNuitCelcat());
      setErreur(null);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur");
    } finally {
      setEnCours(false);
    }
  };

  const basculerSemaine = (n: number, verrouillee: boolean) => {
    if (verrouillee) return;
    setSemaines((prev) => (prev.includes(n) ? prev.filter((s) => s !== n) : [...prev, n].sort((a, b) => a - b)));
  };

  const traiterExtra = async (id: string, action: "ajouter" | "ignorer") => {
    setEnCours(true);
    try {
      if (action === "ajouter") {
        await ajouterExtraCelcat(id);
      } else {
        await ignorerExtraCelcat(id);
      }
      setExtras((prev) => prev.filter((x) => x.id !== id));
      setErreur(null);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur");
    } finally {
      setEnCours(false);
    }
  };

  if (erreur && !etat) {
    return (
      <section className="view celcat">
        <div className="panel">
          <p className="alerte" role="alert">
            {erreur}
          </p>
        </div>
      </section>
    );
  }

  if (!etat) {
    return (
      <section className="view celcat">
        <div className="panel">
          <p className="muted">Chargement…</p>
        </div>
      </section>
    );
  }

  const validees = etat.semaines_validees;
  const passees = etat.semaines_passees ?? [];
  const lancees = etat.semaines_lancees ?? [];
  // Retour utilisateur (03/09/2026) : "si la semaine 1 est entièrement
  // placée on la met comme placée" — distinct de « validée » (lot de nuit
  // enregistré) : une semaine peut être entièrement placée sans qu'on ait
  // encore décidé de l'envoyer à Celcat.
  const completes = etat.semaines_completes ?? [];

  return (
    <section className="view celcat">
      {erreur && (
        <div className="panel">
          <p className="alerte" role="alert">
            {erreur}
          </p>
        </div>
      )}

      <nav className="celcat-onglets" aria-label="Sections Celcat">
        {([
          ["pilotage", "Pilotage"],
          ["activite", "Activité"],
          ["celcat", "Contenu Celcat"],
        ] as const).map(([cle, libelle]) => (
          <button
            key={cle}
            type="button"
            className={`celcat-onglet${onglet === cle ? " celcat-onglet--actif" : ""}`}
            aria-current={onglet === cle ? "page" : undefined}
            onClick={() => setOnglet(cle)}
          >
            {libelle}
          </button>
        ))}
      </nav>

      {onglet === "pilotage" ? (
      <>
      <div className={`panel celcat-hero celcat-etape ${etat.saisie_active ? "celcat-hero--on" : "celcat-hero--off"}`}>
        <span className="celcat-etape-num">1</span>
        <div className="celcat-etape-corps">
          <h3>Armer l’écriture</h3>
          <p className="celcat-hero-statut">{etat.saisie_active ? "ÉCRITURE ON" : "ÉCRITURE OFF"}</p>
          <p className="celcat-hero-consequence">
            {etat.saisie_active
              ? "Chaque modification du planning s’écrit tout de suite dans Celcat."
              : "Les modifications du planning ne s’écrivent pas tout de suite dans Celcat."}
          </p>
          <div className="celcat-switch-row">
            <button
              type="button"
              role="switch"
              className="celcat-switch"
              aria-checked={etat.saisie_active}
              aria-label="Écriture Celcat"
              disabled={enCours}
              onClick={() => void basculerSaisie(!etat.saisie_active)}
            >
              <span className="celcat-switch-knob" />
            </button>
            <span>{etat.saisie_active ? "Live armé" : "Live désarmé"}</span>
          </div>
          {/* PAUSE DU WORKER, distincte de l'écriture ci-dessus.
              Le VPN et le compte Celcat sont PARTAGÉS avec l'équipe : tant
              que le worker tourne, il monte le tunnel toutes les 90 secondes
              et personne ne peut ouvrir une session durable à côté. Le
              09/09/2026, une recherche d'identifiant a dû être abandonnée
              pour cette raison.

              Ce bouton ne touche NI la file, NI le journal, NI les semaines
              validées — contrairement au bouton d'écriture ci-dessus, dont
              la coupure vide la file. */}
          <div className="celcat-switch-row">
            <button
              type="button"
              role="switch"
              className="celcat-switch"
              aria-checked={etat.worker_actif !== false}
              aria-label="Worker Celcat (VPN)"
              disabled={enCours}
              onClick={() => void basculerWorker(etat.worker_actif === false)}
            >
              <span className="celcat-switch-knob" />
            </button>
            <span>
              {etat.worker_actif === false
                ? "Worker en pause — VPN libre, la file est conservée"
                : "Worker actif — il prend le VPN toutes les 90 s"}
            </span>
          </div>
          <div className="celcat-hero-meta">
            <span className={`pill mini ${etat.worker_ok ? "good" : "bad"}`}>
              {etat.worker_ok ? "Worker joignable." : "Worker injoignable."}
            </span>
            {/* Retour utilisateur (03/09/2026) : "on voudrait la dernière
                fois qu'une modification faite dans l'app a été appliquée
                dans Celcat" — c'est CE signal-là qui doit être le plus
                visible, pas `valide_le` (qui ne marque que le dernier clic
                sur « Enregistrer le lot de nuit », jamais une écriture
                réelle). */}
            <span>
              {etat.derniere_ecriture_celcat
                ? `Dernière modification appliquée dans Celcat : ${etat.derniere_ecriture_celcat}.`
                : "Aucune modification encore appliquée dans Celcat."}
            </span>
          </div>
          {/* Détail technique, secondaire : à quand remonte le dernier lot
              VALIDÉ (étape 2) et le dernier passage du job de nuit — utile
              pour diagnostiquer pourquoi rien n'a encore été appliqué
              ci-dessus, pas la première chose à lire. */}
          <p className="celcat-hero-detail muted">
            {etat.valide_le ? `Dernier lot validé : ${etat.valide_le}.` : "Aucun lot validé."}{" "}
            {etat.dernier_job?.lance_le
              ? `Dernier passage du job de nuit : ${etat.dernier_job.lance_le}.`
              : "Le job de nuit n'a encore jamais tourné."}
          </p>
        </div>
      </div>

      <div className="panel celcat-etape">
        <span className="celcat-etape-num">2</span>
        <div className="celcat-etape-corps">
          <h3>Semaines du lot de nuit</h3>
          <p>
            Enregistrer le lot pour cette nuit. Lancer maintenant enfile le même lot tout de suite, sans attendre
            minuit. Les semaines passées ou déjà lancées sont désactivées.
          </p>
          <div className="celcat-semaines">
            {SEMAINES.map((n) => {
              const validee = validees.includes(n);
              const cochee = semaines.includes(n);
              const verrouillee = passees.includes(n) || lancees.includes(n);
              const pastille = passees.includes(n)
                ? "passée"
                : lancees.includes(n)
                  ? "lancée"
                  : validee
                    ? "validée"
                    : completes.includes(n)
                      ? "planning complet"
                      : null;
              return (
                <button
                  key={n}
                  type="button"
                  className={classesSemaine(n, semaines, validees, passees, lancees, completes)}
                  aria-pressed={cochee}
                  aria-label={libelleSemaine(n, passees, lancees, validees, completes)}
                  disabled={verrouillee || enCours}
                  onClick={() => basculerSemaine(n, verrouillee)}
                >
                  Semaine {n}
                  {pastille ? (
                    <span className="pill mini" aria-hidden="true">
                      {pastille}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
          <div className="celcat-lot-actions">
            <button type="button" className="btn btn--accent" disabled={enCours} onClick={() => void valider()}>
              Enregistrer le lot de nuit
            </button>
            <button
              type="button"
              className="btn btn--primary"
              disabled={enCours || !etat.saisie_active}
              onClick={() => void lancerMaintenant()}
            >
              Lancer maintenant
            </button>
          </div>
        </div>
      </div>

      <div className="panel celcat-etape">
        <span className="celcat-etape-num">3</span>
        <div className="celcat-etape-corps">
          <h3>Extras Live</h3>
          {extras.length === 0 ? (
            <p className="muted">Aucun extra ouvert.</p>
          ) : (
            <ul className="celcat-extras">
              {extras.map((x) => {
                const label = libelleExtra(x);
                return (
                  <li key={x.id} className="celcat-extra">
                    <strong>{label}</strong>
                    <div className="celcat-extra-actions">
                      <button
                        type="button"
                        className="btn btn--sm"
                        disabled={enCours}
                        aria-label={`Ajouter ${label}`}
                        onClick={() => void traiterExtra(x.id, "ajouter")}
                      >
                        Ajouter
                      </button>
                      <button
                        type="button"
                        className="btn btn--sm btn--ghost"
                        disabled={enCours}
                        aria-label={`Ignorer ${label}`}
                        onClick={() => void traiterExtra(x.id, "ignorer")}
                      >
                        Ignorer
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      </>
      ) : null}

      {onglet === "celcat" ? (
      <>
      {/* Ce que Celcat contient vraiment. L'API ne le lit jamais elle-même
          (son conteneur n'a ni VPN ni navigateur) : elle sert un relevé
          déposé par le sidecar, d'où l'âge affiché systématiquement. */}
      <div className="panel celcat-instantane" data-testid="instantane-celcat">
        <h3>Contenu de Celcat</h3>
        {!instantane?.releve_le ? (
          <p className="muted">
            Aucun relevé pour l’instant — Celcat n’a pas encore été consulté.
          </p>
        ) : (
          <p className={instantane.perime ? "bad" : "muted"}>
            {(instantane.evenements ?? []).length} évènement(s) sur{" "}
            {(instantane.groupes ?? []).length} groupe(s),
            relevé {ageLisible(instantane.age_secondes)}
            {instantane.perime ? " — périmé, à rafraîchir" : ""}
          </p>
        )}
        {instantane?.erreur ? (
          // Un instantané vide sans explication ramènerait au silence que
          // cet outil vient de passer deux jours à réparer.
          <p className="bad">Dernier relevé en échec : {instantane.erreur}</p>
        ) : null}
        <button
          type="button"
          disabled={enCours}
          onClick={async () => {
            setEnCours(true);
            try {
              const r = await rafraichirCelcatInstantane();
              setMessageReleve(r.message);
              setErreur(null);
            } catch (err) {
              setErreur(err instanceof Error ? err.message : "Demande impossible");
            } finally {
              setEnCours(false);
            }
          }}
        >
          Rafraîchir
        </button>
        {messageReleve ? <p className="muted">{messageReleve}</p> : null}
        {instantane?.demande_en_cours && !messageReleve ? (
          <p className="muted">Relevé demandé — en attente du prochain passage.</p>
        ) : null}
      </div>

      {/* Celcat vs cal-iut. Placé juste après l'instantané : c'est la même
          question — ce que Celcat contient — mais confrontée au planning. */}
      <div className="panel celcat-comparaison">
        <h3>Comparer avec cal-iut</h3>
        <label>
          Semaine{" "}
          <select
            value={semaineComparee}
            onChange={(e) => setSemaineComparee(Number(e.target.value))}
          >
            {(libellesSemaines.length ? libellesSemaines : SEMAINES.map((n) => `Semaine ${n}`)).map(
              (libelle, i) => (
                <option key={libelle} value={i}>
                  {libelle}
                </option>
              ),
            )}
          </select>
        </label>
        <ComparaisonCelcat semaine={semaineComparee} />
      </div>

      </>
      ) : null}

      {onglet === "activite" ? (
      <>
      {/* Repartir de la comparaison. La file se remplissait par balayage
          aveugle du planning : 491 jobs dont 409 créations, là où la
          comparaison n'en réclamait que 105 (le 08/09/2026). Ce bouton jette
          ce qui attend sur les semaines validées et ne ré-enfile que ce qui
          diverge réellement — « on veut uniquement modifier ce qui ne va
          pas ». */}
      <div className="panel">
        <h3>File d’attente</h3>
        <EtatFileCelcat />
        <p className="muted">
          Reconstruit la file à partir de la comparaison : ce qui concorde déjà avec Celcat
          n’engendre plus aucun job. Ne touche que les semaines validées.
        </p>
        {/* Deux gestes, parce que le risque n'est pas le même. Reconstruire
            les modifications et les créations est rattrapable ; supprimer ne
            l'est pas — le 08/09/2026, dix-sept évènements ont disparu de
            Celcat parce que des suppressions dormaient en file depuis le
            matin, dont douze venus d'une saisie manuelle en cours. */}
        {([
          ["sans", "Reconstruire sans supprimer", false],
          ["avec", "Reconstruire, suppressions comprises", true],
        ] as const).map(([cle, libelle, supprimer]) => (
          <button
            key={cle}
            type="button"
            disabled={enCours}
            data-testid={`resynchroniser-file-${cle}`}
            onClick={() => {
              void (async () => {
                if (supprimer) {
                  const ok = await confirmAsync(
                    "Les évènements que Celcat a en trop seront SUPPRIMÉS définitivement.\n\n" +
                      "À n’utiliser que si personne ne travaille dans Celcat en ce moment.",
                    { title: "Reconstruire avec les suppressions", confirmLabel: "Reconstruire" },
                  );
                  if (!ok) return;
                }
                setEnCours(true);
                try {
                  const r = await resynchroniserFileCelcat(undefined, { supprimer });
                  setMessageResync(r.message);
                  setErreur(null);
                } catch (e) {
                  setErreur(e instanceof Error ? e.message : "Resynchronisation impossible");
                } finally {
                  setEnCours(false);
                }
              })();
            }}
          >
            {libelle}
          </button>
        ))}
        {messageResync ? <p className="muted">{messageResync}</p> : null}
      </div>

      {/* Activité récente, en colonnes. Remplace la liste chronologique :
          « 12 échecs sur le même motif » et « 12 incidents distincts »
          n'appellent pas le même geste, et une liste à plat ne les
          distinguait pas. */}
      <div className="panel celcat-journal">
        <h3>Activité</h3>
        {logs.length === 0 ? (
          <p className="muted">Aucune entrée.</p>
        ) : (
          <div className="celcat-kanban">
            {COLONNES.map((colonne) => {
              const lignes = logs.filter((l) => l.kind === colonne.kind);
              return (
                <div
                  key={colonne.kind}
                  className="celcat-kanban-col"
                  data-testid={`colonne-${colonne.kind}`}
                >
                  <h4>
                    {colonne.titre} <span className={`pill mini ${colonne.ton}`}>{lignes.length}</span>
                    {lignes.length > 0 ? (
                      <CopyButton
                        text={() => texteColonne(colonne.titre, lignes)}
                        idleLabel="Copier"
                        title={`Copier les ${lignes.length} ligne(s) de « ${colonne.titre} »`}
                      />
                    ) : null}
                  </h4>
                  {lignes.length === 0 ? (
                    <p className="muted">—</p>
                  ) : (
                    <ul className="celcat-journal-list">
                      {lignes.map((item, i) => (
                        <li
                          key={`${item.session_id ?? colonne.kind}-${i}`}
                          className={`celcat-journal-item celcat-journal-item--${colonne.kind}`}
                          title={item.at ?? undefined}
                        >
                          <strong>{item.session_id ?? item.course_code ?? "?"}</strong>
                          {/* Le nombre de tentatives distingue un blocage
                              installé d'un incident isolé — sans lui, les
                              deux se ressemblent. */}
                          {item.repetitions && item.repetitions > 1 ? (
                            <span className="pill mini bad"> {item.repetitions}× </span>
                          ) : null}
                          {item.event_id ? <span className="muted"> #{item.event_id}</span> : null}
                          {item.motif ? <div className="muted">{item.motif}</div> : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
      </>
      ) : null}
    </section>
  );
}
