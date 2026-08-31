/**
 * Gestion des comptes (31/08/2026) — liste + activation/rôle/désactivation.
 * Réservée aux admins : le backend refuse déjà tout le reste
 * (`Depends(require_role("admin"))`), cette vue n'est simplement jamais
 * proposée dans la nav à un autre rôle (App.tsx/SideNav).
 */

import { useCallback, useEffect, useState } from "react";

import { adminListUsers, adminUpdateUser } from "../api/client";
import type { AdminUser } from "../api/client";

const LIBELLE_STATUT: Record<AdminUser["status"], string> = {
  pending_email: "Email non confirmé",
  pending_admin_activation: "En attente d'activation",
  active: "Actif",
  disabled: "Désactivé",
};

const LIBELLE_ROLE: Record<AdminUser["role"], string> = {
  read_only: "Lecture seule",
  edit: "Édition",
  admin: "Admin",
};

export function AdminUsersView() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCoursId, setEnCoursId] = useState<number | null>(null);

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

  const appliquer = async (id: number, patch: { role?: string; status?: string }) => {
    setEnCoursId(id);
    setErreur(null);
    try {
      const maj = await adminUpdateUser(id, patch);
      setUsers((prev) => (prev ? prev.map((u) => (u.id === id ? maj : u)) : prev));
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Erreur");
    } finally {
      setEnCoursId(null);
    }
  };

  if (erreur && !users) {
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

  if (!users) {
    return (
      <section className="view">
        <div className="panel">
          <p className="muted">Chargement…</p>
        </div>
      </section>
    );
  }

  const enAttente = users.filter((u) => u.status === "pending_admin_activation");
  const reste = users.filter((u) => u.status !== "pending_admin_activation");

  return (
    <section className="view">
      {erreur && (
        <div className="panel">
          <p className="alerte" role="alert">
            {erreur}
          </p>
        </div>
      )}

      {enAttente.length > 0 && (
        <div className="panel">
          <h3>En attente d'activation ({enAttente.length})</h3>
          <ul className="admin-users-list">
            {enAttente.map((u) => (
              <li key={u.id} className="admin-users-row">
                <div className="admin-users-identite">
                  <strong>{u.email}</strong>
                  <span className="muted">{LIBELLE_STATUT[u.status]}</span>
                </div>
                <div className="admin-users-actions">
                  <button
                    type="button"
                    className="btn btn--primary"
                    disabled={enCoursId === u.id}
                    onClick={() => void appliquer(u.id, { role: "read_only" })}
                  >
                    Activer en lecture seule
                  </button>
                  <button
                    type="button"
                    className="btn"
                    disabled={enCoursId === u.id}
                    onClick={() => void appliquer(u.id, { role: "edit" })}
                  >
                    Activer en édition
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="panel">
        <h3>Tous les comptes ({reste.length})</h3>
        <ul className="admin-users-list">
          {reste.map((u) => (
            <li key={u.id} className="admin-users-row">
              <div className="admin-users-identite">
                <strong>{u.email}</strong>
                <span className={`pill mini ${u.status === "active" ? "good" : u.status === "disabled" ? "bad" : "warn"}`}>
                  {LIBELLE_STATUT[u.status]}
                </span>
                {u.status === "active" && <span className="muted">{LIBELLE_ROLE[u.role]}</span>}
              </div>
              <div className="admin-users-actions">
                {u.status === "active" && (
                  <>
                    <select
                      aria-label={`Rôle de ${u.email}`}
                      value={u.role}
                      disabled={enCoursId === u.id}
                      onChange={(e) => void appliquer(u.id, { role: e.target.value })}
                    >
                      <option value="read_only">Lecture seule</option>
                      <option value="edit">Édition</option>
                      <option value="admin">Admin</option>
                    </select>
                    <button
                      type="button"
                      className="btn btn--danger"
                      disabled={enCoursId === u.id}
                      onClick={() => void appliquer(u.id, { status: "disabled" })}
                    >
                      Désactiver
                    </button>
                  </>
                )}
                {u.status === "disabled" && (
                  <button
                    type="button"
                    className="btn btn--primary"
                    disabled={enCoursId === u.id}
                    onClick={() => void appliquer(u.id, { status: "active" })}
                  >
                    Réactiver
                  </button>
                )}
                {u.status === "pending_email" && <span className="muted">N'a pas encore confirmé son email</span>}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
