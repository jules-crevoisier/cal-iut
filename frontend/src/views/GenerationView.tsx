/**
 * Nouveau semestre (16/11/2026) — générer un emploi du temps complet depuis
 * l'interface, sans ligne de commande.
 *
 * Le calcul tourne sur le serveur, en tâche de fond, pendant plusieurs
 * heures : l'écran ne fait que le lancer, le suivre et en montrer le
 * résultat. Fermer la page n'arrête rien, et un redémarrage du serveur non
 * plus (la génération reprend là où elle en était). Le résultat est un
 * BROUILLON : le planning en service n'est pas modifié.
 *
 * Réservé aux administrateurs (`api/generations_routes.py`), même patron
 * que `SauvegardesView`.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, CircleDashed, LoaderCircle, Sparkles, X } from "lucide-react";

import {
  annulerGeneration,
  lancerGeneration,
  lireGeneration,
  listBrouillons,
  listGenerations,
  publierBrouillon,
  supprimerBrouillon,
  type EtapeGeneration,
  type GenerationDetail,
  type GenerationResume,
  type GenerationsReponse,
  type BrouillonsReponse,
  type RunResume,
  type StatutGeneration,
} from "../api/client";
import { ActionsDePage } from "../components/TopBar";
import "../styles/outils.css";
import "./GenerationView.css";

/** Pendant un calcul, l'état est relu toutes les 5 secondes. */
const PERIODE_SUIVI_MS = 5000;

const NOMBRE = new Intl.NumberFormat("fr-FR");
const DATE_HEURE = new Intl.DateTimeFormat("fr-FR", {
  day: "numeric",
  month: "long",
  hour: "2-digit",
  minute: "2-digit",
});

const STATUTS: Record<StatutGeneration, { libelle: string; classe: string }> = {
  en_attente: { libelle: "En attente", classe: "warn" },
  en_cours: { libelle: "En cours", classe: "warn" },
  terminee: { libelle: "Terminée", classe: "good" },
  echec: { libelle: "Échec", classe: "bad" },
  annulee: { libelle: "Annulée", classe: "" },
};

function formatDateHeure(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : DATE_HEURE.format(d);
}

function formatDuree(secondes: number | undefined): string {
  if (secondes === undefined) return "";
  const minutes = Math.round(secondes / 60);
  if (minutes < 1) return "moins d’une minute";
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`;
}

/** « , commencé il y a 42 min » : un essai dure souvent plus d'une demi-heure
 *  sans rien afficher d'autre. */
function depuis(iso: string): string {
  const debut = new Date(iso).getTime();
  if (Number.isNaN(debut)) return "";
  const secondes = Math.max(0, (Date.now() - debut) / 1000);
  return `, commencé il y a ${formatDuree(secondes)}`;
}

function pluriel(n: number, singulier: string, plurielMot = `${singulier}s`): string {
  return `${NOMBRE.format(n)} ${n > 1 ? plurielMot : singulier}`;
}

function IconeEtape({ statut }: { statut: EtapeGeneration["statut"] }) {
  if (statut === "faite") return <Check size={16} aria-hidden="true" />;
  if (statut === "en_cours") return <LoaderCircle size={16} aria-hidden="true" className="generation-tourne" />;
  if (statut === "echec" || statut === "annulee") return <X size={16} aria-hidden="true" />;
  return <CircleDashed size={16} aria-hidden="true" />;
}

const LIBELLE_ETAPE: Record<EtapeGeneration["statut"], string> = {
  a_faire: "à venir",
  en_cours: "en cours",
  faite: "fait",
  echec: "échec",
  annulee: "arrêtée",
};

function Etapes({ generation }: { generation: GenerationDetail }) {
  const essai = generation.tentative_en_cours;
  return (
    <ol className="generation-etapes">
      {generation.etapes.map((etape) => (
        <li key={etape.cle} className={`generation-etape generation-etape--${etape.statut}`}>
          <span className="generation-etape-icone">
            <IconeEtape statut={etape.statut} />
          </span>
          <span className="generation-etape-texte">
            <span className="generation-etape-nom">
              {etape.libelle}
              <span className="sr-only"> ({LIBELLE_ETAPE[etape.statut]})</span>
            </span>
            {etape.cle === "calcul" && etape.statut === "en_cours" && essai ? (
              <span className="generation-etape-detail">
                Essai {essai.numero} sur {generation.parametres.tentatives}
                {depuis(essai.debut)}
                {generation.meilleur
                  ? ` · meilleur résultat pour l’instant : ${pluriel(generation.meilleur.placees, "séance placée", "séances placées")}`
                  : ""}
              </span>
            ) : etape.detail ? (
              <span className="generation-etape-detail">{etape.detail}</span>
            ) : null}
          </span>
        </li>
      ))}
    </ol>
  );
}

function Resultat({ generation, libelleGroupe }: { generation: GenerationDetail; libelleGroupe: string }) {
  const r = generation.resultat;
  const constats = (generation.verification?.constats ?? []).filter((c) => c.severite !== "info");
  const essais = generation.tentatives;
  return (
    <section className="panel carte-tableau generation-resultat" aria-labelledby="generation-resultat-titre">
      <div className="carte-tete">
        <h2 id="generation-resultat-titre">
          {libelleGroupe} <span className={`pill ${STATUTS[generation.statut].classe}`}>{STATUTS[generation.statut].libelle}</span>
        </h2>
        <span className="carte-tete-note">
          lancée le {formatDateHeure(generation.cree_le)}
          {generation.cree_par ? ` par ${generation.cree_par}` : ""}
        </span>
      </div>

      {generation.statut === "echec" && (
        <p className="alerte generation-bloc" role="alert">
          La génération n’a pas abouti{generation.erreur ? ` : ${generation.erreur}` : "."}
        </p>
      )}
      {generation.statut === "annulee" && <p className="carte-vide">Cette génération a été arrêtée avant la fin.</p>}

      {r && (
        <>
          <dl className="generation-chiffres">
            <div>
              <dt>Séances placées</dt>
              <dd>
                {NOMBRE.format(r.placees)} <span className="muted">sur {NOMBRE.format(r.a_placer)}</span>
              </dd>
            </div>
            <div>
              <dt>À placer à la main</dt>
              <dd className={r.non_placees.length ? "generation-attention" : ""}>{NOMBRE.format(r.non_placees.length)}</dd>
            </div>
            <div>
              <dt>Sans salle</dt>
              <dd className={r.sans_salle ? "generation-attention" : ""}>{NOMBRE.format(r.sans_salle)}</dd>
            </div>
          </dl>
          {generation.run_id !== null && (
            <p className="generation-bloc generation-brouillon">
              Enregistré comme <strong>brouillon n° {generation.run_id}</strong>. Le planning en service n’a pas changé et
              rien n’est parti vers Celcat.
            </p>
          )}
          {r.non_placees.length > 0 && (
            <details className="generation-bloc">
              <summary>{pluriel(r.non_placees.length, "séance")} à placer à la main</summary>
              <ul className="generation-motifs">
                {r.motifs.map((m) => (
                  <li key={m.raison}>
                    <strong>{NOMBRE.format(m.nombre)}</strong> — {m.raison}
                  </li>
                ))}
              </ul>
              <table className="ref">
                <thead>
                  <tr>
                    <th scope="col">Cours</th>
                    <th scope="col">Séance</th>
                    <th scope="col">Pourquoi</th>
                  </tr>
                </thead>
                <tbody>
                  {r.non_placees.map((s) => (
                    <tr key={s.session_id}>
                      <th scope="row">{s.course_code}</th>
                      <td className="generation-id">{s.session_id}</td>
                      <td>{s.raison}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
        </>
      )}

      {constats.length > 0 && (
        <details className="generation-bloc">
          <summary>{pluriel(constats.length, "point")} relevés dans les données avant le calcul</summary>
          <ul className="generation-constats">
            {constats.map((c, i) => (
              <li key={`${c.controle}-${i}`}>
                <span className={`pill ${c.severite === "erreur" ? "bad" : "warn"}`}>
                  {c.severite === "erreur" ? "Erreur" : "Alerte"}
                </span>{" "}
                {c.message}
              </li>
            ))}
          </ul>
        </details>
      )}

      {essais.length > 0 && (
        <details className="generation-bloc">
          <summary>{pluriel(essais.length, "essai")} de calcul</summary>
          <table className="ref">
            <thead>
              <tr>
                <th scope="col">Essai</th>
                <th scope="col" className="num">
                  Séances placées
                </th>
                <th scope="col" className="num">
                  Manquantes
                </th>
                <th scope="col" className="num">
                  Durée
                </th>
                <th scope="col">
                  <span className="sr-only">Retenu</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {essais.map((t) => (
                <tr key={t.numero}>
                  <th scope="row">n° {t.numero}</th>
                  <td className="num">{t.placees !== undefined ? NOMBRE.format(t.placees) : "—"}</td>
                  <td className="num">{t.manquantes !== undefined ? NOMBRE.format(t.manquantes) : "—"}</td>
                  <td className="num">{formatDuree(t.secondes)}</td>
                  <td>{t.erreur ? <span className="muted">{t.erreur}</span> : t.gardee ? <span className="pill good">retenu</span> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </section>
  );
}

export function GenerationView({
  onRelire,
  onPublie,
}: {
  onRelire?: (runId: number) => void;
  /** Un brouillon vient d'être mis en service : recharger le planning. */
  onPublie?: () => void;
}) {
  const [brouillons, setBrouillons] = useState<RunResume[]>([]);
  const [enService, setEnService] = useState<BrouillonsReponse["en_service"]>([]);
  const [donnees, setDonnees] = useState<GenerationsReponse | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);
  const [groupe, setGroupe] = useState<string | null>(null);
  const [essais, setEssais] = useState<string>("");
  const [heures, setHeures] = useState<string>("");
  const [choisie, setChoisie] = useState<string | null>(null);
  const [detail, setDetail] = useState<GenerationDetail | null>(null);
  const etaitActive = useRef(false);

  const recharger = useCallback(async () => {
    try {
      const r = await listGenerations();
      setDonnees(r);
      // Les brouillons : un complément, jamais de quoi bloquer l'écran.
      listBrouillons()
        .then((b) => {
          setBrouillons(Array.isArray(b?.brouillons) ? b.brouillons : []);
          setEnService(Array.isArray(b?.en_service) ? b.en_service : []);
        })
        .catch(() => undefined);
      setErreur(null);
      // Le calcul vient de se terminer : on montre son résultat.
      if (etaitActive.current && !r.active) setChoisie(null);
      etaitActive.current = r.active !== null;
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Erreur de chargement");
    }
  }, []);

  useEffect(() => {
    void recharger();
  }, [recharger]);

  const activeId = donnees?.active?.id ?? null;
  useEffect(() => {
    if (!activeId) return undefined;
    const minuterie = window.setInterval(() => void recharger(), PERIODE_SUIVI_MS);
    return () => window.clearInterval(minuterie);
  }, [activeId, recharger]);

  // Résultat affiché : celui choisi dans l'historique, sinon la dernière
  // génération finie.
  const finies = (donnees?.generations ?? []).filter((g) => g.id !== activeId);
  const aAfficher = choisie ?? finies[0]?.id ?? null;
  useEffect(() => {
    if (!aAfficher) {
      setDetail(null);
      return undefined;
    }
    let perime = false;
    lireGeneration(aAfficher)
      .then((d) => {
        if (!perime) setDetail(d);
      })
      .catch(() => {
        if (!perime) setDetail(null);
      });
    return () => {
      perime = true;
    };
  }, [aAfficher]);

  if (erreur && !donnees) {
    return (
      <section className="view generation-view">
        <p className="alerte" role="alert">
          {erreur}
        </p>
        <div>
          <button type="button" className="btn" onClick={() => void recharger()}>
            Réessayer
          </button>
        </div>
      </section>
    );
  }

  if (!donnees) {
    return (
      <section className="view generation-view">
        <p className="muted">Chargement…</p>
      </section>
    );
  }

  const groupes = donnees.groupes;
  const libelleGroupe = (cle: string): string => {
    const g = groupes.find((x) => x.cle === cle);
    return g ? `${g.libelle} (${g.semestres.join(", ")})` : cle;
  };
  const groupeChoisi = groupes.find((g) => g.cle === groupe) ?? null;
  const active = donnees.active;

  const lancer = async () => {
    if (!groupeChoisi) return;
    setEnvoi(true);
    setErreur(null);
    setMessage(null);
    try {
      await lancerGeneration({
        semestre_group: groupeChoisi.cle,
        ...(essais.trim() ? { tentatives: Number(essais) } : {}),
        ...(heures.trim() ? { heures: Number(heures.replace(",", ".")) } : {}),
      });
      setMessage("Génération lancée. Vous pouvez fermer cette page : le calcul continue sur le serveur.");
      await recharger();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Le lancement a échoué");
    } finally {
      setEnvoi(false);
    }
  };

  // Le semestre en cours est celui que le serveur sert par défaut.
  const groupeEnCours = enService.find((r) => r.en_cours)?.groupe ?? null;

  const publier = async (b: RunResume) => {
    const remplace = enService.find((r) => r.groupe === b.groupe);
    const question = remplace
      ? `Publier le brouillon n° ${b.run_id} (${b.libelle}) ? Il REMPLACE le planning en service de ce semestre (${NOMBRE.format(remplace.placements)} séances, modifications comprises). Une copie de la base est faite avant.`
      : `Publier le brouillon n° ${b.run_id} (${b.libelle}) ? Il devient l’emploi du temps de ce semestre, visible par tous. Le semestre en cours ne change pas.`;
    if (!window.confirm(question)) return;
    setEnvoi(true);
    setErreur(null);
    try {
      const publie = await publierBrouillon(b.run_id);
      setMessage(
        `${publie.libelle} : en service. Choisissez ce semestre avec le sélecteur Impair / Pair, en haut de la barre latérale.`,
      );
      await recharger();
      onPublie?.();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "La publication a échoué");
    } finally {
      setEnvoi(false);
    }
  };

  const supprimer = async (b: RunResume) => {
    if (!window.confirm(`Supprimer le brouillon n° ${b.run_id} ? Il faudra relancer une génération pour en avoir un autre.`)) return;
    setEnvoi(true);
    setErreur(null);
    try {
      await supprimerBrouillon(b.run_id);
      setMessage(`Brouillon n° ${b.run_id} supprimé.`);
      await recharger();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "La suppression a échoué");
    } finally {
      setEnvoi(false);
    }
  };

  const annuler = async (g: GenerationDetail) => {
    if (!window.confirm("Arrêter la génération en cours ? Le calcul déjà fait sera perdu.")) return;
    setEnvoi(true);
    setErreur(null);
    try {
      await annulerGeneration(g.id);
      setMessage("Arrêt demandé.");
      await recharger();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "L’arrêt a échoué");
    } finally {
      setEnvoi(false);
    }
  };

  return (
    <section className="view generation-view">
      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}
      <div className="page-retour" role="status" aria-live="polite">
        {message}
      </div>

      {active ? (
        <section className="panel generation-carte" aria-labelledby="generation-active-titre">
          <div className="page-outils">
            <div>
              <h2 id="generation-active-titre">Génération en cours : {libelleGroupe(active.parametres.semestre_group)}</h2>
              <p className="generation-sous-titre">
                Lancée le {formatDateHeure(active.cree_le)}
                {active.cree_par ? ` par ${active.cree_par}` : ""}. Le calcul peut durer jusqu’à{" "}
                {formatDuree(active.parametres.heures * 3600)} ; vous pouvez fermer cette page.
              </p>
            </div>
            <ActionsDePage>
              <button
                type="button"
                className="btn btn--danger"
                disabled={envoi || active.annulation_demandee}
                onClick={() => void annuler(active)}
              >
                {active.annulation_demandee ? "Arrêt en cours…" : "Arrêter"}
              </button>
            </ActionsDePage>
          </div>
          {!active.vivante && !active.annulation_demandee && (
            <p className="generation-reprise" role="status">
              Le serveur a redémarré pendant le calcul. La génération reprend toute seule dans quelques minutes, là où
              elle en était.
            </p>
          )}
          <Etapes generation={active} />
          {active.journal.length > 0 && (
            <details className="generation-journal">
              <summary>Journal technique</summary>
              <pre>{active.journal.join("\n")}</pre>
            </details>
          )}
        </section>
      ) : (
        <section className="panel generation-carte" aria-labelledby="generation-lancer-titre">
          <h2 id="generation-lancer-titre">Générer un emploi du temps</h2>
          <p className="generation-sous-titre">
            Le serveur calcule l’emploi du temps complet du semestre à partir des maquettes, des disponibilités et des
            contraintes enregistrées. Le résultat est un <strong>brouillon</strong> : le planning en service ne change
            pas tant qu’il n’est pas publié.
          </p>
          <fieldset className="generation-groupes">
            <legend>Quel semestre ?</legend>
            {groupes.map((g) => (
              <label key={g.cle} className={`generation-groupe${groupe === g.cle ? " generation-groupe--choisi" : ""}`}>
                <input
                  type="radio"
                  name="generation-groupe"
                  value={g.cle}
                  checked={groupe === g.cle}
                  onChange={() => setGroupe(g.cle)}
                />
                <span>
                  <strong>{g.libelle}</strong>
                  <span className="muted">{g.semestres.join(", ")}</span>
                </span>
              </label>
            ))}
          </fieldset>
          {groupeChoisi && (
            <>
              <p className="generation-duree">
                Durée : jusqu’à{" "}
                <strong>{formatDuree((heures.trim() ? Number(heures.replace(",", ".")) : groupeChoisi.parametres.heures) * 3600)}</strong>
                . Le calcul s’arrête plus tôt dès qu’un essai place toutes les séances.
              </p>
              <details className="generation-reglages">
                <summary>Réglages</summary>
                <div className="generation-champs">
                  <label>
                    Nombre d’essais
                    <input
                      type="number"
                      min={1}
                      max={30}
                      value={essais}
                      placeholder={String(groupeChoisi.parametres.tentatives)}
                      onChange={(e) => setEssais(e.target.value)}
                    />
                  </label>
                  <label>
                    Durée maximale (heures)
                    <input
                      type="number"
                      min={0.25}
                      max={24}
                      step={0.25}
                      value={heures}
                      placeholder={String(groupeChoisi.parametres.heures)}
                      onChange={(e) => setHeures(e.target.value)}
                    />
                  </label>
                </div>
                <p className="muted">
                  Chaque essai repart d’un tirage différent ; le meilleur est gardé. Le serveur y consacre{" "}
                  {groupeChoisi.parametres.num_workers} cœur{groupeChoisi.parametres.num_workers > 1 ? "s" : ""} sur{" "}
                  {donnees.coeurs}.
                </p>
              </details>
            </>
          )}
          <div className="generation-actions">
            <button type="button" className="btn btn--primary" disabled={!groupeChoisi || envoi} onClick={() => void lancer()}>
              <Sparkles size={16} aria-hidden="true" />
              {envoi ? "Lancement…" : "Générer l’emploi du temps"}
            </button>
            {!groupeChoisi && <span className="muted">Choisissez d’abord le semestre.</span>}
          </div>
        </section>
      )}

      {detail && detail.id !== activeId && (
        <Resultat generation={detail} libelleGroupe={libelleGroupe(detail.parametres.semestre_group)} />
      )}

      {brouillons.length > 0 && (
        <section className="panel carte-tableau" aria-labelledby="generation-brouillons-titre">
          <div className="carte-tete">
            <h2 id="generation-brouillons-titre">
              Brouillons <span className="carte-tete-nb">{brouillons.length}</span>
            </h2>
            <span className="carte-tete-note">à relire dans les vues habituelles, sans rien changer au planning en service</span>
          </div>
          <table className="ref generation-historique">
            <thead>
              <tr>
                <th scope="col">Brouillon</th>
                <th scope="col">Semestre</th>
                <th scope="col">Calculé le</th>
                <th scope="col" className="num">
                  Séances placées
                </th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {brouillons.map((b) => (
                <tr key={b.run_id}>
                  <th scope="row">n° {b.run_id}</th>
                  <td>{b.libelle}</td>
                  <td>{formatDateHeure(b.cree_le)}</td>
                  <td className="num">{NOMBRE.format(b.placements)}</td>
                  <td className="generation-col-action">
                    <span className="generation-actions-ligne">
                      {onRelire && (
                        <button type="button" className="btn btn--sm btn--primary" onClick={() => onRelire(b.run_id)}>
                          Relire
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn--sm"
                        disabled={envoi || b.groupe === null || b.groupe === groupeEnCours}
                        title={
                          b.groupe !== null && b.groupe === groupeEnCours
                            ? "Le semestre en cours ne se remplace pas depuis l’interface : corrigez-le dans les vues."
                            : "Mettre ce brouillon en service"
                        }
                        onClick={() => void publier(b)}
                      >
                        Publier
                      </button>
                      <button type="button" className="btn btn--sm" disabled={envoi} onClick={() => void supprimer(b)}>
                        Supprimer
                      </button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="panel carte-tableau" aria-labelledby="generation-historique-titre">
        <div className="carte-tete">
          <h2 id="generation-historique-titre">
            Historique <span className="carte-tete-nb">{donnees.generations.length}</span>
          </h2>
          <span className="carte-tete-note">les dix dernières générations</span>
        </div>
        {donnees.generations.length === 0 ? (
          <p className="carte-vide">Aucune génération pour l’instant.</p>
        ) : (
          <table className="ref generation-historique">
            <thead>
              <tr>
                <th scope="col">Lancée le</th>
                <th scope="col">Semestre</th>
                <th scope="col">État</th>
                <th scope="col" className="num">
                  Séances placées
                </th>
                <th scope="col">
                  <span className="sr-only">Résultat</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {donnees.generations.map((g: GenerationResume) => (
                <tr key={g.id}>
                  <th scope="row">{formatDateHeure(g.cree_le)}</th>
                  <td>{libelleGroupe(g.semestre_group)}</td>
                  <td>
                    <span className={`pill ${STATUTS[g.statut].classe}`}>{STATUTS[g.statut].libelle}</span>
                  </td>
                  <td className="num">
                    {g.placees !== null && g.a_placer !== null ? `${NOMBRE.format(g.placees)} sur ${NOMBRE.format(g.a_placer)}` : "—"}
                  </td>
                  <td className="generation-col-action">
                    {g.id !== activeId && (
                      <button
                        type="button"
                        className="btn btn--sm"
                        aria-pressed={aAfficher === g.id}
                        onClick={() => setChoisie(g.id)}
                      >
                        Voir
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </section>
  );
}
