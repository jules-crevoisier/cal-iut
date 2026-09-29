/**
 * Kanban « Tâches » (22/09/2026, retour utilisateur Jules) : « on voudrait
 * une partie kanban pour les choses à faire, exemple : ce prof a dit qu'il
 * ne serait pas présent ce jour, déplacer ». Trois colonnes fixes (À faire /
 * En cours / Fait), tâches HUMAINES uniquement — distinct de « À traiter »,
 * généré automatiquement.
 *
 * Une carte qui porte un enseignant et une période est reliée au planning
 * réel : `utils/kanban.ts::seancesConcernees` liste les séances concernées,
 * chacune ouvre la Vue Promo sur le bon jour.
 *
 * Déplacer une carte : glisser-déposer (souris) ET boutons ← → ↑ ↓ — ces
 * derniers sont le seul moyen clavier/tactile, jamais optionnels. Mise à jour
 * optimiste, retour arrière + message si le serveur refuse.
 *
 * Deux onglets EDT / Plateforme (Jules, dicté 25/09/2026) : vrai widget ARIA
 * `tablist` (ils changent le contenu affiché sans changer de page).
 *
 * Refonte du 29/09/2026 : une seule barre d'outils compacte (onglets, filtres,
 * création), ajout rapide en bas de chaque colonne (Entrée pour créer, « N »
 * pour y aller), filtre texte, filtres mémorisés, cartes denses dont le titre
 * ouvre la modification.
 */

import type { DragEvent as ReactDragEvent, FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Plus } from "lucide-react";

import type { Tache, TacheCreateBody, TachePatchBody } from "../api/client";
import { creerTache, fetchTaches, patchTache, supprimerTache } from "../api/client";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { confirmAsync } from "../utils/confirmDialog";
import { libelleDatesTache, routeVersSeance, seancesConcernees, texteTache } from "../utils/kanban";
import { ecrireOngletTaches, lireOngletTaches } from "../utils/kanbanTabPrefs";
import { copyToClipboard } from "../utils/clipboard";
import { SLOT_TIMES } from "../utils/slots";
import { ecrireLocal, lireLocal } from "../utils/stockageLocal";
import { Onglets } from "../components/Onglets";
import "./KanbanView.css";

const COLONNES: { id: Tache["colonne"]; label: string }[] = [
  { id: "a_faire", label: "À faire" },
  { id: "en_cours", label: "En cours" },
  { id: "fait", label: "Fait" },
];

const CATEGORIES: { id: Tache["categorie"]; label: string }[] = [
  { id: "edt", label: "Emploi du temps" },
  { id: "plateforme", label: "Plateforme" },
];

const CLE_FILTRE = "cal-iut:kanban:pour-qui:v1";
/** Au-delà, la colonne « Fait » se replie : ce qui est fait sert d'archive,
 * pas de liste de travail. */
const MAX_FAIT = 8;

const FMT_COURT = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short" });
const FMT_JOUR = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" });

function formatDateCourte(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : FMT_COURT.format(d);
}

/** Premières lignes d'une description — de quoi reconnaître la tâche ; le
 * détail complet reste dans la modification. */
function premieresLignes(description: string, max = 2): { texte: string; tronque: boolean } {
  const lignes = description.split(/\r?\n/).filter((l) => l.trim() !== "");
  if (lignes.length <= max) return { texte: lignes.join(" "), tronque: false };
  return { texte: lignes.slice(0, max).join(" "), tronque: true };
}

function normaliser(t: string): string {
  return t
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
}

/** « jules.crevoisier@univ.fr » -> « jules.crevoisier » : l'auteur se lit
 * sans occuper une ligne entière de la carte. */
function auteurCourt(email: string): string {
  return email.split("@")[0] || email;
}

function champDeSaisie(cible: EventTarget | null): boolean {
  const el = cible as HTMLElement | null;
  return !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
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
  const [survolColonne, setSurvolColonne] = useState<Tache["colonne"] | null>(null);
  const [faitDeplie, setFaitDeplie] = useState(false);

  // Onglet actif, restauré au premier rendu (cf. `utils/kanbanTabPrefs.ts`).
  const [categorieActive, setCategorieActive] = useState<Tache["categorie"]>(() => lireOngletTaches());
  useEffect(() => {
    ecrireOngletTaches(categorieActive);
  }, [categorieActive]);

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

  // Filtre « pour qui » (Kyllian Bresson, 25/09/2026 : « il y a des
  // modifications qui vous concernent et d'autres qui me concernent
  // uniquement ») — mémorisé : chacun revient sur SES tâches.
  const [filtreConcerne, setFiltreConcerne] = useState<string>(() =>
    lireLocal(CLE_FILTRE, "tout", (v): v is string => typeof v === "string"),
  );
  useEffect(() => ecrireLocal(CLE_FILTRE, filtreConcerne), [filtreConcerne]);
  const [filtreTexte, setFiltreTexte] = useState("");
  // Carte tout juste copiée — confirmation brève (Jules, 28/09/2026).
  const [copiee, setCopiee] = useState<number | null>(null);

  // Personnes proposées : celles des cartes existantes, jamais une liste figée.
  const personnes = useMemo(
    () =>
      [...new Set((taches ?? []).map((t) => t.concerne).filter((c): c is string => Boolean(c)))].sort((a, b) =>
        a.localeCompare(b, "fr"),
      ),
    [taches],
  );

  const filtrees = useMemo(() => {
    const q = normaliser(filtreTexte.trim());
    return (taches ?? []).filter((t) => {
      if (filtreConcerne !== "tout" && (filtreConcerne === "__sans__" ? t.concerne : t.concerne !== filtreConcerne)) {
        return false;
      }
      if (!q) return true;
      const nomProf = t.enseignant_code ? payload.teacherLabels[t.enseignant_code] ?? t.enseignant_code : "";
      return normaliser([t.titre, t.description ?? "", t.concerne ?? "", nomProf, t.enseignant_code ?? ""].join(" ")).includes(q);
    });
  }, [taches, filtreConcerne, filtreTexte, payload.teacherLabels]);

  // Compte par onglet, filtres appliqués mais AVANT le filtre d'onglet (sinon
  // l'onglet non sélectionné afficherait toujours 0). Seules les tâches non
  // faites comptent : c'est ce qui reste à faire qui intéresse.
  const parCategorie = useMemo(() => {
    const compte: Record<Tache["categorie"], number> = { edt: 0, plateforme: 0 };
    for (const t of filtrees) if (t.colonne !== "fait") compte[t.categorie]++;
    return compte;
  }, [filtrees]);

  const parColonne = useMemo(() => {
    const map: Record<Tache["colonne"], Tache[]> = { a_faire: [], en_cours: [], fait: [] };
    for (const t of filtrees) if (t.categorie === categorieActive) map[t.colonne].push(t);
    // Urgente en tête de sa colonne (marqueur TEXTE sur la carte) — à égalité,
    // ordre habituel.
    for (const c of COLONNES) {
      map[c.id].sort((a, b) => {
        const urgenceA = a.priorite === "urgente" ? 0 : 1;
        const urgenceB = b.priorite === "urgente" ? 0 : 1;
        return urgenceA - urgenceB || a.ordre - b.ordre;
      });
    }
    return map;
  }, [filtrees, categorieActive]);

  /** Lot de correctifs appliqué de façon optimiste ; retour arrière COMPLET si
   * un appel échoue, le tableau reste visible avec un message. */
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

  const ordreEnFin = (colonneId: Tache["colonne"]) => {
    const liste = parColonne[colonneId];
    return liste.length ? Math.max(...liste.map((x) => x.ordre)) + 1 : 0;
  };

  const deplacerColonne = (t: Tache, sens: -1 | 1) => {
    const idx = COLONNES.findIndex((c) => c.id === t.colonne);
    const cible = COLONNES[idx + sens];
    if (!cible) return;
    void appliquerLots(
      [{ id: t.id, corps: { colonne: cible.id, ordre: ordreEnFin(cible.id) } }],
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
    setSurvolColonne(null);
    if (draggingId === null) return;
    const source = (taches ?? []).find((x) => x.id === draggingId);
    setDraggingId(null);
    if (!source || source.colonne === colonneId) return;
    void appliquerLots(
      [{ id: source.id, corps: { colonne: colonneId, ordre: ordreEnFin(colonneId) } }],
      "Le déplacement n'a pas pu être enregistré.",
    );
  };

  const deposerSurCarte = (cible: Tache) => (e: ReactDragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setSurvolColonne(null);
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

  // ── Ajout rapide : un titre, Entrée, la carte existe ──
  const [saisieRapide, setSaisieRapide] = useState<Record<Tache["colonne"], string>>({
    a_faire: "",
    en_cours: "",
    fait: "",
  });
  const [ajoutEnCours, setAjoutEnCours] = useState<Tache["colonne"] | null>(null);
  const refAjout = useRef<HTMLInputElement>(null);
  const refFiltre = useRef<HTMLInputElement>(null);

  const ajouterRapide = async (colonneId: Tache["colonne"]) => {
    const titre = saisieRapide[colonneId].trim();
    if (!titre) return;
    setAjoutEnCours(colonneId);
    try {
      const creee = await creerTache({
        titre,
        colonne: colonneId,
        categorie: categorieActive,
        ordre: ordreEnFin(colonneId),
        // Créée sous le filtre « Jules » : elle est pour Jules, sinon elle
        // disparaîtrait de l'écran à peine créée.
        concerne: filtreConcerne !== "tout" && filtreConcerne !== "__sans__" ? filtreConcerne : "",
      });
      setTaches((cur) => [...(cur ?? []), creee]);
      setSaisieRapide((s) => ({ ...s, [colonneId]: "" }));
      setErreur(null);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "La tâche n'a pas pu être créée.");
    } finally {
      setAjoutEnCours(null);
    }
  };

  // Raccourcis : « N » = nouvelle tâche (ajout rapide), « / » = filtrer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || champDeSaisie(e.target) || modaleOuverte) return;
      if (e.key === "n" || e.key === "N") {
        if (!peutModifier) return;
        e.preventDefault();
        refAjout.current?.focus();
      } else if (e.key === "/") {
        e.preventDefault();
        refFiltre.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [peutModifier, modaleOuverte]);

  if (taches === null && !erreur) {
    return (
      <section className="view kanban-view">
        <p className="muted" role="status">
          Chargement…
        </p>
      </section>
    );
  }

  if (taches === null && erreur) {
    return (
      <section className="view kanban-view">
        <div className="kanban-erreur">
          <p className="alerte" role="alert">
            {erreur}
          </p>
          <button type="button" className="btn btn--sm" onClick={() => void charger()}>
            Réessayer
          </button>
        </div>
      </section>
    );
  }

  const filtreActif = filtreConcerne !== "tout" || filtreTexte.trim() !== "";

  return (
    <section className="view kanban-view">
      <div className="page-outils kanban-barre">
        <Onglets
          onglets={CATEGORIES.map((cat) => ({
            id: cat.id,
            label: cat.label,
            nb: parCategorie[cat.id],
            titreNb: "Tâches non terminées",
          }))}
          actif={categorieActive}
          onChoisir={setCategorieActive}
          label="Catégorie de tâches"
          prefixeId="kanban-onglet"
          controle="kanban-board"
        />

        <input
          ref={refFiltre}
          type="search"
          className="kanban-recherche"
          placeholder="Filtrer…  ( / )"
          aria-label="Filtrer les tâches"
          value={filtreTexte}
          onChange={(e) => setFiltreTexte(e.target.value)}
        />
        <label className="kanban-filtre">
          <span>Pour qui</span>
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
        {filtreActif && (
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => {
              setFiltreConcerne("tout");
              setFiltreTexte("");
            }}
          >
            Réinitialiser
          </button>
        )}
        {peutModifier && (
          <div className="page-outils-actions">
            <button
              type="button"
              className="btn btn--primary"
              onClick={ouvrirCreation}
              title="Formulaire complet (enseignant, dates, urgence…)"
            >
              <Plus size={16} aria-hidden="true" />
              Nouvelle tâche
            </button>
          </div>
        )}
        <datalist id="kanban-concerne-suggestions">
          {personnes.map((nom) => (
            <option key={nom} value={nom} />
          ))}
        </datalist>
      </div>

      {erreur && (
        <p className="alerte kanban-alerte" role="alert">
          {erreur}
        </p>
      )}

      <div className="kanban-board" id="kanban-board" role="tabpanel" aria-labelledby={`kanban-onglet-${categorieActive}`}>
        {COLONNES.map((colonne, idxCol) => {
          const liste = parColonne[colonne.id];
          const tronquee = colonne.id === "fait" && !faitDeplie && liste.length > MAX_FAIT;
          const affichees = tronquee ? liste.slice(0, MAX_FAIT) : liste;
          return (
            <section
              key={colonne.id}
              className={`kanban-column${survolColonne === colonne.id ? " survol" : ""}`}
              aria-label={`Colonne ${colonne.label}`}
              onDragOver={(e) => {
                if (draggingId === null) return;
                e.preventDefault();
                if (survolColonne !== colonne.id) setSurvolColonne(colonne.id);
              }}
              onDragLeave={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setSurvolColonne(null);
              }}
              onDrop={deposerSurColonne(colonne.id)}
            >
              <header className="kanban-column-titre">
                <span className={`kanban-statut kanban-statut--${colonne.id}`} aria-hidden="true" />
                <h3>{colonne.label}</h3>
                <span className="kanban-column-nb">{liste.length}</span>
              </header>

              {liste.length === 0 ? (
                <p className="kanban-column-vide">Aucune tâche.</p>
              ) : (
                <ul className="kanban-cards">
                  {affichees.map((t, index) => (
                    <CarteTache
                      key={t.id}
                      t={t}
                      index={index}
                      nbDansColonne={liste.length}
                      idxColonne={COLONNES.findIndex((c) => c.id === t.colonne)}
                      payload={payload}
                      peutModifier={peutModifier}
                      deplie={depliees.has(t.id)}
                      copiee={copiee === t.id}
                      enTrain={draggingId === t.id}
                      onDragStart={() => setDraggingId(t.id)}
                      onDragEnd={() => {
                        setDraggingId(null);
                        setSurvolColonne(null);
                      }}
                      onDragOver={(e) => {
                        if (draggingId !== null) e.preventDefault();
                      }}
                      onDrop={deposerSurCarte(t)}
                      onBasculer={() => basculerDeplie(t.id)}
                      onModifier={() => ouvrirEdition(t)}
                      onSupprimer={() => void supprimer(t)}
                      onColonne={(sens) => deplacerColonne(t, sens)}
                      onOrdre={(sens) => reordonner(t, sens)}
                      onCopier={(texte) => {
                        void (async () => {
                          await copyToClipboard(texte);
                          setCopiee(t.id);
                          window.setTimeout(() => setCopiee((id) => (id === t.id ? null : id)), 2000);
                        })();
                      }}
                      setRoute={setRoute}
                    />
                  ))}
                </ul>
              )}
              {tronquee && (
                <button type="button" className="btn btn--ghost btn--sm kanban-plus" onClick={() => setFaitDeplie(true)}>
                  Afficher les {liste.length - MAX_FAIT} plus anciennes
                </button>
              )}

              {peutModifier && colonne.id !== "fait" && (
                <form
                  className="kanban-ajout"
                  onSubmit={(e: FormEvent) => {
                    e.preventDefault();
                    void ajouterRapide(colonne.id);
                  }}
                >
                  <input
                    ref={idxCol === 0 ? refAjout : undefined}
                    type="text"
                    maxLength={200}
                    aria-label={`Ajouter une tâche dans ${colonne.label}`}
                    placeholder={idxCol === 0 ? "Ajouter une tâche…  ( N )" : "Ajouter une tâche…"}
                    value={saisieRapide[colonne.id]}
                    disabled={ajoutEnCours === colonne.id}
                    onChange={(e) => setSaisieRapide((s) => ({ ...s, [colonne.id]: e.target.value }))}
                    onKeyDown={(e) => {
                      if (e.key === "Escape") {
                        setSaisieRapide((s) => ({ ...s, [colonne.id]: "" }));
                        e.currentTarget.blur();
                      }
                    }}
                  />
                </form>
              )}
            </section>
          );
        })}
      </div>

      {modaleOuverte && (
        <TacheModal
          payload={payload}
          tache={tacheEnEdition}
          categorieParDefaut={categorieActive}
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

interface CarteTacheProps {
  t: Tache;
  index: number;
  nbDansColonne: number;
  idxColonne: number;
  payload: AppPayload;
  peutModifier: boolean;
  deplie: boolean;
  copiee: boolean;
  enTrain: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDragOver: (e: ReactDragEvent) => void;
  onDrop: (e: ReactDragEvent) => void;
  onBasculer: () => void;
  onModifier: () => void;
  onSupprimer: () => void;
  onColonne: (sens: -1 | 1) => void;
  onOrdre: (sens: -1 | 1) => void;
  onCopier: (texte: string) => void;
  setRoute: (patch: Partial<Route>) => void;
}

function CarteTache({
  t,
  index,
  nbDansColonne,
  idxColonne,
  payload,
  peutModifier,
  deplie,
  copiee,
  enTrain,
  onDragStart,
  onDragEnd,
  onDragOver,
  onDrop,
  onBasculer,
  onModifier,
  onSupprimer,
  onColonne,
  onOrdre,
  onCopier,
  setRoute,
}: CarteTacheProps) {
  const nomProf = t.enseignant_code ? payload.teacherLabels[t.enseignant_code] ?? t.enseignant_code : null;
  const datesLabel = libelleDatesTache(t.date_debut, t.date_fin);
  const seances = t.enseignant_code && t.date_debut ? seancesConcernees(payload, t) : null;
  const desc = t.description ? premieresLignes(t.description) : null;
  const libelleSeance = ({ row, dateIso }: { row: AppPayload["rows"][number]; dateIso: string }) =>
    `${formatDateCourte(dateIso)} · ${SLOT_TIMES[row.s].label} · ${row.c} · ${row.g
      .map((g) => payload.groupLabels[g] ?? g)
      .join("/")}`;

  return (
    <li
      className={`kanban-card${enTrain ? " dragging" : ""}${t.priorite === "urgente" ? " urgente" : ""}`}
      draggable={peutModifier}
      onDragStart={
        peutModifier
          ? (e) => {
              e.dataTransfer.effectAllowed = "move";
              onDragStart();
            }
          : undefined
      }
      onDragEnd={onDragEnd}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <div className="kanban-card-tete">
        {peutModifier ? (
          <button type="button" className="kanban-card-titre" aria-label={`Modifier « ${t.titre} »`} onClick={onModifier}>
            {t.titre}
          </button>
        ) : (
          <p className="kanban-card-titre">{t.titre}</p>
        )}
        {/* Marqueur TEXTE, pas seulement une couleur. */}
        {t.priorite === "urgente" && <span className="pill bad">Urgent</span>}
      </div>

      {(t.concerne || nomProf || datesLabel) && (
        <p className="kanban-card-meta">
          {t.concerne && <span className="kanban-card-concerne">{t.concerne}</span>}
          {[nomProf, datesLabel].filter(Boolean).join(" · ")}
        </p>
      )}
      {desc && (
        <p className="kanban-card-desc">
          {desc.texte}
          {desc.tronque ? "…" : ""}
        </p>
      )}

      {seances !== null && (
        <div className="kanban-card-seances">
          <button type="button" className="kanban-lien" aria-expanded={deplie} onClick={onBasculer}>
            {seances.length} séance{seances.length > 1 ? "s" : ""} concernée{seances.length > 1 ? "s" : ""}
          </button>
          {deplie && (
            <ul className="kanban-seances-liste">
              {seances.length === 0 && <li className="muted small">Aucune séance dans cette période.</li>}
              {seances.map((s) => (
                <li key={s.row.id}>
                  <button type="button" className="kanban-seance-lien" onClick={() => setRoute(routeVersSeance(s.row))}>
                    {libelleSeance(s)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="kanban-card-pied">
        <span className="kanban-card-auteur" title={`Ajoutée par ${t.cree_par}`}>
          {t.colonne === "fait" && t.fait_le
            ? `faite le ${FMT_JOUR.format(new Date(t.fait_le))}`
            : `par ${auteurCourt(t.cree_par)}`}
        </span>
        <span className="kanban-card-actions">
          {peutModifier && (
            <>
              <button
                type="button"
                className="kanban-icone"
                aria-label={`Déplacer « ${t.titre} » vers la colonne précédente`}
                title="Colonne précédente"
                disabled={idxColonne === 0}
                onClick={() => onColonne(-1)}
              >
                <ArrowLeft size={14} aria-hidden="true" />
              </button>
              <button
                type="button"
                className="kanban-icone"
                aria-label={`Déplacer « ${t.titre} » vers la colonne suivante`}
                title="Colonne suivante"
                disabled={idxColonne === COLONNES.length - 1}
                onClick={() => onColonne(1)}
              >
                <ArrowRight size={14} aria-hidden="true" />
              </button>
              <button
                type="button"
                className="kanban-icone"
                aria-label={`Monter « ${t.titre} » dans la colonne`}
                title="Monter"
                disabled={index === 0}
                onClick={() => onOrdre(-1)}
              >
                <ArrowUp size={14} aria-hidden="true" />
              </button>
              <button
                type="button"
                className="kanban-icone"
                aria-label={`Descendre « ${t.titre} » dans la colonne`}
                title="Descendre"
                disabled={index === nbDansColonne - 1}
                onClick={() => onOrdre(1)}
              >
                <ArrowDown size={14} aria-hidden="true" />
              </button>
            </>
          )}
          {/* Copier : visible aussi en lecture seule, ne modifie rien. */}
          <button
            type="button"
            className="kanban-texte"
            aria-label={`Copier toutes les informations de « ${t.titre} »`}
            onClick={() =>
              onCopier(texteTache(t, { nomEnseignant: nomProf, seances: seances ?? [], libelleSeance }))
            }
          >
            {copiee ? "Copié" : "Copier"}
          </button>
          {peutModifier && (
            <button
              type="button"
              className="kanban-texte kanban-texte--danger"
              aria-label={`Supprimer « ${t.titre} »`}
              onClick={onSupprimer}
            >
              Supprimer
            </button>
          )}
        </span>
      </div>
    </li>
  );
}

interface TacheModalProps {
  payload: AppPayload;
  /** Présent = édition, absent = création — même convention que
   * `CreerSeanceModal`. */
  tache: Tache | null;
  /** Catégorie proposée à la création — celle de l'onglet ouvert, pour
   * qu'une carte créée depuis « Plateforme » y reste par défaut. Sans effet
   * en édition (la carte a déjà sa catégorie). */
  categorieParDefaut: Tache["categorie"];
  onClose: () => void;
  onSaved: (t: Tache) => void;
}

function TacheModal({ payload, tache, categorieParDefaut, onClose, onSaved }: TacheModalProps) {
  const [titre, setTitre] = useState(tache?.titre ?? "");
  const [description, setDescription] = useState(tache?.description ?? "");
  const [colonne, setColonne] = useState<Tache["colonne"]>(tache?.colonne ?? "a_faire");
  const [categorie, setCategorie] = useState<Tache["categorie"]>(tache?.categorie ?? categorieParDefaut);
  const [urgent, setUrgent] = useState(tache?.priorite === "urgente");
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
      categorie,
      priorite: urgent ? "urgente" : "normale",
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

          {/* Onglet EDT / Plateforme (25/09/2026) — décide sous quel onglet
              la carte apparaît sur le tableau. */}
          <label className="newroom-field">
            Catégorie
            <select value={categorie} onChange={(e) => setCategorie(e.target.value as Tache["categorie"])}>
              {CATEGORIES.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>

          {/* Urgence (même demande, 25/09/2026) — une case, pas un select :
              deux valeurs seulement, et l'état par défaut ("normale") est le
              plus courant. */}
          <label className="newroom-field newroom-field--checkbox">
            <input type="checkbox" checked={urgent} onChange={(e) => setUrgent(e.target.checked)} />
            Urgent
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
