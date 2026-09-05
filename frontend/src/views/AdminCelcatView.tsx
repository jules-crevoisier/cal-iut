/**
 * Administration Celcat — bandeau Live, 3 étapes, lot de nuit, extras, journal.
 * Chrome identique à Comptes (panels, boutons, pills).
 */
import { useCallback, useEffect, useState } from "react";

import {
  ajouterExtraCelcat,
  fetchCelcatEtat,
  fetchCelcatExtras,
  fetchCelcatLogs,
  ignorerExtraCelcat,
  lancerNuitCelcat,
  patchCelcatSaisie,
  validerSemainesCelcat,
  type CelcatEtat,
  type CelcatExtra,
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

function libelleJournal(kind: string): string {
  if (kind === "created") return "créé";
  if (kind === "blocked") return "bloqué";
  return kind;
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

  const charger = useCallback(async () => {
    try {
      const [e, x, l] = await Promise.all([
        fetchCelcatEtat(),
        fetchCelcatExtras("ouvert"),
        fetchCelcatLogs(50),
      ]);
      setEtat(e);
      setSemaines(e.semaines_validees);
      setExtras(x.extras);
      setLogs(l.items);
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

      <div className="panel celcat-journal">
        <h3>Journal</h3>
        {logs.length === 0 ? (
          <p className="muted">Aucune entrée.</p>
        ) : (
          <ul className="celcat-journal-list">
            {logs.map((item, i) => (
              <li
                key={`${item.session_id ?? "log"}-${i}`}
                className={`celcat-journal-item ${item.kind === "created" ? "celcat-journal-item--created" : ""} ${item.kind === "blocked" ? "celcat-journal-item--blocked" : ""}`.trim()}
              >
                <span className={`pill mini ${item.kind === "blocked" ? "bad" : item.kind === "created" ? "good" : ""}`}>
                  {libelleJournal(item.kind)}
                </span>
                {item.motif ? ` — ${item.motif}` : ""}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
