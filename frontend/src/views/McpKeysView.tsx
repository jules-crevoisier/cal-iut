/**
 * Clés API du compte connecté — brut affiché une seule fois à la génération.
 *
 * Anciennement « Clés MCP » (renommé 05/09/2026, retour utilisateur) : la
 * même clé `caliut_…` sert de Bearer sur N'IMPORTE QUELLE route protégée,
 * pas seulement `/mcp` — notamment pour un accès programmatique à la
 * production (`cal-iut prod diff/pull/push`, `CAL_IUT_PROD_API_KEY`) sans
 * donner l'email/mot de passe d'un compte personnel. Le composant s'appelle
 * encore `McpKeysView`/`McpKey` côté code — seul le libellé visible change.
 *
 * Refonte du 29/09/2026 : la clé neuve s'affiche dans un encadré qu'on ne
 * peut pas manquer, avec de quoi la coller directement là où elle sert (la
 * valeur « Bearer … » exacte qu'attend Claude.ai, l'adresse du serveur MCP,
 * le bloc de configuration Claude Code / Cursor — cf. docs/MCP.md). Révoquer
 * est irréversible : confirmé.
 */

import { useCallback, useEffect, useState } from "react";

import { createMcpKey, listMcpKeys, revokeMcpKey } from "../api/client";
import type { McpKey } from "../api/client";
import { CopyButton } from "../components/CopyButton";
import { confirmAsync } from "../utils/confirmDialog";
import "./McpKeysView.css";

const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", year: "numeric" });

function dateCourte(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : DATE.format(d);
}

function configurationFichier(url: string, cle: string): string {
  return JSON.stringify(
    { mcpServers: { "cal-iut": { type: "http", url, headers: { Authorization: `Bearer ${cle}` } } } },
    null,
    2,
  );
}

export function McpKeysView() {
  const [cles, setCles] = useState<McpKey[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);
  const [brutUneFois, setBrutUneFois] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const urlMcp = `${window.location.origin}/mcp`;

  const recharger = useCallback(async () => {
    try {
      setCles(await listMcpKeys());
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Erreur de chargement");
    }
  }, []);

  useEffect(() => {
    void recharger();
  }, [recharger]);

  const generer = async () => {
    setEnCours(true);
    setErreur(null);
    setMessage(null);
    try {
      const creee = await createMcpKey();
      setBrutUneFois(creee.token);
      setCles((prev) => (prev ? [...prev, creee] : [creee]));
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Erreur");
    } finally {
      setEnCours(false);
    }
  };

  const revoquer = async (cle: McpKey) => {
    const ok = await confirmAsync(
      `La clé ${cle.prefix}… cessera immédiatement de fonctionner : les connecteurs et scripts qui l’utilisent ` +
        "recevront une erreur 401 jusqu’à ce qu’on leur donne une nouvelle clé.",
      { title: "Révoquer cette clé", confirmLabel: "Révoquer", variant: "danger" },
    );
    if (!ok) return;
    setEnCours(true);
    setErreur(null);
    setMessage(null);
    try {
      await revokeMcpKey(cle.id);
      setCles((prev) => (prev ? prev.filter((c) => c.id !== cle.id) : prev));
      setBrutUneFois(null);
      setMessage(`Clé ${cle.prefix}… révoquée.`);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Erreur");
    } finally {
      setEnCours(false);
    }
  };

  if (erreur && !cles) {
    return (
      <section className="view cles">
        <p className="alerte" role="alert">
          {erreur}
        </p>
      </section>
    );
  }

  if (!cles) {
    return (
      <section className="view cles">
        <p className="muted">Chargement…</p>
      </section>
    );
  }

  return (
    <section className="view cles">
      <div className="panel cles-intro">
        <div>
          <h2>Vos clés d’accès</h2>
          <p className="muted">
            Une clé permet à Claude (connecteur MCP) ou à un script (<code>cal-iut prod diff/pull/push</code>) d’agir
            avec les droits de votre compte, sans votre mot de passe. Prévoyez une clé par usage : on en révoque une
            sans casser les autres.
          </p>
        </div>
        <button type="button" className="btn btn--primary" disabled={enCours} onClick={() => void generer()}>
          {enCours ? "Génération…" : "Générer une clé"}
        </button>
      </div>

      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}
      <div className="cles-message" role="status" aria-live="polite">
        {message}
      </div>

      {brutUneFois && (
        <section className="panel cles-nouvelle" aria-labelledby="cles-nouvelle-titre">
          <h2 id="cles-nouvelle-titre">Copiez cette clé maintenant</h2>
          <p className="cles-avertissement">
            Elle ne sera plus jamais réaffichée. Ne la collez ni dans un chat, ni dans un commit, ni sur une capture.
          </p>
          <div className="cles-brut">
            <code className="mcp-key-brut">{brutUneFois}</code>
            <CopyButton text={brutUneFois} idleLabel="Copier la clé" className="btn btn--primary" />
          </div>

          <dl className="cles-usages">
            <div>
              <dt>Claude.ai — en-tête <code>authorization</code></dt>
              <dd>
                <code>Bearer {brutUneFois.slice(0, 12)}…</code>
                <CopyButton text={`Bearer ${brutUneFois}`} idleLabel="Copier la valeur" />
              </dd>
            </div>
            <div>
              <dt>Adresse du serveur MCP</dt>
              <dd>
                <code>{urlMcp}</code>
                <CopyButton text={urlMcp} idleLabel="Copier l’adresse" />
              </dd>
            </div>
            <div>
              <dt>Claude Code, Cursor — bloc de configuration</dt>
              <dd>
                <code>{"{ \"mcpServers\": { \"cal-iut\": … } }"}</code>
                <CopyButton text={() => configurationFichier(urlMcp, brutUneFois)} idleLabel="Copier le bloc" />
              </dd>
            </div>
          </dl>

          <div>
            <button type="button" className="btn" onClick={() => setBrutUneFois(null)}>
              J’ai copié la clé
            </button>
          </div>
        </section>
      )}

      <section className="panel" aria-labelledby="cles-actives-titre">
        <h2 id="cles-actives-titre">Clés actives ({cles.length})</h2>
        {cles.length === 0 ? (
          <p className="muted">Aucune clé pour l’instant. « Générer une clé » en crée une, affichée une seule fois.</p>
        ) : (
          <div className="ref-table-wrap">
            <table className="ref cles-table">
              <thead>
                <tr>
                  <th scope="col">Clé</th>
                  <th scope="col">Créée le</th>
                  <th scope="col">Dernière utilisation</th>
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {cles.map((cle) => (
                  <tr key={cle.id}>
                    <td>
                      <strong className="mono">{cle.prefix}</strong>
                    </td>
                    <td>{dateCourte(cle.created_at)}</td>
                    <td className={cle.last_used_at ? undefined : "muted"}>
                      {cle.last_used_at ? dateCourte(cle.last_used_at) : "jamais"}
                    </td>
                    <td className="cles-col-actions">
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm cles-revoquer"
                        disabled={enCours}
                        onClick={() => void revoquer(cle)}
                      >
                        Révoquer
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}
