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
 *
 * Images jointes (30/09/2026) : bouton, collage (Ctrl V) et glisser-déposer
 * dans la modale ; compteur sur la carte, qui ouvre l'aperçu — y compris en
 * lecture seule (cf. `components/ImagesTache.tsx`).
 *
 * Archive (09/10/2026, Jules) : une tâche faite depuis plus de deux
 * semaines quitte la colonne « Fait » et le rapport copié ; le bouton
 * « Archive » de la barre la retrouve (cf. `utils/kanban.ts::estArchivee`).
 */

import type { DragEvent as ReactDragEvent, FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Archive, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, ClipboardCopy, Image as IconeImage, Plus } from "lucide-react";

import type { ImageTache, Tache, TacheCreateBody, TachePatchBody } from "../api/client";
import {
  IMAGES_TACHE,
  creerTache,
  envoyerImageTache,
  fetchTaches,
  patchTache,
  supprimerImageTache,
  supprimerTache,
} from "../api/client";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { confirmAsync } from "../utils/confirmDialog";
import { ARCHIVE_APRES_JOURS, estArchivee, libelleDatesTache, rapportTaches, routeVersSeance, seancesConcernees, texteTache } from "../utils/kanban";
import { ecrireOngletTaches, lireOngletTaches } from "../utils/kanbanTabPrefs";
import { copyToClipboard } from "../utils/clipboard";
import { SLOT_TIMES } from "../utils/slots";
import { ecrireLocal, lireLocal } from "../utils/stockageLocal";
import { ChampRecherche } from "../components/ChampRecherche";
import type { ImageAffichable } from "../components/ImagesTache";
import { ApercuImages, ImagesTache, imageAffichable, nommerCapture, trierFichiers } from "../components/ImagesTache";
import { Onglets } from "../components/Onglets";
import { ActionsDePage } from "../components/TopBar";
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

/** Une séance concernée sur une ligne — même libellé sur la carte, dans sa
 * copie et dans le rapport de la page. */
function libelleSeance(payload: AppPayload, { row, dateIso }: { row: AppPayload["rows"][number]; dateIso: string }): string {
  return `${formatDateCourte(dateIso)} · ${SLOT_TIMES[row.s].label} · ${row.c} · ${row.g
    .map((g) => payload.groupLabels[g] ?? g)
    .join("/")}`;
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
  const [voirArchive, setVoirArchive] = useState(false);
  // Aperçu des images d'une carte, ouvert depuis son compteur.
  const [apercu, setApercu] = useState<{ tacheId: number; index: number } | null>(null);

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
  const [rapportCopie, setRapportCopie] = useState(false);

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
      // « #7 » retrouve la tâche par son numéro ; « 7 » seul aussi, en plus du texte.
      if (/^#\d+$/.test(q)) return `#${t.id}` === q;
      if (/^\d+$/.test(q) && String(t.id) === q) return true;
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

  // Faites depuis plus de deux semaines : hors du tableau (et du rapport),
  // rangées dans l'archive, la plus récemment faite en tête.
  const { parColonne, archivees } = useMemo(() => {
    const maintenant = new Date();
    const map: Record<Tache["colonne"], Tache[]> = { a_faire: [], en_cours: [], fait: [] };
    const archive: Tache[] = [];
    for (const t of filtrees) {
      if (t.categorie !== categorieActive) continue;
      if (estArchivee(t, maintenant)) archive.push(t);
      else map[t.colonne].push(t);
    }
    archive.sort((a, b) => (b.fait_le ?? "").localeCompare(a.fait_le ?? ""));
    // Urgente en tête de sa colonne (marqueur TEXTE sur la carte) — à égalité,
    // ordre habituel.
    for (const c of COLONNES) {
      map[c.id].sort((a, b) => {
        const urgenceA = a.priorite === "urgente" ? 0 : 1;
        const urgenceB = b.priorite === "urgente" ? 0 : 1;
        return urgenceA - urgenceB || a.ordre - b.ordre;
      });
    }
    return { parColonne: map, archivees: archive };
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

  const onSaved = (t: Tache, avertissement?: string) => {
    setTaches((cur) => {
      if (!cur) return [t];
      const existe = cur.some((x) => x.id === t.id);
      return existe ? cur.map((x) => (x.id === t.id ? t : x)) : [...cur, t];
    });
    setModaleOuverte(false);
    setTacheEnEdition(null);
    if (avertissement) setErreur(avertissement);
  };

  /** Images ajoutées ou retirées depuis la modale (enregistrées aussitôt) :
   * seules les images de la carte changent, le reste attend « Enregistrer ». */
  const onImagesChange = (t: Tache) => {
    setTaches((cur) => (cur ?? []).map((x) => (x.id === t.id ? { ...x, images: t.images ?? [] } : x)));
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
      if (e.ctrlKey || e.metaKey || e.altKey || champDeSaisie(e.target) || modaleOuverte || apercu) return;
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
  }, [peutModifier, modaleOuverte, apercu]);

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

  // Rapport de toute la page, à coller à Claude (Jules, 09/10/2026) : ce
  // que l'écran montre (onglet + filtres), colonne « Fait » comprise même
  // repliée — mais jamais l'archive.
  const copierRapport = async () => {
    const filtres: string[] = [];
    if (filtreConcerne === "__sans__") filtres.push("non attribuées");
    else if (filtreConcerne !== "tout") filtres.push(`pour ${filtreConcerne}`);
    if (filtreTexte.trim()) filtres.push(`texte « ${filtreTexte.trim()} »`);
    const texte = rapportTaches(
      COLONNES.map((c) => ({ id: c.id, label: c.label, taches: parColonne[c.id] })),
      {
        categorie: categorieActive,
        filtres,
        nomEnseignant: (t) => (t.enseignant_code ? payload.teacherLabels[t.enseignant_code] ?? t.enseignant_code : null),
        seances: (t) => seancesConcernees(payload, t).map((sc) => libelleSeance(payload, sc)),
      },
    );
    await copyToClipboard(texte);
    setRapportCopie(true);
    window.setTimeout(() => setRapportCopie(false), 2000);
  };

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

        <ChampRecherche
          ref={refFiltre}
          className="kanban-recherche"
          placeholder="Filtrer…"
          libelle="Filtrer les tâches"
          raccourci="/"
          valeur={filtreTexte}
          onChange={(v) => setFiltreTexte(v)}
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
        {/* Archive : tâches faites depuis plus de deux semaines. */}
        <button
          type="button"
          className={`btn btn--ghost btn--sm kanban-archive-bouton${voirArchive ? " actif" : ""}`}
          aria-pressed={voirArchive}
          aria-controls="kanban-board"
          onClick={() => setVoirArchive((v) => !v)}
          title={`Tâches faites il y a plus de ${ARCHIVE_APRES_JOURS / 7} semaines`}
        >
          <Archive size={14} aria-hidden="true" />
          Archive
          <span className="kanban-archive-nb">{archivees.length}</span>
        </button>
        {/* Visible aussi en lecture seule : copier ne modifie rien. */}
        <button
          type="button"
          className="btn btn--ghost btn--sm kanban-rapport"
          onClick={() => void copierRapport()}
          title="Copie toutes les tâches de cet onglet (filtres appliqués) en Markdown, prêtes à coller"
        >
          <ClipboardCopy size={14} aria-hidden="true" />
          <span aria-live="polite">{rapportCopie ? "Rapport copié" : "Copier le rapport"}</span>
        </button>
        {peutModifier && (
          <ActionsDePage>
            <button
              type="button"
              className="btn btn--primary"
              onClick={ouvrirCreation}
              title="Formulaire complet (enseignant, dates, urgence…)"
            >
              <Plus size={16} aria-hidden="true" />
              Nouvelle tâche
            </button>
          </ActionsDePage>
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

      {voirArchive ? (
        <section
          className="kanban-archive"
          id="kanban-board"
          role="tabpanel"
          aria-labelledby={`kanban-onglet-${categorieActive}`}
        >
          <header className="kanban-archive-tete">
            <h3>Archive</h3>
            <p className="muted small">
              Faites il y a plus de {ARCHIVE_APRES_JOURS / 7} semaines, la plus récente en tête. Rien n'est supprimé,
              et l'archive n'entre pas dans le rapport copié.
            </p>
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => setVoirArchive(false)}>
              Retour au tableau
            </button>
          </header>
          {archivees.length === 0 ? (
            <p className="kanban-column-vide">Aucune tâche archivée.</p>
          ) : (
            <ul className="kanban-cards kanban-archive-liste">
              {archivees.map((t) => (
                <CarteTache
                  key={t.id}
                  t={t}
                  index={0}
                  nbDansColonne={1}
                  idxColonne={COLONNES.findIndex((c) => c.id === t.colonne)}
                  payload={payload}
                  peutModifier={peutModifier}
                  deplie={depliees.has(t.id)}
                  copiee={copiee === t.id}
                  enTrain={false}
                  glissable={false}
                  onDragStart={() => undefined}
                  onDragEnd={() => undefined}
                  onDragOver={() => undefined}
                  onDrop={() => undefined}
                  onBasculer={() => basculerDeplie(t.id)}
                  onModifier={() => ouvrirEdition(t)}
                  onVoirImages={() => setApercu({ tacheId: t.id, index: 0 })}
                  onSupprimer={() => void supprimer(t)}
                  onColonne={(sens) => deplacerColonne(t, sens)}
                  onOrdre={() => undefined}
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
        </section>
      ) : (
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
                      onVoirImages={() => setApercu({ tacheId: t.id, index: 0 })}
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
                  {/* Raccourci « N » (première colonne) : dans un `<kbd>` à
                      droite, pas dans le texte d'exemple. */}
                  <span className="champ-raccourci">
                    <input
                      ref={idxCol === 0 ? refAjout : undefined}
                      type="text"
                      maxLength={200}
                      aria-label={`Ajouter une tâche dans ${colonne.label}`}
                      placeholder="Ajouter une tâche…"
                      aria-keyshortcuts={idxCol === 0 ? "N" : undefined}
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
                    {idxCol === 0 && (
                      <kbd className="champ-recherche-kbd" aria-hidden="true">
                        N
                      </kbd>
                    )}
                  </span>
                </form>
              )}
            </section>
          );
        })}
      </div>
      )}

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
          onImagesChange={onImagesChange}
        />
      )}

      {apercu && (
        <ApercuImages
          images={((taches ?? []).find((x) => x.id === apercu.tacheId)?.images ?? []).map(imageAffichable)}
          index={apercu.index}
          onIndex={(index) => setApercu((a) => (a ? { ...a, index } : a))}
          onClose={() => setApercu(null)}
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
  onVoirImages: () => void;
  onSupprimer: () => void;
  onColonne: (sens: -1 | 1) => void;
  onOrdre: (sens: -1 | 1) => void;
  onCopier: (texte: string) => void;
  setRoute: (patch: Partial<Route>) => void;
  /** Faux dans l'archive : pas de colonne où déposer. */
  glissable?: boolean;
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
  onVoirImages,
  onSupprimer,
  onColonne,
  onOrdre,
  onCopier,
  setRoute,
  glissable = true,
}: CarteTacheProps) {
  const nomProf = t.enseignant_code ? payload.teacherLabels[t.enseignant_code] ?? t.enseignant_code : null;
  const datesLabel = libelleDatesTache(t.date_debut, t.date_fin);
  const seances = t.enseignant_code && t.date_debut ? seancesConcernees(payload, t) : null;
  const desc = t.description ? premieresLignes(t.description) : null;
  const nbImages = t.images?.length ?? 0;

  return (
    <li
      className={`kanban-card${enTrain ? " dragging" : ""}${t.priorite === "urgente" ? " urgente" : ""}`}
      draggable={peutModifier && glissable}
      onDragStart={
        peutModifier && glissable
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
        {/* Numéro de la tâche, le même que dans le rapport copié (« (#7) ») :
            on peut dire « la tâche 7 » (Jules, 09/10/2026). */}
        <span className="kanban-card-num" aria-label={`Tâche numéro ${t.id}`}>
          #{t.id}
        </span>
        {peutModifier ? (
          <button type="button" className="kanban-card-titre" aria-label={`Modifier « ${t.titre} »`} onClick={onModifier}>
            {t.titre}
          </button>
        ) : (
          <p className="kanban-card-titre">{t.titre}</p>
        )}
        {/* Marqueur TEXTE, pas seulement une couleur. */}
        {t.priorite === "urgente" && <span className="pill dot bad">Urgent</span>}
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
                    {libelleSeance(payload, s)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="kanban-card-pied">
        <span className="kanban-card-pied-gauche">
          {/* Compteur d'images : ouvre l'aperçu, lecture seule comprise. */}
          {nbImages > 0 && (
            <button
              type="button"
              className="kanban-card-images"
              aria-label={`Voir ${nbImages > 1 ? `les ${nbImages} images` : "l’image"} de « ${t.titre} »`}
              title={nbImages > 1 ? `${nbImages} images` : "1 image"}
              onClick={onVoirImages}
            >
              <IconeImage size={13} aria-hidden="true" />
              {nbImages}
            </button>
          )}
          <span className="kanban-card-auteur" title={`Ajoutée par ${t.cree_par}`}>
            {t.colonne === "fait" && t.fait_le
              ? `faite le ${FMT_JOUR.format(new Date(t.fait_le))}`
              : `par ${auteurCourt(t.cree_par)}`}
          </span>
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
              onCopier(texteTache(t, {
                  nomEnseignant: nomProf,
                  seances: seances ?? [],
                  libelleSeance: (sc) => libelleSeance(payload, sc),
                }))
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
  /** `avertissement` : la tâche est enregistrée, mais une partie des images
   * choisies à la création n'a pas pu être jointe. */
  onSaved: (t: Tache, avertissement?: string) => void;
  /** Images ajoutées/retirées en modification (enregistrées aussitôt). */
  onImagesChange: (t: Tache) => void;
}

interface ImageEnAttente {
  cle: string;
  fichier: File;
  url: string;
}

function urlLocale(fichier: File): string {
  return typeof URL.createObjectURL === "function" ? URL.createObjectURL(fichier) : "";
}

function libererUrl(url: string): void {
  if (url && typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(url);
}

function messageDe(e: unknown, repli: string): string {
  return e instanceof Error ? e.message : repli;
}

function TacheModal({ payload, tache, categorieParDefaut, onClose, onSaved, onImagesChange }: TacheModalProps) {
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

  // ── Images ──
  // En modification : chaque image est envoyée (ou retirée) aussitôt. À la
  // création, la tâche n'existe pas encore : les images attendent ici et
  // partent juste après sa création.
  const [images, setImages] = useState<ImageTache[]>(tache?.images ?? []);
  const [enAttente, setEnAttente] = useState<ImageEnAttente[]>([]);
  const [envois, setEnvois] = useState(0);
  const [erreurImages, setErreurImages] = useState<string | null>(null);
  const [depot, setDepot] = useState(false);
  const compteurCle = useRef(0);

  const refEnAttente = useRef(enAttente);
  refEnAttente.current = enAttente;
  useEffect(() => () => refEnAttente.current.forEach((i) => libererUrl(i.url)), []);

  const ajouterFichiers = async (fichiers: File[]) => {
    const places = IMAGES_TACHE.max - images.length - enAttente.length - envois;
    const { acceptes, refus } = trierFichiers(fichiers, places);
    setErreurImages(refus.length ? refus.join(" ") : null);
    if (!acceptes.length) return;
    if (!tache) {
      setEnAttente((cur) => [
        ...cur,
        ...acceptes.map((fichier) => ({ cle: `attente-${++compteurCle.current}`, fichier, url: urlLocale(fichier) })),
      ]);
      return;
    }
    const echecs: string[] = [];
    setEnvois((n) => n + acceptes.length);
    for (const fichier of acceptes) {
      try {
        const maj = await envoyerImageTache(tache.id, fichier);
        setImages(maj.images ?? []);
        onImagesChange(maj);
      } catch (e) {
        echecs.push(`« ${fichier.name} » : ${messageDe(e, "envoi impossible.")}`);
      } finally {
        setEnvois((n) => n - 1);
      }
    }
    if (echecs.length) setErreurImages([...refus, ...echecs].join(" "));
  };
  const refAjouter = useRef(ajouterFichiers);
  refAjouter.current = ajouterFichiers;

  const retirerImage = async (image: ImageAffichable) => {
    const attente = enAttente.find((i) => i.cle === image.cle);
    if (attente) {
      libererUrl(attente.url);
      setEnAttente((cur) => cur.filter((i) => i.cle !== image.cle));
      return;
    }
    const id = images.find((i) => `img-${i.id}` === image.cle)?.id;
    if (!tache || id === undefined) return;
    try {
      const maj = await supprimerImageTache(tache.id, id);
      setImages(maj.images ?? []);
      onImagesChange(maj);
      setErreurImages(null);
    } catch (e) {
      setErreurImages(messageDe(e, "L’image n’a pas pu être retirée."));
    }
  };

  // Ctrl V n'importe où tant que la modale est ouverte (le titre a le
  // focus à l'ouverture). Un texte collé dans un champ reste un texte.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const donnees = e.clipboardData;
      const fichiers = Array.from(donnees?.files ?? []);
      if (!donnees || !fichiers.length) return;
      if (champDeSaisie(e.target) && donnees.getData("text/plain")) return;
      e.preventDefault();
      void refAjouter.current(fichiers.map((f) => nommerCapture(f)));
    };
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, []);

  const fichiersGlisses = (e: ReactDragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");

  const affichables: ImageAffichable[] = [
    ...images.map(imageAffichable),
    ...enAttente.map((i) => ({ cle: i.cle, url: i.url, nom: i.fichier.name, enAttente: true })),
  ];

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
      let resultat = tache ? await patchTache(tache.id, corps) : await creerTache(corps);
      // Création : les images choisies partent maintenant que la tâche existe.
      const echecs: string[] = [];
      for (const attente of tache ? [] : enAttente) {
        try {
          resultat = await envoyerImageTache(resultat.id, attente.fichier);
        } catch (e) {
          echecs.push(`« ${attente.fichier.name} » (${messageDe(e, "envoi impossible")})`);
        }
      }
      onSaved(
        resultat,
        echecs.length
          ? `La tâche est créée, mais ${echecs.length > 1 ? "ces images n’ont" : "cette image n’a"} pas pu être jointe${
              echecs.length > 1 ? "s" : ""
            } : ${echecs.join(", ")}.`
          : undefined,
      );
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "L'enregistrement a échoué.");
    } finally {
      setEnCours(false);
    }
  };

  return (
    <div
      className="confirmmodal-overlay"
      role="presentation"
      onClick={onClose}
      // Une image lâchée à côté de la fenêtre ne doit pas remplacer la page.
      onDragOver={(e) => {
        if (fichiersGlisses(e)) e.preventDefault();
      }}
      onDrop={(e) => {
        if (fichiersGlisses(e)) e.preventDefault();
      }}
    >
      <form
        className={`panel confirmmodal seancemodal kanban-modal${depot ? " kanban-modal--depot" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="kanban-modal-titre"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => void valider(e)}
        onDragEnter={(e) => {
          if (!fichiersGlisses(e)) return;
          e.preventDefault();
          setDepot(true);
        }}
        onDragOver={(e) => {
          if (!fichiersGlisses(e)) return;
          e.preventDefault();
          e.stopPropagation();
          e.dataTransfer.dropEffect = "copy";
          if (!depot) setDepot(true);
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDepot(false);
        }}
        onDrop={(e) => {
          if (!fichiersGlisses(e)) return;
          e.preventDefault();
          e.stopPropagation();
          setDepot(false);
          void ajouterFichiers(Array.from(e.dataTransfer.files ?? []));
        }}
      >
        {depot && (
          <div className="kanban-modal-depot" aria-hidden="true">
            Déposez les images pour les joindre à la tâche
          </div>
        )}
        <h3 id="kanban-modal-titre">{tache ? `Modifier la tâche #${tache.id}` : "Nouvelle tâche"}</h3>

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

        <ImagesTache
          images={affichables}
          peutModifier
          precision={tache ? "enregistrées dès l’ajout" : "jointes à la création de la tâche"}
          envois={envois}
          erreur={erreurImages}
          onAjouter={(fichiers) => void ajouterFichiers(fichiers)}
          onRetirer={(image) => void retirerImage(image)}
        />

        {erreur && (
          <p className="alerte" role="alert">
            {erreur}
          </p>
        )}

        <div className="confirmmodal-actions">
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Annuler
          </button>
          <button type="submit" className="btn btn--accent" disabled={enCours || envois > 0}>
            {enCours ? "…" : tache ? "Enregistrer" : "Créer"}
          </button>
        </div>
      </form>
    </div>
  );
}
