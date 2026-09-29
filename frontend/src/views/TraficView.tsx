/**
 * Trafic — anti-aspiration (29/09/2026, cf. api/anti_aspiration.py et
 * docs/ANTI-ASPIRATION.md).
 *
 * Des clients aspirent le serveur par les liens publics (`?t=`, sans
 * vérification — décision du 28/08/2026, inchangée). Cet écran montre qui
 * interroge le serveur et à quel rythme, et permet de bloquer une IP, une
 * plage ou un User-Agent. Réservé aux admins : le backend refuse déjà tout
 * le reste (`require_role("admin")`), même patron que `SauvegardesView`.
 *
 * Tout le mécanisme est inerte par défaut (`CAL_IUT_ANTI_ASPIRATION=off`) :
 * le bandeau d'état le dit et donne la variable à poser. La liste de
 * blocage, elle, se prépare dès maintenant — elle s'applique à partir du
 * mode « observation ».
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, ShieldBan } from "lucide-react";

import {
  ErreurApi,
  creerBlocage,
  fetchTrafic,
  listBlocages,
  supprimerBlocage,
  type Blocage,
  type ClientTrafic,
  type FenetreTrafic,
  type ModeAntiAspiration,
  type NouveauBlocage,
  type TraficResponse,
  type TypeBlocage,
} from "../api/client";
import { ChampRecherche } from "../components/ChampRecherche";
import { Onglets } from "../components/Onglets";
import { ActionsDePage } from "../components/TopBar";
import { Tuile, Tuiles } from "../components/Tuile";
import "../styles/outils.css";
import "./TraficView.css";

const NOMBRE = new Intl.NumberFormat("fr-FR");
const DATE_HEURE = new Intl.DateTimeFormat("fr-FR", {
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

const FENETRES: Array<{ id: FenetreTrafic; label: string }> = [
  { id: "15min", label: "15 min" },
  { id: "1h", label: "1 h" },
  { id: "24h", label: "24 h" },
];

const LIBELLE_FENETRE: Record<FenetreTrafic, string> = { "15min": "15 min", "1h": "1 h", "24h": "24 h" };

const LIBELLE_TYPE: Record<TypeBlocage, string> = {
  ip: "Adresse IP",
  cidr: "Plage d'adresses",
  user_agent: "User-Agent",
};

const LIBELLE_CATEGORIE: Record<string, string> = {
  public: "Lien public",
  ics: "Agenda .ics",
  sonde: "Sonde",
  appli: "Compte",
  api: "Clé API",
};

/** Durées proposées : [libellé, valeur envoyée]. `null` = permanent. */
const DUREES: Array<[string, string | null]> = [
  ["1 h", "1h"],
  ["24 h", "24h"],
  ["7 jours", "7j"],
  ["Permanent", null],
];

const MODES: Record<ModeAntiAspiration, { pastille: string; ton: string; texte: (v: string, t: TraficResponse | null) => string }> = {
  off: {
    pastille: "Désactivé",
    ton: "",
    texte: (v) =>
      `Rien n'est compté ni bloqué. Pour observer sans rien refuser, poser ${v}=observe dans les variables du service backend (Dokploy), puis redéployer. La liste de blocage peut être préparée dès maintenant : elle s'appliquera à l'activation.`,
  },
  observe: {
    pastille: "Observation",
    ton: "warn",
    texte: (v) =>
      `Le trafic est compté et les dépassements sont journalisés, mais rien n'est refusé ; seuls les blocages manuels s'appliquent. Une fois les budgets ajustés : ${v}=enforce.`,
  },
  enforce: {
    pastille: "Blocage actif",
    ton: "good",
    texte: (v, t) => {
      const duree = t ? dureeLisible(t.bannissement.duree_s) : "1 h";
      return `Au-delà des budgets, les requêtes sont refusées (429) ; une IP qui insiste est bannie ${duree}. Retour arrière immédiat : ${v}=off.`;
    },
  },
};

function dureeLisible(secondes: number): string {
  if (secondes % 86400 === 0) return `${secondes / 86400} j`;
  if (secondes % 3600 === 0) return `${secondes / 3600} h`;
  if (secondes % 60 === 0) return `${secondes / 60} min`;
  return `${secondes} s`;
}

function periodeLisible(secondes: number): string {
  if (secondes === 1) return "s";
  if (secondes === 60) return "min";
  if (secondes === 3600) return "h";
  return dureeLisible(secondes);
}

function dateLisible(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : DATE_HEURE.format(d);
}

function ilYA(iso: string): string {
  const d = new Date(iso).getTime();
  if (Number.isNaN(d)) return iso;
  const minutes = Math.max(0, Math.round((Date.now() - d) / 60000));
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const heures = Math.round(minutes / 60);
  return `il y a ${heures} h`;
}

function message(e: unknown, defaut: string): string {
  return e instanceof Error ? e.message : defaut;
}

/** Pré-remplissage de la modale : une ligne du tableau, ou rien. */
interface Cible {
  type: TypeBlocage;
  valeur: string;
  userAgent?: string;
  ip?: string;
}

function BloquerModal({
  cible,
  onFait,
  onAnnuler,
}: {
  cible: Cible | null;
  onFait: (b: Blocage) => void;
  onAnnuler: () => void;
}) {
  const [type, setType] = useState<TypeBlocage>(cible?.type ?? "ip");
  const [valeur, setValeur] = useState(cible?.valeur ?? "");
  const [duree, setDuree] = useState<string | null>("24h");
  const [motif, setMotif] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [aConfirmer, setAConfirmer] = useState(false);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onAnnuler();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onAnnuler]);

  // Depuis une ligne : passer de l'IP au User-Agent reprend la bonne valeur.
  const changerType = (t: TypeBlocage) => {
    setType(t);
    setAConfirmer(false);
    if (cible?.ip && t === "ip") setValeur(cible.ip);
    if (cible?.userAgent && t === "user_agent") setValeur(cible.userAgent);
  };

  const envoyer = async (forcer: boolean) => {
    if (!valeur.trim()) {
      setErreur("Indiquez ce qu'il faut bloquer.");
      return;
    }
    setEnCours(true);
    setErreur(null);
    const corps: NouveauBlocage = { type, valeur: valeur.trim(), motif: motif.trim(), duree, forcer };
    try {
      onFait(await creerBlocage(corps));
    } catch (e) {
      setErreur(message(e, "Blocage impossible"));
      setAConfirmer(e instanceof ErreurApi && e.status === 409);
    } finally {
      setEnCours(false);
    }
  };

  const exemple = type === "ip" ? "203.0.113.7" : type === "cidr" ? "203.0.113.0/24" : "python-requests";

  return (
    <div className="confirmmodal-overlay" role="presentation" onClick={onAnnuler}>
      <form
        className="panel confirmmodal trafic-modale"
        role="dialog"
        aria-modal="true"
        aria-labelledby="trafic-bloquer-titre"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          void envoyer(false);
        }}
      >
        <h3 id="trafic-bloquer-titre">Bloquer</h3>
        <p className="muted small">
          Toute requête visée reçoit un refus (403), compte connecté compris — une IP peut être partagée par tout un
          réseau (Wi-Fi de l'IUT, opérateur mobile).
        </p>

        <label className="newroom-field">
          Quoi
          <select value={type} onChange={(e) => changerType(e.target.value as TypeBlocage)}>
            <option value="ip">{LIBELLE_TYPE.ip}</option>
            <option value="cidr">{LIBELLE_TYPE.cidr}</option>
            <option value="user_agent">{LIBELLE_TYPE.user_agent} (contient…)</option>
          </select>
        </label>

        <label className="newroom-field">
          {type === "user_agent" ? "Motif du User-Agent" : type === "cidr" ? "Plage (CIDR)" : "Adresse"}
          <input
            type="text"
            value={valeur}
            autoFocus={!cible}
            maxLength={200}
            placeholder={`ex. ${exemple}`}
            onChange={(e) => {
              setValeur(e.target.value);
              setAConfirmer(false);
            }}
          />
        </label>

        <fieldset className="trafic-durees">
          <legend>Durée</legend>
          <div className="segmente" role="radiogroup" aria-label="Durée du blocage">
            {DUREES.map(([libelle, v]) => (
              <button
                key={libelle}
                type="button"
                role="radio"
                aria-checked={duree === v}
                onClick={() => setDuree(v)}
              >
                {libelle}
              </button>
            ))}
          </div>
        </fieldset>

        <label className="newroom-field">
          Motif
          <input
            type="text"
            value={motif}
            autoFocus={!!cible}
            maxLength={200}
            placeholder="ex. aspire /app-state toutes les 10 s"
            onChange={(e) => setMotif(e.target.value)}
          />
        </label>

        {erreur && (
          <p className="alerte" role="alert">
            {erreur}
          </p>
        )}

        <div className="confirmmodal-actions">
          <button type="button" className="btn btn--ghost" onClick={onAnnuler}>
            Annuler
          </button>
          {aConfirmer ? (
            <button type="button" className="btn btn--danger" disabled={enCours} onClick={() => void envoyer(true)}>
              Bloquer quand même
            </button>
          ) : (
            <button type="submit" className="btn btn--primary" disabled={enCours}>
              {enCours ? "Blocage…" : "Bloquer"}
            </button>
          )}
        </div>
      </form>
    </div>
  );
}

export function TraficView() {
  const [fenetre, setFenetre] = useState<FenetreTrafic>("1h");
  const [trafic, setTrafic] = useState<TraficResponse | null>(null);
  const [blocages, setBlocages] = useState<Blocage[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [retour, setRetour] = useState<string | null>(null);
  const [recherche, setRecherche] = useState("");
  const [modale, setModale] = useState<{ cible: Cible | null } | null>(null);
  const [enCoursId, setEnCoursId] = useState<string | null>(null);
  const [chargement, setChargement] = useState(false);

  const recharger = useCallback(async (f: FenetreTrafic) => {
    setChargement(true);
    try {
      const [t, b] = await Promise.all([fetchTrafic(f), listBlocages()]);
      setTrafic(t);
      setBlocages(b);
      setErreur(null);
    } catch (e) {
      setErreur(message(e, "Erreur de chargement"));
    } finally {
      setChargement(false);
    }
  }, []);

  useEffect(() => {
    void recharger(fenetre);
  }, [recharger, fenetre]);

  const visibles = useMemo(() => {
    const clients = trafic?.clients ?? [];
    const q = recherche.trim().toLowerCase();
    if (!q) return clients;
    return clients.filter(
      (c) =>
        c.ip.toLowerCase().includes(q) ||
        c.user_agent.toLowerCase().includes(q) ||
        (c.compte_email ?? "").toLowerCase().includes(q) ||
        c.chemins.some((ch) => ch.chemin.toLowerCase().includes(q)),
    );
  }, [trafic, recherche]);

  const debloquer = async (b: Blocage) => {
    setEnCoursId(b.id);
    setErreur(null);
    setRetour(null);
    try {
      await supprimerBlocage(b.id);
      setRetour(`${LIBELLE_TYPE[b.type]} ${b.valeur} débloquée.`);
      await recharger(fenetre);
    } catch (e) {
      setErreur(message(e, "Déblocage impossible"));
    } finally {
      setEnCoursId(null);
    }
  };

  const apresBlocage = async (b: Blocage) => {
    setModale(null);
    setRetour(
      `${LIBELLE_TYPE[b.type]} ${b.valeur} bloquée ${b.expire_le ? `jusqu'au ${dateLisible(b.expire_le)}` : "sans limite de durée"}.`,
    );
    await recharger(fenetre);
  };

  if (erreur && !trafic) {
    return (
      <section className="view trafic-view">
        <p className="alerte" role="alert">
          {erreur}
        </p>
        <div>
          <button type="button" className="btn" onClick={() => void recharger(fenetre)}>
            Réessayer
          </button>
        </div>
      </section>
    );
  }

  if (!trafic || !blocages) {
    return (
      <section className="view trafic-view">
        <p className="muted">Chargement…</p>
      </section>
    );
  }

  const mode = MODES[trafic.mode];
  const compte = trafic.comptage_actif;
  const r = trafic.resume;
  const libelleFenetre = LIBELLE_FENETRE[trafic.fenetre];
  const nbIpBloquees = r.ip_bloquees;

  return (
    <section className="view trafic-view">
      <div className="trafic-mode" role="status" data-mode={trafic.mode}>
        <span className={`pill dot ${mode.ton}`}>{mode.pastille}</span>
        <p>{mode.texte(trafic.variable, trafic)}</p>
      </div>

      <div className="page-outils">
        <Onglets
          onglets={FENETRES}
          actif={fenetre}
          onChoisir={setFenetre}
          label="Fenêtre de temps"
          prefixeId="trafic-fenetre"
          controle="trafic-clients"
        />
        <ActionsDePage>
          <button type="button" className="btn" disabled={chargement} onClick={() => void recharger(fenetre)}>
            <RefreshCw size={16} aria-hidden="true" />
            Actualiser
          </button>
          <button type="button" className="btn btn--primary" onClick={() => setModale({ cible: null })}>
            <ShieldBan size={16} aria-hidden="true" />
            Bloquer une adresse…
          </button>
        </ActionsDePage>
      </div>

      <Tuiles label="Sommaire du trafic">
        <Tuile
          libelle={`Requêtes (${libelleFenetre})`}
          valeur={compte ? NOMBRE.format(r.requetes) : "—"}
          detail={compte ? "fichiers statiques non comptés" : "comptage désactivé"}
        />
        <Tuile
          libelle="Clients distincts"
          valeur={compte ? NOMBRE.format(r.clients) : "—"}
          detail={compte ? "adresses IP vues" : "comptage désactivé"}
        />
        <Tuile
          libelle="Refus (429)"
          valeur={compte ? NOMBRE.format(r.depassements) : "—"}
          detail={
            !compte
              ? "comptage désactivé"
              : trafic.mode === "enforce"
                ? "requêtes au-delà du budget, refusées"
                : "au-delà du budget : auraient été refusées"
          }
          ton={compte && r.depassements > 0 ? "warn" : undefined}
          nul={compte && r.depassements === 0}
        />
        <Tuile
          libelle="IP bloquées"
          valeur={NOMBRE.format(nbIpBloquees)}
          detail={`${blocages.length} blocage${blocages.length > 1 ? "s" : ""} actif${blocages.length > 1 ? "s" : ""} en tout`}
          nul={nbIpBloquees === 0}
        />
      </Tuiles>

      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}
      <div className="page-retour" role="status" aria-live="polite">
        {retour}
      </div>

      <section className="panel carte-tableau" id="trafic-clients" aria-labelledby="trafic-clients-titre">
        <div className="carte-tete">
          <h2 id="trafic-clients-titre">
            Plus gros clients <span className="carte-tete-nb">{visibles.length}</span>
          </h2>
          <ChampRecherche
            className="trafic-recherche"
            libelle="Filtrer les clients"
            placeholder="IP, User-Agent, chemin, compte"
            valeur={recherche}
            onChange={setRecherche}
          />
        </div>
        {!compte ? (
          <p className="carte-vide">
            Comptage désactivé : le serveur ne compte rien tant que {trafic.variable} vaut « off ». Pour un premier
            diagnostic sans rien activer, analyser les journaux d'accès avec <code>scripts/analyser_acces.py</code>.
          </p>
        ) : visibles.length === 0 ? (
          <p className="carte-vide">
            {trafic.clients.length === 0 ? `Aucune requête sur les dernières ${libelleFenetre}.` : "Aucun client ne correspond à ce filtre."}
          </p>
        ) : (
          <div className="trafic-defile">
            <table className="ref trafic-table">
              <thead>
                <tr>
                  <th scope="col">Client</th>
                  <th scope="col" className="num">
                    15 min
                  </th>
                  <th scope="col" className="num">
                    1 h
                  </th>
                  <th scope="col" className="num">
                    24 h
                  </th>
                  <th scope="col" className="num trafic-optionnel" title="Part des requêtes sans compte">
                    Public
                  </th>
                  <th scope="col" className="trafic-optionnel">
                    User-Agent
                  </th>
                  <th scope="col" className="trafic-optionnel">
                    Chemins
                  </th>
                  <th scope="col" className="num">
                    Refus
                  </th>
                  <th scope="col">
                    <span className="sr-only">Action</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visibles.map((c) => (
                  <LigneClient key={c.ip} c={c} onBloquer={(cible) => setModale({ cible })} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="carte-note">
          Budgets par client :{" "}
          {trafic.budgets.map((b, i) => (
            <span key={b.categorie} title={b.description}>
              {i > 0 ? " · " : ""}
              {LIBELLE_CATEGORIE[b.categorie] ?? b.categorie} {NOMBRE.format(b.nombre)}/{periodeLisible(b.periode_s)}
            </span>
          ))}
          . Bannissement après {trafic.bannissement.seuil} refus en {dureeLisible(trafic.bannissement.fenetre_s)}.
          {trafic.exemptes.length > 0 ? ` Jamais limités : ${trafic.exemptes.join(", ")}.` : ""} Réglages :
          variables <code>CAL_IUT_AA_*</code> (docs/ANTI-ASPIRATION.md).
        </p>
      </section>

      <section className="panel carte-tableau" aria-labelledby="trafic-blocages-titre">
        <div className="carte-tete">
          <h2 id="trafic-blocages-titre">
            Blocages <span className="carte-tete-nb">{blocages.length}</span>
          </h2>
          <span className="carte-tete-note">
            {trafic.mode === "off" ? "préparés : s'appliqueront à l'activation" : "refus 403 immédiat"}
          </span>
        </div>
        {blocages.length === 0 ? (
          <p className="carte-vide">Aucun blocage.</p>
        ) : (
          <div className="trafic-defile">
            <table className="ref trafic-blocages">
              <thead>
                <tr>
                  <th scope="col">Cible</th>
                  <th scope="col">Motif</th>
                  <th scope="col" className="trafic-optionnel">
                    Par
                  </th>
                  <th scope="col">Jusqu'à</th>
                  <th scope="col">
                    <span className="sr-only">Action</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {blocages.map((b) => (
                  <tr key={b.id}>
                    <th scope="row">
                      <span className="trafic-ip">{b.valeur}</span>
                      <div className="muted trafic-sous">{LIBELLE_TYPE[b.type]}</div>
                    </th>
                    <td>
                      {b.motif}
                      {b.automatique ? (
                        <>
                          {" "}
                          <span className="pill">automatique</span>
                        </>
                      ) : null}
                    </td>
                    <td className="trafic-optionnel muted">{b.auteur}</td>
                    <td>{b.expire_le ? dateLisible(b.expire_le) : "permanent"}</td>
                    <td className="trafic-col-action">
                      <button
                        type="button"
                        className="btn btn--sm"
                        disabled={enCoursId === b.id}
                        onClick={() => void debloquer(b)}
                        aria-label={`Débloquer ${b.valeur}`}
                      >
                        Débloquer
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {modale && (
        <BloquerModal cible={modale.cible} onFait={(b) => void apresBlocage(b)} onAnnuler={() => setModale(null)} />
      )}
    </section>
  );
}

function LigneClient({ c, onBloquer }: { c: ClientTrafic; onBloquer: (cible: Cible) => void }) {
  const refus = c.depassements + c.refus_403;
  return (
    <tr>
      <th scope="row">
        <span className="trafic-ip">{c.ip}</span>
        <div className="muted trafic-sous">
          {c.compte_email ?? LIBELLE_CATEGORIE[c.categorie] ?? c.categorie}
          {c.liens_distincts > 3 ? ` · ${c.liens_distincts} liens différents` : ""} · {ilYA(c.dernier_passage)}
        </div>
      </th>
      <td className="num">{NOMBRE.format(c.requetes_15min)}</td>
      <td className="num">{NOMBRE.format(c.requetes_1h)}</td>
      <td className="num">{NOMBRE.format(c.requetes_24h)}</td>
      <td className="num trafic-optionnel">{Math.round(c.part_publique * 100)} %</td>
      <td className="trafic-optionnel trafic-ua" title={c.user_agent}>
        {c.user_agent || <span className="muted">(vide)</span>}
      </td>
      <td className="trafic-optionnel trafic-chemins">
        {c.chemins.slice(0, 2).map((ch) => (
          <div key={ch.chemin} title={`${ch.nb} requêtes`}>
            <code>{ch.chemin}</code>
          </div>
        ))}
      </td>
      <td className="num" title={`${c.depassements} au-delà du budget, ${c.refus_403} refus 403`}>
        {refus > 0 ? <strong>{NOMBRE.format(refus)}</strong> : <span className="muted">0</span>}
      </td>
      <td className="trafic-col-action">
        {c.blocage_id ? (
          <span className="pill dot bad">bloqué</span>
        ) : (
          <button
            type="button"
            className="btn btn--sm"
            aria-label={`Bloquer ${c.ip}…`}
            onClick={() => onBloquer({ type: "ip", valeur: c.ip, ip: c.ip, userAgent: c.user_agent })}
          >
            Bloquer…
          </button>
        )}
      </td>
    </tr>
  );
}
