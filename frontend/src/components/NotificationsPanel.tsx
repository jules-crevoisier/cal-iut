/**
 * Réglage des notifications par mail — retour utilisateur 29/08/2026 :
 * « fais en sorte que l'on puisse configurer pour quoi les mails partent
 * dans l'interface, et que l'on puisse modifier l'email et en ajouter
 * plusieurs en même temps ».
 *
 * Deux partis pris d'ergonomie, tirés de cette phrase :
 *
 * - les destinataires se saisissent dans UN champ, séparés par virgule ou
 *   retour à la ligne : « en ajouter plusieurs en même temps » veut dire
 *   coller une liste, pas cliquer huit fois sur « + » ;
 * - rien n'est actif par défaut, et l'écran le dit — une fonctionnalité
 *   d'envoi de mail ne doit jamais s'allumer toute seule.
 */

import { useEffect, useState } from "react";

import { lireNotifications, testerNotifications, ecrireNotifications } from "../api/client";
import type { NotificationConfig } from "../types";
import "./NotificationsPanel.css";

export function NotificationsPanel() {
  const [cfg, setCfg] = useState<NotificationConfig | null>(null);
  const [saisie, setSaisie] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [occupe, setOccupe] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const c = await lireNotifications();
        setCfg(c);
        setSaisie(c.destinataires.join(", "));
      } catch (e) {
        setErreur(e instanceof Error ? e.message : "Configuration illisible");
      }
    })();
  }, []);

  if (!cfg) {
    return (
      <div className="panel">
        <h3>Notifications par mail</h3>
        <p className="muted">{erreur ?? "Chargement…"}</p>
      </div>
    );
  }

  const appliquer = async (patch: Parameters<typeof ecrireNotifications>[0]) => {
    setOccupe(true);
    setErreur(null);
    setMessage(null);
    try {
      const c = await ecrireNotifications(patch);
      setCfg(c);
      setSaisie(c.destinataires.join(", "));
      setMessage("Enregistré.");
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Enregistrement impossible");
    } finally {
      setOccupe(false);
    }
  };

  const enregistrerDestinataires = () =>
    // Virgule, point-virgule, espace ou retour à la ligne : on accepte tout
    // ce qu'un copier-coller peut produire plutôt que d'imposer un format.
    appliquer({ destinataires: saisie.split(/[\s,;]+/).filter(Boolean) });

  const actifs = Object.values(cfg.evenements).filter(Boolean).length;
  const saisieModifiee =
    saisie.split(/[\s,;]+/).filter(Boolean).join(",") !== cfg.destinataires.join(",");
  const actif = cfg.destinataires.length > 0 && actifs > 0;

  return (
    <div className="panel notif">
      <header className="notif-tete">
        <h3>Notifications par mail</h3>
        <span className={`pill dot ${actif && cfg.mail_configure ? "good" : ""}`}>
          {actif
            ? `${actifs} événement${actifs > 1 ? "s" : ""} suivi${actifs > 1 ? "s" : ""}, ${cfg.destinataires.length} destinataire${cfg.destinataires.length > 1 ? "s" : ""}`
            : `Inactives : ${cfg.destinataires.length === 0 ? "aucun destinataire" : "aucun événement coché"}`}
        </span>
      </header>
      <p className="notif-intro">
        Un résumé groupé part quand le planning change : les modifications d'une même rafale tiennent dans un seul
        mail (une réorganisation, c'est vingt déplacements en dix minutes). Rien n'est actif par défaut.
      </p>

      {!cfg.mail_configure && (
        <p className="notif-alerte" role="alert">
          {/* Les DEUX variables sont nécessaires (`mailer.is_configured()`) —
              on nomme précisément ce qui manque (retour utilisateur
              31/08/2026 : « j'ai bien la key dans le env », alors que c'était
              CAL_IUT_PUBLIC_URL l'absente). */}
          L'envoi de mails n'est pas configuré sur ce serveur : il manque{" "}
          {!cfg.mail_a_la_clef_api && !cfg.mail_a_url_publique ? (
            <>
              <span className="mono">RESEND_API_KEY</span> et <span className="mono">CAL_IUT_PUBLIC_URL</span>
            </>
          ) : !cfg.mail_a_la_clef_api ? (
            <span className="mono">RESEND_API_KEY</span>
          ) : (
            <span className="mono">CAL_IUT_PUBLIC_URL</span>
          )}{" "}
          côté serveur. Les réglages ci-dessous sont gardés, mais rien ne partira.
        </p>
      )}

      <div className="notif-grille">
        <div className="notif-bloc">
          <label className="notif-champ">
            <span className="notif-libelle">Destinataires</span>
            <textarea
              value={saisie}
              onChange={(e) => setSaisie(e.target.value)}
              rows={3}
              placeholder="kyllian.bresson@univ-reims.fr, autre@exemple.fr"
              spellCheck={false}
            />
          </label>
          <p className="notif-aide">
            Plusieurs adresses à la fois : séparées par une virgule, un espace ou un retour à la ligne. Les doublons
            sont retirés à l'enregistrement.
          </p>
          <div>
            <button
              type="button"
              className="btn btn--primary btn--sm"
              onClick={enregistrerDestinataires}
              disabled={occupe || !saisieModifiee}
            >
              Enregistrer les destinataires
            </button>
          </div>
        </div>

        <div className="notif-bloc">
          <fieldset className="notif-evenements">
            <legend className="notif-libelle">Ce qui déclenche un mail</legend>
            {Object.entries(cfg.libelles).map(([cle, libelle]) => (
              <label key={cle} className="notif-case">
                <input
                  type="checkbox"
                  checked={cfg.evenements[cle] ?? false}
                  disabled={occupe}
                  onChange={(e) => void appliquer({ evenements: { [cle]: e.target.checked } })}
                />
                <span>{libelle}</span>
              </label>
            ))}
          </fieldset>

          <label className="notif-champ notif-delai">
            <span className="notif-libelle">Regrouper les modifications pendant</span>
            <select
              value={cfg.delai_minutes}
              disabled={occupe}
              onChange={(e) => void appliquer({ delai_minutes: Number(e.target.value) })}
            >
              <option value={0}>Aucun regroupement (un mail par modification)</option>
              <option value={5}>5 minutes</option>
              <option value={15}>15 minutes</option>
              <option value={60}>1 heure</option>
            </select>
          </label>
        </div>
      </div>

      <div className="notif-actions">
        <button
          type="button"
          className="btn btn--sm"
          disabled={occupe || !actif}
          title={actif ? undefined : "Il faut au moins un destinataire et un événement coché."}
          onClick={async () => {
            setOccupe(true);
            setErreur(null);
            setMessage(null);
            try {
              const r = await testerNotifications();
              setMessage(`Mail de test envoyé à ${r.envoye_a.join(", ")}.`);
            } catch (e) {
              setErreur(e instanceof Error ? e.message : "Envoi de test impossible");
            } finally {
              setOccupe(false);
            }
          }}
        >
          Envoyer un mail de test
        </button>
        {cfg.en_attente > 0 && (
          <span className="notif-aide">
            {cfg.en_attente} modification{cfg.en_attente > 1 ? "s" : ""} en attente du prochain résumé
          </span>
        )}
        <span aria-live="polite" className="notif-retour">
          {message && <span className="notif-ok">{message}</span>}
          {erreur && <span className="notif-alerte">{erreur}</span>}
        </span>
      </div>
    </div>
  );
}
