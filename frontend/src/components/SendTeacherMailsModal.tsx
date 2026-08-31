import { useEffect, useMemo, useState } from "react";

import {
  apercuMailProf,
  fetchTeacherMailPreview,
  sendTeacherMails,
  type TeacherMailPreview,
  type TeacherMailSendResult,
} from "../api/client";

interface SendTeacherMailsModalProps {
  onClose: () => void;
}

/** Écran d'envoi du lien perso par mail (Référentiel > Liens & partage,
 * retour utilisateur 28/08/2026 : « on veux une fonctionnalité qui permet
 * d'envoyer automatiquement un mail à chaque prof avec leur lien »).
 * Sélection TOUJOURS explicite (jamais un « tout le monde » pré-coché sans
 * regard) : un enseignant déjà contacté est affiché mais décoché par défaut,
 * pour qu'un ré-envoi accidentel demande un geste conscient. */
export function SendTeacherMailsModal({ onClose }: SendTeacherMailsModalProps) {
  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "error"; message: string }
    | {
        status: "ready";
        configured: boolean;
        aLaClefApi: boolean;
        aUrlPublique: boolean;
        teachers: TeacherMailPreview[];
      }
  >({ status: "loading" });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sending, setSending] = useState(false);
  const [results, setResults] = useState<TeacherMailSendResult[] | null>(null);
  // Aperçu du mail RÉEL avant envoi (retour utilisateur 28/08/2026) — on
  // n'envoie pas à 32 personnes sans avoir pu relire le message.
  const [apercu, setApercu] = useState<{ code: string; subject: string; text: string } | null>(null);
  const [apercuEnCours, setApercuEnCours] = useState(false);

  const ouvrirApercu = async (code: string) => {
    setApercuEnCours(true);
    try {
      const a = await apercuMailProf(code);
      setApercu({ code, subject: a.subject, text: a.text });
    } catch (err) {
      setState({ status: "error", message: err instanceof Error ? err.message : "Aperçu indisponible" });
    } finally {
      setApercuEnCours(false);
    }
  };

  const dateCourte = (iso: string) => new Date(iso).toLocaleDateString("fr-FR");

  useEffect(() => {
    fetchTeacherMailPreview()
      .then((data) => {
        setState({
          status: "ready",
          configured: data.configured,
          aLaClefApi: data.a_la_clef_api,
          aUrlPublique: data.a_url_publique,
          teachers: data.teachers,
        });
        // Pré-coché : adresse connue ET jamais encore contacté — pas les
        // deux autres cas (pas d'adresse : rien à cocher ; déjà envoyé :
        // geste conscient requis pour renvoyer).
        setSelected(new Set(data.teachers.filter((t) => t.email && !t.sent_at).map((t) => t.code)));
      })
      .catch((err) => setState({ status: "error", message: err instanceof Error ? err.message : "Erreur" }));
  }, []);

  const teachers = state.status === "ready" ? state.teachers : [];
  const resultByCode = useMemo(() => new Map((results ?? []).map((r) => [r.code, r])), [results]);

  const toggle = (code: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const handleSend = async () => {
    setSending(true);
    try {
      const { results: r } = await sendTeacherMails([...selected]);
      setResults(r);
      // Rafraîchit les dates d'envoi affichées sans refermer la fenêtre —
      // l'utilisateur doit voir le résultat avant de partir.
      const data = await fetchTeacherMailPreview();
      setState({
        status: "ready",
        configured: data.configured,
        aLaClefApi: data.a_la_clef_api,
        aUrlPublique: data.a_url_publique,
        teachers: data.teachers,
      });
    } catch (err) {
      setState({ status: "error", message: err instanceof Error ? err.message : "Erreur d'envoi" });
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="confirmmodal-overlay" role="presentation" onClick={onClose}>
      <div
        className="panel confirmmodal mailmodal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="mailmodal-titre"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="mailmodal-titre">Envoyer le lien personnel par mail</h3>

        {state.status === "loading" && <p className="muted">Chargement…</p>}
        {state.status === "error" && <p className="mailmodal-err">{state.message}</p>}

        {state.status === "ready" && !state.configured && (
          <p className="mailmodal-err">
            {/* Nommer précisément ce qui manque — retour utilisateur
                31/08/2026 : « j'ai bien la key dans le env » alors que
                c'était CAL_IUT_PUBLIC_URL l'absente, jamais nommée avant
                ce correctif. */}
            Envoi non configuré côté serveur : il manque{" "}
            {!state.aLaClefApi && !state.aUrlPublique ? (
              <>
                <span className="mono">RESEND_API_KEY</span> et <span className="mono">CAL_IUT_PUBLIC_URL</span>
              </>
            ) : !state.aLaClefApi ? (
              <span className="mono">RESEND_API_KEY</span>
            ) : (
              <span className="mono">CAL_IUT_PUBLIC_URL</span>
            )}{" "}
            côté serveur. Les cases restent affichées mais chaque envoi échouera tant que ce n'est pas réglé.
          </p>
        )}

        {state.status === "ready" && (
          <div className="mailmodal-list">
            {teachers.map((t) => {
              const resultat = resultByCode.get(t.code);
              return (
                <label key={t.code} className={`mailmodal-row ${!t.email ? "mailmodal-row--disabled" : ""}`}>
                  <input
                    type="checkbox"
                    checked={selected.has(t.code)}
                    disabled={!t.email}
                    onChange={() => toggle(t.code)}
                  />
                  <span className="mailmodal-name">
                    {t.name} <span className="mono muted">{t.code}</span>
                  </span>
                  <span className="mailmodal-email mono muted">{t.email ?? "adresse inconnue"}</span>
                  <span className="mailmodal-status">
                    {/* Statut PERSISTANT (retour utilisateur 28/08/2026 :
                        « une validation qui reste à côté qui dit que le mail
                        a été envoyé ») : l'issue du dernier envoi de cette
                        session prime, sinon on retombe sur le journal, qui
                        lui survit aux rechargements et redémarrages. */}
                    {resultat && !resultat.ok ? (
                      <span className="mailmodal-err" title={resultat.error ?? ""}>Échec ✗</span>
                    ) : t.opened_at ? (
                      <span className="mailmodal-ok" title={`Ouverture détectée le ${dateCourte(t.opened_at)}`}>
                        Lu ✓✓
                      </span>
                    ) : t.sent_at ? (
                      <span className="mailmodal-ok">Envoyé le {dateCourte(t.sent_at)}</span>
                    ) : null}
                    {t.email && (
                      <button
                        type="button"
                        className="mailmodal-apercu"
                        disabled={apercuEnCours}
                        onClick={(e) => {
                          e.preventDefault(); // dans un <label> : ne pas cocher la case
                          void ouvrirApercu(t.code);
                        }}
                      >
                        Aperçu
                      </button>
                    )}
                  </span>
                </label>
              );
            })}
          </div>
        )}

        {apercu && (
          <div className="mailapercu">
            <div className="mailapercu-tete">
              <strong>Aperçu — {apercu.code}</strong>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => setApercu(null)}>
                Fermer l'aperçu
              </button>
            </div>
            <div className="mailapercu-sujet">Objet : {apercu.subject}</div>
            {/* Le texte brut du mail, tel quel — `white-space: pre-wrap` en
                CSS pour conserver les retours à la ligne réels du message. */}
            <pre className="mailapercu-corps">{apercu.text}</pre>
          </div>
        )}

        <div className="confirmmodal-actions">
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Fermer
          </button>
          {state.status === "ready" && (
            <button type="button" className="btn btn--accent" disabled={sending || selected.size === 0} onClick={handleSend}>
              {sending ? "Envoi…" : `Envoyer (${selected.size})`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
