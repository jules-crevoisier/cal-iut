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

  return (
    <div className="panel">
      <h3>Notifications par mail</h3>
      <p className="muted">
        Un résumé groupé est envoyé quand le planning change. Les modifications d'une même rafale tiennent dans
        un seul mail : une réorganisation, c'est vingt déplacements en dix minutes.
      </p>

      {!cfg.mail_configure && (
        <p className="notif-alerte">
          L'envoi de mails n'est pas configuré sur ce serveur (<span className="mono">RESEND_API_KEY</span>{" "}
          manquante) : les réglages ci-dessous seront gardés, mais rien ne partira.
        </p>
      )}

      <label className="notif-champ">
        <span>Destinataires</span>
        <textarea
          value={saisie}
          onChange={(e) => setSaisie(e.target.value)}
          rows={2}
          placeholder="kyllian.bresson@univ-reims.fr, autre@exemple.fr"
          spellCheck={false}
        />
        <span className="notif-aide">
          Plusieurs adresses à la fois : séparez-les par une virgule, un espace ou un retour à la ligne. Les
          doublons sont retirés à l'enregistrement.
        </span>
      </label>
      <button type="button" className="btn btn--accent" onClick={enregistrerDestinataires} disabled={occupe}>
        Enregistrer les destinataires
      </button>

      <fieldset className="notif-evenements">
        <legend>Ce qui déclenche un mail</legend>
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
        <span>Regrouper les modifications pendant</span>
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

      <div className="notif-actions">
        <button
          type="button"
          className="btn btn--ghost"
          disabled={occupe || cfg.destinataires.length === 0 || actifs === 0}
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
          <span className="muted">{cfg.en_attente} modification(s) en attente de résumé</span>
        )}
      </div>

      {cfg.destinataires.length === 0 || actifs === 0 ? (
        <p className="muted">
          Aucune notification n'est active :{" "}
          {cfg.destinataires.length === 0 ? "aucun destinataire enregistré" : "aucun événement coché"}.
        </p>
      ) : (
        <p className="muted">
          {actifs} événement(s) suivi(s), envoyés à {cfg.destinataires.length} destinataire(s).
        </p>
      )}

      {message && <p className="notif-ok">{message}</p>}
      {erreur && <p className="notif-alerte">{erreur}</p>}
    </div>
  );
}
