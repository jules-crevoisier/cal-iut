/**
 * Gestion des comptes (31/08/2026) — activation, rôle, désactivation.
 * Réservée aux admins : le backend refuse déjà tout le reste
 * (`Depends(require_role("admin"))`), cette vue n'est simplement jamais
 * proposée dans la nav à un autre rôle (App.tsx/SideNav).
 *
 * Suppression des comptes en attente (25/09/2026, retour utilisateur Jules :
 * « des personnes qui se sont trompées ou qu'on ne veut pas, donc on veut
 * les supprimer ») — bouton « Supprimer » réservé aux DEUX statuts jamais
 * activés (`pending_email`, `pending_admin_activation`), jamais affiché sur
 * un compte `active`/`disabled` : le serveur refuse de toute façon leur
 * suppression (`api/accounts.py::PENDING_STATUSES`).
 *
 * Refonte du 29/09/2026 :
 *   - les demandes d'accès en tête, chacune avec la date de sa demande et
 *     ses trois gestes ;
 *   - les autres comptes dans un tableau (compte, statut, rôle, depuis),
 *     filtrable par statut et par adresse ;
 *   - ce que chaque rôle permet, dit une fois en tête plutôt que deviné ;
 *   - désactiver est réversible : pas de confirmation, mais un « Annuler »
 *     dans le message qui suit.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { adminDeleteUser, adminListUsers, adminUpdateUser } from "../api/client";
import type { AdminUser } from "../api/client";
import { confirmAsync } from "../utils/confirmDialog";
import "./AdminUsersView.css";

const LIBELLE_STATUT: Record<AdminUser["status"], string> = {
  pending_email: "Email non confirmé",
  pending_admin_activation: "En attente d'activation",
  active: "Actif",
  disabled: "Désactivé",
};

const TON_STATUT: Record<AdminUser["status"], string> = {
  pending_email: "",
  pending_admin_activation: "warn",
  active: "good",
  disabled: "bad",
};

const LIBELLE_ROLE: Record<AdminUser["role"], string> = {
  read_only: "Lecture seule",
  edit: "Édition",
  admin: "Admin",
};

type Filtre = "tous" | "active" | "disabled" | "pending_email";

const FILTRES: Array<{ cle: Filtre; libelle: string }> = [
  { cle: "tous", libelle: "Tous" },
  { cle: "active", libelle: "Actifs" },
  { cle: "disabled", libelle: "Désactivés" },
  { cle: "pending_email", libelle: "Email non confirmé" },
];

const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", year: "numeric" });

function dateCourte(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : DATE.format(d);
}

/** La date qui compte pour un compte : depuis quand il est dans son état. */
function depuis(u: AdminUser): string {
  if (u.status === "active" && u.activated_at) return `actif depuis le ${dateCourte(u.activated_at)}`;
  if (u.status === "pending_email") return `inscrit le ${dateCourte(u.created_at)}`;
  if (u.status === "pending_admin_activation")
    return `demande du ${dateCourte(u.email_confirmed_at ?? u.created_at)}`;
  return `inscrit le ${dateCourte(u.created_at)}`;
}

interface Message {
  texte: string;
  annuler?: { libelle: string; action: () => void };
}

export function AdminUsersView() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [message, setMessage] = useState<Message | null>(null);
  const [enCoursId, setEnCoursId] = useState<number | null>(null);
  const [filtre, setFiltre] = useState<Filtre>("tous");
  const [recherche, setRecherche] = useState("");

  const recharger = useCallback(async () => {
    try {
      setUsers(await adminListUsers());
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Erreur de chargement");
    }
  }, []);

  useEffect(() => {
    void recharger();
  }, [recharger]);

  const appliquer = async (u: AdminUser, patch: { role?: string; status?: string }, texte?: (maj: AdminUser) => Message) => {
    setEnCoursId(u.id);
    setErreur(null);
    setMessage(null);
    try {
      const maj = await adminUpdateUser(u.id, patch);
      setUsers((prev) => (prev ? prev.map((x) => (x.id === u.id ? maj : x)) : prev));
      if (texte) setMessage(texte(maj));
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Erreur");
    } finally {
      setEnCoursId(null);
    }
  };

  const supprimer = async (u: AdminUser) => {
    const confirme = await confirmAsync(`Supprimer définitivement le compte ${u.email} ?`, {
      title: "Supprimer ce compte",
      confirmLabel: "Supprimer",
      cancelLabel: "Annuler",
      variant: "danger",
    });
    if (!confirme) return;

    setEnCoursId(u.id);
    setErreur(null);
    setMessage(null);
    try {
      await adminDeleteUser(u.id);
      setUsers((prev) => (prev ? prev.filter((x) => x.id !== u.id) : prev));
      setMessage({ texte: `Compte ${u.email} supprimé.` });
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Erreur de suppression");
    } finally {
      setEnCoursId(null);
    }
  };

  const activer = (u: AdminUser, role: AdminUser["role"]) =>
    void appliquer(u, { role }, (maj) => ({ texte: `${maj.email} activé en ${LIBELLE_ROLE[role].toLowerCase()}.` }));

  const desactiver = (u: AdminUser) =>
    void appliquer(u, { status: "disabled" }, (maj) => ({
      texte: `${maj.email} désactivé : il ne peut plus se connecter.`,
      annuler: { libelle: "Annuler", action: () => void appliquer(maj, { status: "active" }, () => ({ texte: `${maj.email} réactivé.` })) },
    }));

  const reste = useMemo(() => (users ?? []).filter((u) => u.status !== "pending_admin_activation"), [users]);
  const visibles = useMemo(() => {
    const q = recherche.trim().toLowerCase();
    return reste.filter((u) => (filtre === "tous" || u.status === filtre) && (!q || u.email.toLowerCase().includes(q)));
  }, [reste, filtre, recherche]);

  if (erreur && !users) {
    return (
      <section className="view comptes">
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

  if (!users) {
    return (
      <section className="view comptes">
        <p className="muted">Chargement…</p>
      </section>
    );
  }

  const enAttente = users.filter((u) => u.status === "pending_admin_activation");
  const compte = (s: Filtre) => (s === "tous" ? reste.length : reste.filter((u) => u.status === s).length);

  return (
    <section className="view comptes">
      <p className="comptes-roles">
        <strong>Lecture seule</strong> consulte le planning · <strong>Édition</strong> le modifie ·{" "}
        <strong>Admin</strong> gère aussi les comptes, Celcat et les sauvegardes.
      </p>

      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}

      <div className="comptes-message" role="status" aria-live="polite">
        {message ? (
          <>
            <span>{message.texte}</span>
            {message.annuler ? (
              <button type="button" className="btn btn--sm" onClick={message.annuler.action}>
                {message.annuler.libelle}
              </button>
            ) : null}
          </>
        ) : null}
      </div>

      {enAttente.length > 0 && (
        <section className="panel comptes-attente" aria-labelledby="comptes-attente-titre">
          <h2 id="comptes-attente-titre">En attente d'activation ({enAttente.length})</h2>
          <p className="muted comptes-aide">Email confirmé : ces personnes attendent que vous leur donniez un rôle.</p>
          <ul className="comptes-demandes">
            {enAttente.map((u) => (
              <li key={u.id}>
                <div className="comptes-identite">
                  <strong>{u.email}</strong>
                  <span className="muted">{depuis(u)}</span>
                </div>
                <div className="comptes-actions">
                  <button
                    type="button"
                    className="btn btn--primary"
                    disabled={enCoursId === u.id}
                    onClick={() => activer(u, "read_only")}
                  >
                    Activer en lecture seule
                  </button>
                  <button type="button" className="btn" disabled={enCoursId === u.id} onClick={() => activer(u, "edit")}>
                    Activer en édition
                  </button>
                  <button
                    type="button"
                    className="btn btn--ghost comptes-supprimer"
                    disabled={enCoursId === u.id}
                    onClick={() => void supprimer(u)}
                  >
                    Supprimer
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="panel comptes-tous" aria-labelledby="comptes-tous-titre">
        <div className="comptes-entete">
          <h2 id="comptes-tous-titre">Comptes ({reste.length})</h2>
          <div className="comptes-filtres" role="group" aria-label="Filtrer par statut">
            {FILTRES.map((f) => (
              <button
                key={f.cle}
                type="button"
                className={`comptes-filtre${filtre === f.cle ? " comptes-filtre--actif" : ""}`}
                aria-pressed={filtre === f.cle}
                onClick={() => setFiltre(f.cle)}
              >
                {f.libelle} <span className="comptes-filtre-nb">{compte(f.cle)}</span>
              </button>
            ))}
          </div>
          <input
            type="search"
            className="comptes-recherche"
            placeholder="Rechercher une adresse"
            aria-label="Rechercher une adresse"
            value={recherche}
            onChange={(e) => setRecherche(e.target.value)}
          />
        </div>

        {visibles.length === 0 ? (
          <p className="muted comptes-vide">
            {reste.length === 0 ? "Aucun compte pour l'instant." : "Aucun compte ne correspond à ce filtre."}
          </p>
        ) : (
          <div className="ref-table-wrap">
            <table className="ref comptes-table">
              <thead>
                <tr>
                  <th scope="col">Compte</th>
                  <th scope="col">Statut</th>
                  <th scope="col">Rôle</th>
                  <th scope="col" className="comptes-col-actions">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visibles.map((u) => (
                  <tr key={u.id} className={u.status === "disabled" ? "comptes-ligne--inactive" : undefined}>
                    <td data-label="Compte">
                      <strong className="comptes-email">{u.email}</strong>
                      <div className="muted comptes-depuis">{depuis(u)}</div>
                    </td>
                    <td data-label="Statut">
                      <span className={`pill ${TON_STATUT[u.status]}`}>{LIBELLE_STATUT[u.status]}</span>
                    </td>
                    <td data-label="Rôle">
                      {u.status === "active" ? (
                        <select
                          aria-label={`Rôle de ${u.email}`}
                          value={u.role}
                          disabled={enCoursId === u.id}
                          onChange={(e) =>
                            void appliquer(u, { role: e.target.value }, (maj) => ({
                              texte: `Rôle de ${maj.email} : ${LIBELLE_ROLE[maj.role].toLowerCase()}.`,
                            }))
                          }
                        >
                          <option value="read_only">Lecture seule</option>
                          <option value="edit">Édition</option>
                          <option value="admin">Admin</option>
                        </select>
                      ) : u.status === "disabled" ? (
                        <span className="muted">{LIBELLE_ROLE[u.role]}</span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="comptes-col-actions">
                      {u.status === "active" && (
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm comptes-supprimer"
                          disabled={enCoursId === u.id}
                          onClick={() => desactiver(u)}
                        >
                          Désactiver
                        </button>
                      )}
                      {u.status === "disabled" && (
                        <button
                          type="button"
                          className="btn btn--sm"
                          disabled={enCoursId === u.id}
                          onClick={() => void appliquer(u, { status: "active" }, (maj) => ({ texte: `${maj.email} réactivé.` }))}
                        >
                          Réactiver
                        </button>
                      )}
                      {u.status === "pending_email" && (
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm comptes-supprimer"
                          disabled={enCoursId === u.id}
                          onClick={() => void supprimer(u)}
                        >
                          Supprimer
                        </button>
                      )}
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
