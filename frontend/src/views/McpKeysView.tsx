/**
 * Clés API du compte connecté — brut affiché une seule fois à la génération.
 * Réutilise le vocabulaire visuel des comptes admin (liste + actions).
 *
 * Anciennement « Clés MCP » (renommé 05/09/2026, retour utilisateur) : la
 * même clé `caliut_…` sert désormais de Bearer sur N'IMPORTE QUELLE route
 * protégée, pas seulement `/mcp` — notamment pour un accès programmatique
 * à la production (`cal-iut prod diff/pull/push`, `CAL_IUT_PROD_API_KEY`)
 * sans donner l'email/mot de passe d'un compte personnel. Le composant
 * s'appelle encore `McpKeysView`/`McpKey` côté code (`api/mcp-keys`, table
 * `McpKey`) — seul le libellé visible change, pas l'API ni le schéma.
 */

import { useCallback, useEffect, useState } from "react";

import { createMcpKey, listMcpKeys, revokeMcpKey } from "../api/client";
import type { McpKey } from "../api/client";
import { CopyButton } from "../components/CopyButton";

export function McpKeysView() {
  const [cles, setCles] = useState<McpKey[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);
  const [brutUneFois, setBrutUneFois] = useState<string | null>(null);

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

  const revoquer = async (id: number) => {
    setEnCours(true);
    setErreur(null);
    try {
      await revokeMcpKey(id);
      setCles((prev) => (prev ? prev.filter((c) => c.id !== id) : prev));
      setBrutUneFois(null);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Erreur");
    } finally {
      setEnCours(false);
    }
  };

  if (erreur && !cles) {
    return (
      <section className="view">
        <div className="panel">
          <p className="alerte" role="alert">
            {erreur}
          </p>
        </div>
      </section>
    );
  }

  if (!cles) {
    return (
      <section className="view">
        <div className="panel">
          <p className="muted">Chargement…</p>
        </div>
      </section>
    );
  }

  return (
    <section className="view">
      <div className="panel">
        <h3>Clé API</h3>
        <p className="muted">
          Une clé par usage (connecteur MCP type Claude/Cursor, ou accès programmatique à
          l’application — <code>cal-iut prod diff/pull/push</code> par exemple). Elle n’est
          affichée qu’une fois : copiez-la tout de suite. Le cookie de session du site ne sert
          jamais à l’authentification par clé.
        </p>
        {erreur && (
          <p className="alerte" role="alert">
            {erreur}
          </p>
        )}
        <button type="button" className="btn btn--primary" disabled={enCours} onClick={() => void generer()}>
          Générer une clé
        </button>
      </div>

      {brutUneFois && (
        <div className="panel">
          <h3>Copiez cette clé maintenant</h3>
          <p className="muted">Elle ne sera plus jamais réaffichée. Collez-la dans Authorization : Bearer …</p>
          <p className="mono mcp-key-brut">{brutUneFois}</p>
          <CopyButton text={brutUneFois} idleLabel="Copier la clé" />
        </div>
      )}

      <div className="panel">
        <h3>Clés actives ({cles.length})</h3>
        {cles.length === 0 ? (
          <p className="muted">Aucune clé pour l’instant.</p>
        ) : (
          <ul className="admin-users-list">
            {cles.map((cle) => (
              <li key={cle.id} className="admin-users-row">
                <div className="admin-users-identite">
                  <strong className="mono">{cle.prefix}</strong>
                  <span className="muted">créée {cle.created_at.slice(0, 10)}</span>
                </div>
                <div className="admin-users-actions">
                  <button
                    type="button"
                    className="btn btn--danger"
                    disabled={enCours}
                    onClick={() => void revoquer(cle.id)}
                  >
                    Révoquer
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
