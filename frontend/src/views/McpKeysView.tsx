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
 * est irréversible : confirmé. Refonte v2 (même jour) : l'explication et
 * l'action sur une barre à plat, les clés dans une carte-tableau.
 *
 * Variante « Accès API » (29/09/2026, `variante="api"`) : l'UNIQUE écran d'un
 * compte `api` (cf. `api/accounts.py::ROLE_API`), qui ne voit aucune donnée
 * dans l'appli et dont les clés ne lisent que `/api/v1` — donc pas de
 * connecteur MCP ici, mais la documentation de l'API et deux exemples prêts
 * à coller. Les clés portent un nom (tous les comptes) pour les reconnaître.
 */

import { useCallback, useEffect, useId, useState } from "react";
import { BookOpen, KeyRound } from "lucide-react";

import { createMcpKey, listMcpKeys, revokeMcpKey } from "../api/client";
import type { McpKey } from "../api/client";
import { CopyButton } from "../components/CopyButton";
import { confirmAsync } from "../utils/confirmDialog";
import "../styles/outils.css";
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

/** Exemples `curl` de la page « Accès API » : `$CLE` tant qu'aucune clé
 *  neuve n'est affichée (une clé enregistrée n'est jamais relisible). */
export function exemplesCurl(origine: string, cle = "$CLE"): string {
  return [
    `curl -H "Authorization: Bearer ${cle}" ${origine}/api/v1/version`,
    `curl -H "Authorization: Bearer ${cle}" ${origine}/api/v1/export`,
  ].join("\n");
}

export function McpKeysView({ variante = "compte" }: { variante?: "compte" | "api" }) {
  const acces = variante === "api";
  const idNom = useId();
  const [nom, setNom] = useState("");
  const [cles, setCles] = useState<McpKey[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);
  const [brutUneFois, setBrutUneFois] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const origine = window.location.origin;
  const urlMcp = `${origine}/mcp`;

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
      const creee = await createMcpKey(nom);
      setBrutUneFois(creee.token);
      setNom("");
      setCles((prev) => (prev ? [...prev, creee] : [creee]));
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Erreur");
    } finally {
      setEnCours(false);
    }
  };

  const revoquer = async (cle: McpKey) => {
    const ok = await confirmAsync(
      `La clé ${cle.nom ? `« ${cle.nom} » (${cle.prefix}…)` : `${cle.prefix}…`} cessera immédiatement de fonctionner : ` +
        `les ${acces ? "applications" : "connecteurs"} et scripts qui l’utilisent ` +
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
      setMessage(`Clé ${cle.nom ? `« ${cle.nom} »` : `${cle.prefix}…`} révoquée.`);
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

  const plein = cles.length >= 5;

  return (
    <section className={`view cles${acces ? " cles--api" : ""}`}>
      <div className="page-outils cles-outils">
        {acces ? (
          <p className="page-note">
            Ce compte ne montre aucune donnée dans l’appli : il sert à lire l’emploi du temps depuis un script ou une
            application, avec une clé. Chaque clé lit l’API v1 <strong>en lecture seule</strong>, sans votre mot de
            passe. Prévoyez une clé par usage : on en révoque une sans casser les autres.
          </p>
        ) : (
          <p className="page-note">
            Une clé agit avec les droits de votre compte, sans votre mot de passe — connecteur MCP de Claude ou script (
            <code>cal-iut prod diff/pull/push</code>). Prévoyez une clé par usage : on en révoque une sans casser les
            autres.
          </p>
        )}
        <form
          className="cles-generer"
          onSubmit={(e) => {
            e.preventDefault();
            void generer();
          }}
        >
          <label htmlFor={idNom} className="sr-only">
            Nom de la nouvelle clé (facultatif)
          </label>
          <input
            id={idNom}
            type="text"
            value={nom}
            maxLength={60}
            placeholder={acces ? "Nom : écran du hall, script…" : "Nom : Claude, script prod…"}
            onChange={(e) => setNom(e.target.value)}
            disabled={enCours || plein}
          />
          <button type="submit" className="btn btn--primary" disabled={enCours || plein}>
            <KeyRound size={16} aria-hidden="true" />
            {enCours ? "Génération…" : "Générer une clé"}
          </button>
        </form>
      </div>
      {plein && (
        <p className="muted cles-plein">5 clés actives au plus : révoquez-en une pour en générer une autre.</p>
      )}

      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}
      <div className="page-retour" role="status" aria-live="polite">
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

          {acces ? (
            <dl className="cles-usages">
              <div>
                <dt>
                  En-tête de chaque requête
                </dt>
                <dd>
                  <code>Authorization: Bearer {brutUneFois.slice(0, 12)}…</code>
                  <CopyButton text={`Authorization: Bearer ${brutUneFois}`} idleLabel="Copier l’en-tête" />
                </dd>
              </div>
              <div>
                <dt>Essayer tout de suite</dt>
                <dd>
                  <code>curl … {origine}/api/v1/version</code>
                  <CopyButton text={() => exemplesCurl(origine, brutUneFois)} idleLabel="Copier les exemples" />
                </dd>
              </div>
            </dl>
          ) : (
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
          )}

          <div>
            <button type="button" className="btn" onClick={() => setBrutUneFois(null)}>
              J’ai copié la clé
            </button>
          </div>
        </section>
      )}

      <section className="panel carte-tableau" aria-labelledby="cles-actives-titre">
        <div className="carte-tete">
          <h2 id="cles-actives-titre">
            Clés actives <span className="carte-tete-nb">{cles.length}</span>
          </h2>
        </div>
        {cles.length === 0 ? (
          <p className="carte-vide">Aucune clé pour l’instant. « Générer une clé » en crée une, affichée une seule fois.</p>
        ) : (
          <div>
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
                    <td data-label="Clé">
                      {cle.nom ? (
                        <>
                          <strong>{cle.nom}</strong>
                          <div className="mono muted cles-prefixe">{cle.prefix}</div>
                        </>
                      ) : (
                        <strong className="mono">{cle.prefix}</strong>
                      )}
                    </td>
                    <td data-label="Créée le">{dateCourte(cle.created_at)}</td>
                    <td data-label="Dernière utilisation" className={cle.last_used_at ? undefined : "muted"}>
                      {cle.last_used_at ? dateCourte(cle.last_used_at) : "jamais"}
                    </td>
                    <td className="cles-col-actions">
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm cles-revoquer"
                        disabled={enCours}
                        aria-label={`Révoquer la clé ${cle.nom ?? cle.prefix}`}
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

      {acces && (
        <section className="panel cles-doc" aria-labelledby="cles-doc-titre">
          <div className="cles-doc-tete">
            <h2 id="cles-doc-titre">Utiliser l’API</h2>
            <a className="btn" href="/api/v1/docs" target="_blank" rel="noopener noreferrer">
              <BookOpen size={16} aria-hidden="true" />
              Documentation de l’API
            </a>
          </div>
          <p className="cles-doc-note">
            Chaque requête porte l’en-tête <code>Authorization: Bearer caliut_…</code>. Sondez{" "}
            <code>/api/v1/version</code> et ne relisez les données (<code>/api/v1/export</code>, tout en un appel) que
            quand la révision change. Au plus 600 requêtes par minute. Schéma brut :{" "}
            <a href="/api/v1/openapi.json" target="_blank" rel="noopener noreferrer">
              /api/v1/openapi.json
            </a>
            .
          </p>
          <div className="cles-exemple">
            <pre>
              <code>{`export CLE=caliut_…\n${exemplesCurl(origine)}`}</code>
            </pre>
            <CopyButton text={() => exemplesCurl(origine)} idleLabel="Copier" />
          </div>
        </section>
      )}
    </section>
  );
}
