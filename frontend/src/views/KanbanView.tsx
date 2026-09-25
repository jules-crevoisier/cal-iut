/**
 * Kanban « Tâches » (22/09/2026, retour utilisateur Jules) : « on voudrait
 * une partie kanban pour les choses à faire, exemple : ce prof a dit qu'il
 * ne serait pas présent ce jour, déplacer » — l'équipe se le passait par
 * mail jusqu'ici. Trois colonnes fixes (À faire / En cours / Fait), tâches
 * HUMAINES uniquement : distinct de « À traiter » (`TodoView`), qui reste
 * la liste des problèmes de qualité de données détectés automatiquement.
 *
 * Le point du kanban, illustré par l'exemple même de la demande : relier une
 * carte au planning réel dès qu'elle porte un enseignant et une période —
 * `utils/kanban.ts::seancesConcernees` calcule les séances concernées
 * CÔTÉ CLIENT depuis `payload.rows`, chaque résultat ouvre la Vue Promo sur
 * le bon jour.
 *
 * Déplacer une carte : glisser-déposer (souris) ET boutons explicites
 * (← → pour changer de colonne, ↑ ↓ pour réordonner) — ces derniers sont le
 * seul moyen clavier/tactile, jamais optionnels. Mise à jour optimiste avec
 * retour arrière + message d'erreur si le serveur refuse.
 */

import type { DragEvent as ReactDragEvent, FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import type { Tache, TacheCreateBody, TachePatchBody } from "../api/client";
import { creerTache, fetchTaches, patchTache, supprimerTache } from "../api/client";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { confirmAsync } from "../utils/confirmDialog";
import { libelleDatesTache, routeVersSeance, seancesConcernees } from "../utils/kanban";
import { SLOT_TIMES } from "../utils/slots";
import "./KanbanView.css";

const COLONNES: { id: Tache["colonne"]; label: string }[] = [
  { id: "a_faire", label: "À faire" },
  { id: "en_cours", label: "En cours" },
  { id: "fait", label: "Fait" },
];

const FMT_COURT = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short" });

function formatDateCourte(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : FMT_COURT.format(d);
}

/** Premières lignes d'une description — la carte n'a pas vocation à tout
 * afficher, seulement de quoi reconnaître la tâche ; le détail complet
 * reste disponible via « Modifier ». */
function premieresLignes(description: string, max = 2): { texte: string; tronque: boolean } {
  const lignes = description.split(/\r?\n/).filter((l) => l.trim() !== "");
  if (lignes.length <= max) return { texte: lignes.join(" "), tronque: false };
  return { texte: lignes.slice(0, max).join(" "), tronque: true };
}

interface KanbanViewProps {
  payload: AppPayload;
  role?: "read_only" | "edit" | "admin";
  setRoute: (patch: Partial<Route>) => void;
}

export function KanbanView({ payload, role, setRoute }: KanbanViewProps) {
  const peutModifier = role === "edit" || role === "admin";

  const [taches, setTaches] = useState<Tache[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [modaleOuverte, setModaleOuverte] = useState(false);
  const [tacheEnEdition, setTacheEnEdition] = useState<Tache | null>(null);
  const [depliees, setDepliees] = useState<Set<number>>(new Set());
  const [draggingId, setDraggingId] = useState<number | null>(null);

  const charger = useCallback(async () => {
    try {
      const liste = await fetchTaches();
      setTaches(liste);
      setErreur(null);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Erreur de chargement des tâches.");
    }
  }, []);

  useEffect(() => {
    void charger();
  }, [charger]);

  const [filtreConcerne, setFiltreConcerne] = useState<string>("tout");

  // Filtre « pour qui » (Kyllian Bresson, 25/09/2026 : « il y a des
  // modifications qui vous concernent et d'autres qui me concernent
  // uniquement ») — les valeurs proposées viennent des cartes existantes,
  // jamais d'une liste figée dans le code.
  const personnes = useMemo(
    () => [...new Set((taches ?? []).map((t) => t.concerne).filter((c): c is string => Boolean(c)))].sort((a, b) => a.localeCompare(b, "fr")),
    [taches],
  );

  const parColonne = useMemo(() => {
    const map: Record<Tache["colonne"], Tache[]> = { a_faire: [], en_cours: [], fait: [] };
    const retenues = (taches ?? []).filter(
      (t) => filtreConcerne === "tout" || (filtreConcerne === "__sans__" ? !t.concerne : t.concerne === filtreConcerne),
    );
    for (const t of retenues) map[t.colonne].push(t);
    for (const c of COLONNES) map[c.id].sort((a, b) => a.ordre - b.ordre);
    return map;
  }, [taches, filtreConcerne]);

  /** Applique un lot de correctifs de façon optimiste (une seule passe,
   * pour que deux cartes échangeant leur `ordre` — cf. `reordonner` —
   * s'affichent ensemble) ; retour arrière COMPLET si l'un des appels
   * serveur échoue, le tableau reste visible avec un message d'erreur
   * (jamais un écran blanc). */
  const appliquerLots = useCallback(
    async (mises: { id: number; corps: TachePatchBody }[], messageEchec: string) => {
      setTaches((cur) => {
        if (!cur) return cur;
        return cur.map((t) => {
          const m = mises.find((x) => x.id === t.id);
          return m ? ({ ...t, ...m.corps } as Tache) : t;
        });
      });
      try {
        const majs = await Promise.all(mises.map((m) => patchTache(m.id, m.corps)));
        setTaches((cur) => (cur ?? []).map((t) => majs.find((m) => m.id === t.id) ?? t));
        setErreur(null);
      } catch (e) {
        await charger();
        setErreur(e instanceof Error ? e.message : messageEchec);
      }
    },
    [charger],
  );

  const deplacerColonne = (t: Tache, sens: -1 | 1) => {
    const idx = COLONNES.findIndex((c) => c.id === t.colonne);
    const cible = COLONNES[idx + sens];
    if (!cible) return;
    const cibleListe = parColonne[cible.id];
    const nouvelOrdre = cibleListe.length ? Math.max(...cibleListe.map((x) => x.ordre)) + 1 : 0;
    void appliquerLots(
      [{ id: t.id, corps: { colonne: cible.id, ordre: nouvelOrdre } }],
      "Le déplacement n'a pas pu être enregistré.",
    );
  };

  const reordonner = (t: Tache, sens: -1 | 1) => {
    const liste = parColonne[t.colonne];
    const idx = liste.findIndex((x) => x.id === t.id);
    const voisin = liste[idx + sens];
    if (!voisin) return;
    void appliquerLots(
      [
        { id: t.id, corps: { ordre: voisin.ordre } },
        { id: voisin.id, corps: { ordre: t.ordre } },
      ],
      "La réorganisation n'a pas pu être enregistrée.",
    );
  };

  const deposerSurColonne = (colonneId: Tache["colonne"]) => (e: ReactDragEvent) => {
    e.preventDefault();
    if (draggingId === null) return;
    const source = (taches ?? []).find((x) => x.id === draggingId);
    setDraggingId(null);
    if (!source || source.colonne === colonneId) return;
    const cibleListe = parColonne[colonneId];
    const nouvelOrdre = cibleListe.length ? Math.max(...cibleListe.map((x) => x.ordre)) + 1 : 0;
    void appliquerLots(
      [{ id: source.id, corps: { colonne: colonneId, ordre: nouvelOrdre } }],
      "Le déplacement n'a pas pu être enregistré.",
    );
  };

  const deposerSurCarte = (cible: Tache) => (e: ReactDragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (draggingId === null || draggingId === cible.id) {
      setDraggingId(null);
      return;
    }
    const source = (taches ?? []).find((x) => x.id === draggingId);
    setDraggingId(null);
    if (!source) return;
    const liste = parColonne[cible.colonne].filter((x) => x.id !== source.id);
    const idx = liste.findIndex((x) => x.id === cible.id);
    const precedent = liste[idx - 1];
    const nouvelOrdre = precedent ? (precedent.ordre + cible.ordre) / 2 : cible.ordre - 1;
    void appliquerLots(
      [{ id: source.id, corps: { colonne: cible.colonne, ordre: nouvelOrdre } }],
      "Le déplacement n'a pas pu être enregistré.",
    );
  };

  const basculerDeplie = (id: number) => {
    setDepliees((prev) => {
      const suivant = new Set(prev);
      if (suivant.has(id)) suivant.delete(id);
      else suivant.add(id);
      return suivant;
    });
  };

  const supprimer = async (t: Tache) => {
    const confirme = await confirmAsync(`Supprimer la tâche « ${t.titre} » ?`, {
      title: "Supprimer la tâche",
      confirmLabel: "Supprimer",
      cancelLabel: "Annuler",
      variant: "danger",
    });
    if (!confirme) return;
    setTaches((cur) => (cur ?? []).filter((x) => x.id !== t.id));
    try {
      await supprimerTache(t.id);
    } catch (e) {
      await charger();
      setErreur(e instanceof Error ? e.message : "La suppression n'a pas pu être enregistrée.");
    }
  };

  const ouvrirCreation = () => {
    setTacheEnEdition(null);
    setModaleOuverte(true);
  };

  const ouvrirEdition = (t: Tache) => {
    setTacheEnEdition(t);
    setModaleOuverte(true);
  };

  const onSaved = (t: Tache) => {
    setTaches((cur) => {
      if (!cur) return [t];
      const existe = cur.some((x) => x.id === t.id);
      return existe ? cur.map((x) => (x.id === t.id ? t : x)) : [...cur, t];
    });
    setModaleOuverte(false);
    setTacheEnEdition(null);
  };

  if (taches === null && !erreur) {
    return (
      <section className="view kanban-view">
        <div className="panel">
          <p className="muted">Chargement…</p>
        </div>
      </section>
    );
  }

  if (taches === null && erreur) {
    return (
      <section className="view kanban-view">
        <div className="panel">
          <p className="alerte" role="alert">
            {erreur}
          </p>
          <button type="button" className="btn" onClick={() => void charger()}>
            Réessayer
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="view kanban-view">
      <div className="panel kanban-header">
        <div>
          <h3>Tâches</h3>
          <p className="muted">
            Ce que l'équipe a noté pour elle-même — absences signalées, déplacements à faire, points à suivre.
            Distinct de « À traiter », qui reste généré automatiquement.
          </p>
        </div>
        <div className="kanban-header-actions">
          <label className="kanban-filtre">
            Pour qui
            <select value={filtreConcerne} onChange={(e) => setFiltreConcerne(e.target.value)}>
              <option value="tout">Tout le monde</option>
              <option value="__sans__">Non attribuées</option>
              {personnes.map((nom) => (
                <option key={nom} value={nom}>
                  {nom}
                </option>
              ))}
            </select>
          </label>
          {peutModifier && (
            <button type="button" className="btn btn--accent" onClick={ouvrirCreation}>
              + Nouvelle tâche
            </button>
          )}
        </div>
        <datalist id="kanban-concerne-suggestions">
          {personnes.map((nom) => (
            <option key={nom} value={nom} />
          ))}
        </datalist>
      </div>

      {erreur && (
        <div className="panel">
          <p className="alerte" role="alert">
            {erreur}
          </p>
        </div>
      )}

      <div className="kanban-board">
        {COLONNES.map((colonne) => {
          const liste = parColonne[colonne.id];
          return (
            <section
              key={colonne.id}
              className="panel kanban-column"
              aria-label={`Colonne ${colonne.label}`}
              onDragOver={(e) => {
                if (draggingId !== null) e.preventDefault();
              }}
              onDrop={deposerSurColonne(colonne.id)}
            >
              <div className="kanban-column-titre">
                <h4>{colonne.label}</h4>
                <span className="pill">{liste.length}</span>
              </div>
              {liste.length === 0 ? (
                <p className="muted small kanban-column-vide">Aucune tâche.</p>
              ) : (
                <ul className="kanban-cards">
                  {liste.map((t, index) => {
                    const teacherLabel = t.enseignant_code
                      ? payload.teacherLabels[t.enseignant_code] ?? t.enseignant_code
                      : null;
                    const datesLabel = libelleDatesTache(t.date_debut, t.date_fin);
                    const seances = t.enseignant_code && t.date_debut ? seancesConcernees(payload, t) : null;
                    const deplie = depliees.has(t.id);
                    const desc = t.description ? premieresLignes(t.description) : null;
                    const idxColonne = COLONNES.findIndex((c) => c.id === t.colonne);

                    return (
                      <li
                        key={t.id}
                        className={`kanban-card${draggingId === t.id ? " dragging" : ""}`}
                        draggable={peutModifier}
                        onDragStart={
                          peutModifier
                            ? (e) => {
                                e.dataTransfer.effectAllowed = "move";
                                setDraggingId(t.id);
                              }
                            : undefined
                        }
                        onDragEnd={() => setDraggingId(null)}
                        onDragOver={(e) => {
                          if (draggingId !== null) e.preventDefault();
                        }}
                        onDrop={deposerSurCarte(t)}
                      >
                        <p className="kanban-card-titre">{t.titre}</p>
                        {t.concerne && <span className="pill kanban-card-concerne">{t.concerne}</span>}
                        {(teacherLabel || datesLabel) && (
                          <p className="kanban-card-meta">
                            {[teacherLabel, datesLabel].filter(Boolean).join(" · ")}
                          </p>
                        )}
                        {desc && (
                          <p className="kanban-card-desc">
                            {desc.texte}
                            {desc.tronque ? "…" : ""}
                          </p>
                        )}
                        <p className="kanban-card-auteur muted small">Ajoutée par {t.cree_par}</p>

                        {seances !== null && (
                          <div className="kanban-card-seances">
                            <button
                              type="button"
                              className="btn btn--ghost btn--sm"
                              aria-expanded={deplie}
                              onClick={() => basculerDeplie(t.id)}
                            >
                              {seances.length} séance{seances.length > 1 ? "s" : ""} concernée
                              {seances.length > 1 ? "s" : ""}
                            </button>
                            {deplie && (
                              <ul className="kanban-seances-liste">
                                {seances.length === 0 && (
                                  <li className="muted small">Aucune séance dans cette période.</li>
                                )}
                                {seances.map(({ row, dateIso }) => (
                                  <li key={row.id}>
                                    <button
                                      type="button"
                                      className="kanban-seance-lien"
                                      onClick={() => setRoute(routeVersSeance(row))}
                                    >
                                      {formatDateCourte(dateIso)} · {SLOT_TIMES[row.s].label} · {row.c} ·{" "}
                                      {row.g.map((g) => payload.groupLabels[g] ?? g).join("/")}
                                    </button>
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        )}

                        {peutModifier && (
                          <div className="kanban-card-actions">
                            <button
                              type="button"
                              aria-label={`Déplacer « ${t.titre} » vers la colonne précédente`}
                              disabled={idxColonne === 0}
                              onClick={() => deplacerColonne(t, -1)}
                            >
                              ←
                            </button>
                            <button
                              type="button"
                              aria-label={`Déplacer « ${t.titre} » vers la colonne suivante`}
                              disabled={idxColonne === COLONNES.length - 1}
                              onClick={() => deplacerColonne(t, 1)}
                            >
                              →
                            </button>
                            <button
                              type="button"
                              aria-label={`Monter « ${t.titre} » dans la colonne`}
                              disabled={index === 0}
                              onClick={() => reordonner(t, -1)}
                            >
                              ↑
                            </button>
                            <button
                              type="button"
                              aria-label={`Descendre « ${t.titre} » dans la colonne`}
                              disabled={index === liste.length - 1}
                              onClick={() => reordonner(t, 1)}
                            >
                              ↓
                            </button>
                            <button
                              type="button"
                              className="btn btn--ghost btn--sm"
                              aria-label={`Modifier « ${t.titre} »`}
                              onClick={() => ouvrirEdition(t)}
                            >
                              Modifier
                            </button>
                            <button
                              type="button"
                              className="btn btn--ghost btn--sm"
                              aria-label={`Supprimer « ${t.titre} »`}
                              onClick={() => void supprimer(t)}
                            >
                              Supprimer
                            </button>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          );
        })}
      </div>

      {modaleOuverte && (
        <TacheModal
          payload={payload}
          tache={tacheEnEdition}
          onClose={() => {
            setModaleOuverte(false);
            setTacheEnEdition(null);
          }}
          onSaved={onSaved}
        />
      )}
    </section>
  );
}

interface TacheModalProps {
  payload: AppPayload;
  /** Présent = édition, absent = création — même convention que
   * `CreerSeanceModal`. */
  tache: Tache | null;
  onClose: () => void;
  onSaved: (t: Tache) => void;
}

function TacheModal({ payload, tache, onClose, onSaved }: TacheModalProps) {
  const [titre, setTitre] = useState(tache?.titre ?? "");
  const [description, setDescription] = useState(tache?.description ?? "");
  const [colonne, setColonne] = useState<Tache["colonne"]>(tache?.colonne ?? "a_faire");
  const [enseignantCode, setEnseignantCode] = useState(tache?.enseignant_code ?? "");
  const [concerne, setConcerne] = useState(tache?.concerne ?? "");
  const [dateDebut, setDateDebut] = useState(tache?.date_debut ?? "");
  const [dateFin, setDateFin] = useState(tache?.date_fin ?? "");
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const enseignantsTries = useMemo(
    () => Object.entries(payload.teacherLabels).sort((a, b) => a[1].localeCompare(b[1], "fr")),
    [payload.teacherLabels],
  );

  const valider = async (e: FormEvent) => {
    e.preventDefault();
    const titreNettoye = titre.trim();
    if (!titreNettoye) {
      setErreur("Le titre est obligatoire.");
      return;
    }
    if (dateDebut && dateFin && dateFin < dateDebut) {
      setErreur("La date de fin doit être postérieure ou égale à la date de début.");
      return;
    }
    setEnCours(true);
    setErreur(null);
    // `date_fin` reprend `date_debut` quand une seule date est choisie —
    // « une seule journée » se représente par les deux bornes égales (cf.
    // contrat verrouillé), pas par une `date_fin` absente.
    const corps: TacheCreateBody = {
      titre: titreNettoye,
      description: description.trim() || null,
      colonne,
      enseignant_code: enseignantCode || null,
      concerne: concerne.trim(),
      date_debut: dateDebut || null,
      date_fin: dateDebut ? dateFin || dateDebut : null,
    };
    try {
      const resultat = tache ? await patchTache(tache.id, corps) : await creerTache(corps);
      onSaved(resultat);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "L'enregistrement a échoué.");
    } finally {
      setEnCours(false);
    }
  };

  return (
    <div className="confirmmodal-overlay" role="presentation" onClick={onClose}>
      <form
        className="panel confirmmodal seancemodal kanban-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="kanban-modal-titre"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => void valider(e)}
      >
        <h3 id="kanban-modal-titre">{tache ? "Modifier la tâche" : "Nouvelle tâche"}</h3>

        <div className="seancemodal-grille">
          <label className="newroom-field newroom-field--large">
            Titre
            <input
              value={titre}
              maxLength={200}
              autoFocus
              onChange={(e) => setTitre(e.target.value)}
              placeholder="ex. Prévenir Kyllian, absent jeudi"
            />
          </label>

          <label className="newroom-field newroom-field--large">
            Description (optionnel)
            <textarea
              value={description}
              maxLength={2000}
              placeholder="Détails, contexte…"
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>

          <label className="newroom-field">
            Colonne
            <select value={colonne} onChange={(e) => setColonne(e.target.value as Tache["colonne"])}>
              {COLONNES.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>

          {/* « Il y a des modifications qui vous concernent et d'autres qui
              me concernent uniquement » (Kyllian Bresson, 25/09/2026) : une
              carte dit pour qui elle est. Texte libre : la liste des gens
              change plus vite que le code, et tous n'ont pas de compte. */}
          <label className="newroom-field">
            Pour qui (optionnel)
            <input
              type="text"
              value={concerne}
              maxLength={64}
              placeholder="Jules, Kyllian, scolarité…"
              list="kanban-concerne-suggestions"
              onChange={(e) => setConcerne(e.target.value)}
            />
          </label>

          <label className="newroom-field">
            Enseignant (optionnel)
            <select value={enseignantCode} onChange={(e) => setEnseignantCode(e.target.value)}>
              <option value="">Aucun</option>
              {enseignantsTries.map(([code, nom]) => (
                <option key={code} value={code}>
                  {nom}
                </option>
              ))}
            </select>
          </label>

          <label className="newroom-field">
            Date début (optionnel)
            <input type="date" value={dateDebut} onChange={(e) => setDateDebut(e.target.value)} />
          </label>

          <label className="newroom-field">
            Date fin (optionnel)
            <input
              type="date"
              value={dateFin}
              min={dateDebut || undefined}
              disabled={!dateDebut}
              onChange={(e) => setDateFin(e.target.value)}
            />
          </label>
        </div>

        {erreur && (
          <p className="alerte" role="alert">
            {erreur}
          </p>
        )}

        <div className="confirmmodal-actions">
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Annuler
          </button>
          <button type="submit" className="btn btn--accent" disabled={enCours}>
            {enCours ? "…" : tache ? "Enregistrer" : "Créer"}
          </button>
        </div>
      </form>
    </div>
  );
}
