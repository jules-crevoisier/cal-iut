/**
 * « À traiter » — tout ce qui demande une décision, rangé pour être TRAITÉ
 * (refonte du 29/09/2026) : la page faisait 21 000 px de haut, 309 lignes
 * dépliées à la suite. Désormais :
 *   - un sommaire par nature (compteurs cliquables) ;
 *   - des sections repliables, les « à revoir » repliées par défaut ;
 *   - des filtres (texte, parcours, semaine, enseignant, gravité) mémorisés ;
 *   - un tri par urgence : semaine en cours d'abord, semaines passées
 *     regroupées et repliées en fin de section ;
 *   - chaque ligne ouvre l'écran où l'on corrige.
 *
 * Deux sources : `buildTodoList` (dérivé du planning chargé) et les doublons
 * salle/enseignant (retour Kyllian Bresson 25/09/2026), balayés EN DIRECT par
 * `GET /controles/doublons` pour attraper ceux qu'une retouche à la main a
 * introduits depuis le chargement. Le contrôle HEBDOMADAIRE (Jules Crevoisier,
 * 25/09/2026) tourne côté serveur ; on n'en affiche que le dernier résultat,
 * dans l'en-tête de la section doublons.
 */

import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowRight, ChevronDown, ChevronsDownUp, ChevronsUpDown } from "lucide-react";

import type { Doublon, DoublonHebdoRun } from "../api/client";
import { executerControleDoublonsHebdo, fetchControleDoublonsHebdo, fetchDoublons } from "../api/client";
import type { Route } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { libelleControleHebdo } from "../utils/controleDoublonsHebdo";
import { ecrireLocal, lireLocal } from "../utils/stockageLocal";
import {
  buildTodoList,
  FILTRES_VIDES,
  filtrerPoints,
  libelleQuand,
  libelleSemaine,
  NATURES,
  occurrences,
  pointsDepuisDoublons,
  statutsSemaines,
  trierParUrgence,
  type FiltresTodo,
  type NatureInfo,
  type NatureTodo,
  type StatutSemaine,
  type TodoItem,
} from "../utils/todo";
import { ChampRecherche } from "../components/ChampRecherche";
import { Tuile, Tuiles } from "../components/Tuile";
import { useDroits, useManques } from "../contexts/Droits";
import { filtrerManques, manquesDeReference, SectionCompleter, TITRE_COMPLETER, tonManques } from "./TodoCompleter";
import "../styles/outils.css";
import "./TodoView.css";

const CLE_FILTRES = "cal-iut:a-traiter:filtres:v1";
const CLE_REPLIES = "cal-iut:a-traiter:replies:v1";
const CLE_COMPLETER_REPLIE = "cal-iut:a-traiter:completer-replie:v1";
/** Les « à revoir » (compromis acceptés, confort) sont repliés tant que
 * l'utilisateur n'a rien choisi : ils ne doivent pas noyer ce qui casse. */
const REPLIES_PAR_DEFAUT: NatureTodo[] = ["compromis-sae", "trouee"];
const PAS = 40;

function estFiltres(v: unknown): v is FiltresTodo {
  return typeof v === "object" && v !== null && "gravite" in v && "semaine" in v;
}

interface TodoViewProps {
  payload: AppPayload;
  setRoute: (patch: Partial<Route>) => void;
}

export function TodoView({ payload, setRoute }: TodoViewProps) {
  const items = useMemo(() => buildTodoList(payload), [payload]);

  const [doublons, setDoublons] = useState<Doublon[] | null>(null);
  const [erreurDoublons, setErreurDoublons] = useState<string | null>(null);

  const chargerDoublons = useCallback(async () => {
    try {
      const liste = await fetchDoublons();
      // Signalement de Jules le 27/09/2026 (« je ne vois pas la section ») :
      // une réponse d'une forme inattendue (front et back décalés d'un
      // déploiement) faisait tomber tout l'écran. On refuse tout ce qui
      // n'est pas une liste, et on le DIT.
      if (!Array.isArray(liste)) {
        setDoublons([]);
        setErreurDoublons("Réponse inattendue du serveur pour les doublons.");
        return;
      }
      setDoublons(liste);
      setErreurDoublons(null);
    } catch (e) {
      setErreurDoublons(e instanceof Error ? e.message : "Erreur de chargement des doublons.");
    }
  }, []);

  useEffect(() => {
    void chargerDoublons();
  }, [chargerDoublons]);

  // `undefined` = pas encore chargé, `null` = jamais exécuté.
  const [controleHebdo, setControleHebdo] = useState<DoublonHebdoRun | null | undefined>(undefined);
  const [executionHebdoEnCours, setExecutionHebdoEnCours] = useState(false);

  useEffect(() => {
    let annule = false;
    fetchControleDoublonsHebdo()
      .then((dernier) => {
        if (!annule) setControleHebdo(dernier);
      })
      // Complément, jamais bloquant pour le reste de l'écran.
      .catch(() => {
        if (!annule) setControleHebdo(null);
      });
    return () => {
      annule = true;
    };
  }, []);

  const verifierMaintenant = useCallback(async () => {
    setExecutionHebdoEnCours(true);
    try {
      setControleHebdo(await executerControleDoublonsHebdo());
      // Le contrôle vient de balayer le planning : la liste en direct suit.
      void chargerDoublons();
    } catch {
      // Le dernier résultat connu reste affiché.
    } finally {
      setExecutionHebdoEnCours(false);
    }
  }, [chargerDoublons]);

  const pointsDoublons = useMemo(
    () => (doublons ? pointsDepuisDoublons(payload, doublons, controleHebdo ?? null) : []),
    [payload, doublons, controleHebdo],
  );
  const tous = useMemo(() => [...items, ...pointsDoublons], [items, pointsDoublons]);
  const statuts = useMemo(() => statutsSemaines(payload), [payload]);

  // ── Filtres et sections repliées, mémorisés d'une visite à l'autre ──
  const [filtres, setFiltres] = useState<FiltresTodo>(() => ({
    ...FILTRES_VIDES,
    ...lireLocal(CLE_FILTRES, FILTRES_VIDES, estFiltres),
  }));
  useEffect(() => ecrireLocal(CLE_FILTRES, filtres), [filtres]);
  const majFiltre = (patch: Partial<FiltresTodo>) => setFiltres((f) => ({ ...f, ...patch }));
  const filtresActifs =
    filtres.texte !== "" ||
    filtres.parcours !== "" ||
    filtres.enseignant !== "" ||
    filtres.semaine !== "toutes" ||
    filtres.gravite !== "tout";

  const [replies, setReplies] = useState<Set<NatureTodo>>(
    () => new Set(lireLocal<NatureTodo[]>(CLE_REPLIES, REPLIES_PAR_DEFAUT, Array.isArray as (v: unknown) => v is NatureTodo[])),
  );
  useEffect(() => ecrireLocal(CLE_REPLIES, [...replies]), [replies]);
  const basculer = (n: NatureTodo) =>
    setReplies((r) => {
      const s = new Set(r);
      if (s.has(n)) s.delete(n);
      else s.add(n);
      return s;
    });

  const filtres_ = useMemo(
    () => trierParUrgence(filtrerPoints(tous, filtres, statuts, payload.teacherLabels), statuts),
    [tous, filtres, statuts, payload.teacherLabels],
  );
  const parNature = useMemo(() => {
    const m = new Map<NatureTodo, TodoItem[]>(NATURES.map((n) => [n.id, []]));
    for (const it of filtres_) m.get(it.nature)!.push(it);
    return m;
  }, [filtres_]);
  const totalParNature = useMemo(() => {
    const m = new Map<NatureTodo, number>(NATURES.map((n) => [n.id, 0]));
    for (const it of tous) m.set(it.nature, (m.get(it.nature) ?? 0) + it.n);
    return m;
  }, [tous]);

  // Options proposées : seulement ce qui apparaît vraiment dans la liste.
  const optionsParcours = useMemo(
    () => [...new Set(tous.flatMap((i) => i.parcours))].sort((a, b) => a.localeCompare(b, "fr")),
    [tous],
  );
  const optionsEnseignants = useMemo(() => {
    const codes = new Set(tous.flatMap((i) => i.enseignants));
    return [...codes]
      .map((c) => [c, payload.teacherLabels[c] ?? c] as const)
      .sort((a, b) => a[1].localeCompare(b[1], "fr"));
  }, [tous, payload.teacherLabels]);
  const optionsSemaines = useMemo(
    () => payload.weekRows.filter((w) => w.weekIndex !== null && !w.blocked),
    [payload.weekRows],
  );

  const refSections = useRef<Partial<Record<NatureTodo, HTMLElement | null>>>({});
  const allerA = (n: NatureTodo) => {
    setReplies((r) => {
      const s = new Set(r);
      s.delete(n);
      return s;
    });
    requestAnimationFrame(() => refSections.current[n]?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  // « Données à compléter » (29/09/2026) : liste du serveur, relue à chaque
  // avance de la révision. Absente sans compte (aucun fournisseur de droits).
  const { role } = useDroits();
  const manques = useManques();
  const manquesReference = useMemo(() => manquesDeReference(manques), [manques]);
  const manquesVisibles = useMemo(() => filtrerManques(manquesReference, filtres), [manquesReference, filtres]);
  const [completerReplie, setCompleterReplie] = useState<boolean>(() =>
    lireLocal<boolean>(CLE_COMPLETER_REPLIE, false, (v): v is boolean => typeof v === "boolean"),
  );
  useEffect(() => ecrireLocal(CLE_COMPLETER_REPLIE, completerReplie), [completerReplie]);
  const refCompleter = useRef<HTMLElement | null>(null);
  const allerACompleter = () => {
    setCompleterReplie(false);
    requestAnimationFrame(() => refCompleter.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  const rechercheRef = useRef<HTMLInputElement>(null);
  // « / » place le curseur dans la recherche, comme partout ailleurs sur le web.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      const cible = e.target as HTMLElement | null;
      if (cible && (cible.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(cible.tagName))) return;
      e.preventDefault();
      rechercheRef.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const toutReplie = NATURES.every((n) => replies.has(n.id)) && (!role || completerReplie);

  return (
    <section className="view todo">
      <Tuiles label="Sommaire des points à traiter" className="todo-sommaire">
        {NATURES.map((n) => {
          const nb = occurrences(parNature.get(n.id)!);
          const total = totalParNature.get(n.id) ?? 0;
          const chargement = n.id === "doublon" && doublons === null && !erreurDoublons;
          return (
            <Tuile
              key={n.id}
              libelle={n.court}
              valeur={chargement ? "…" : nb}
              detail={
                filtresActifs && total !== nb
                  ? `sur ${total}`
                  : nb === 0
                    ? "rien à signaler"
                    : n.sev === "bad"
                      ? "à corriger"
                      : "à revoir"
              }
              ton={nb > 0 ? n.sev : undefined}
              nul={!chargement && nb === 0}
              onClick={() => allerA(n.id)}
              title={`Aller à « ${n.titre} »`}
            />
          );
        })}
        {role && (
          <Tuile
            libelle="À compléter"
            valeur={manques === null ? "…" : manquesVisibles.length}
            detail={
              filtresActifs && manquesVisibles.length !== manquesReference.length
                ? `sur ${manquesReference.length}`
                : manquesVisibles.length === 0
                  ? "rien à signaler"
                  : "mail, Celcat…"
            }
            ton={manquesVisibles.length > 0 ? tonManques(manquesVisibles) : undefined}
            nul={manques !== null && manquesVisibles.length === 0}
            onClick={allerACompleter}
            title={`Aller à « ${TITRE_COMPLETER} »`}
          />
        )}
      </Tuiles>

      <div className="page-outils todo-filtres" role="search">
        <ChampRecherche
          ref={rechercheRef}
          className="todo-recherche"
          placeholder="Filtrer : cours, salle, groupe…"
          libelle="Filtrer les points"
          raccourci="/"
          valeur={filtres.texte}
          onChange={(v) => majFiltre({ texte: v })}
        />
        <select aria-label="Parcours" value={filtres.parcours} onChange={(e) => majFiltre({ parcours: e.target.value })}>
          <option value="">Tous les parcours</option>
          {optionsParcours.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select
          aria-label="Semaine"
          value={filtres.semaine}
          onChange={(e) => majFiltre({ semaine: e.target.value as FiltresTodo["semaine"] })}
        >
          <option value="toutes">Toutes les semaines</option>
          <option value="a-venir">Cette semaine et après</option>
          <option value="courante">Cette semaine</option>
          <optgroup label="Une semaine">
            {optionsSemaines.map((w) => (
              <option key={w.weekIndex} value={`s${w.weekIndex}`}>
                {w.label}
              </option>
            ))}
          </optgroup>
        </select>
        <select
          aria-label="Enseignant"
          value={filtres.enseignant}
          onChange={(e) => majFiltre({ enseignant: e.target.value })}
        >
          <option value="">Tous les enseignants</option>
          {optionsEnseignants.map(([code, nom]) => (
            <option key={code} value={code}>
              {nom}
            </option>
          ))}
        </select>
        <div className="segmente" role="radiogroup" aria-label="Gravité">
          {(
            [
              ["tout", "Tout"],
              ["bad", "À corriger"],
              ["warn", "À revoir"],
            ] as const
          ).map(([v, l]) => (
            <button
              key={v}
              type="button"
              role="radio"
              aria-checked={filtres.gravite === v}
              onClick={() => majFiltre({ gravite: v })}
            >
              {l}
            </button>
          ))}
        </div>
        <div className="page-outils-actions">
          {filtresActifs && (
            <>
              <span className="todo-compte" aria-live="polite">
                {occurrences(filtres_)} sur {occurrences(tous)}
              </span>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => setFiltres(FILTRES_VIDES)}>
                Réinitialiser
              </button>
            </>
          )}
          <button
            type="button"
            className="btn btn--sm todo-replier"
            title={toutReplie ? "Tout déplier" : "Tout replier"}
            onClick={() => {
              setReplies(toutReplie ? new Set() : new Set(NATURES.map((n) => n.id)));
              setCompleterReplie(!toutReplie);
            }}
          >
            {toutReplie ? <ChevronsUpDown size={14} aria-hidden="true" /> : <ChevronsDownUp size={14} aria-hidden="true" />}
            <span className="todo-replier-libelle">{toutReplie ? "Tout déplier" : "Tout replier"}</span>
          </button>
        </div>
      </div>
      {NATURES.map((n) => (
        <SectionNature
          key={n.id}
          nature={n}
          points={parNature.get(n.id)!}
          total={totalParNature.get(n.id) ?? 0}
          replie={replies.has(n.id)}
          onBasculer={() => basculer(n.id)}
          refSection={(el) => {
            refSections.current[n.id] = el;
          }}
          payload={payload}
          statuts={statuts}
          filtresActifs={filtresActifs}
          setRoute={setRoute}
          entete={
            n.id === "doublon" ? (
              <ControleHebdo
                controle={controleHebdo}
                enCours={executionHebdoEnCours}
                onVerifier={() => void verifierMaintenant()}
              />
            ) : null
          }
          etat={
            n.id !== "doublon" ? null : erreurDoublons ? (
              <div className="todo-erreur">
                <p className="alerte" role="alert">
                  {erreurDoublons}
                </p>
                <button type="button" className="btn btn--sm" onClick={() => void chargerDoublons()}>
                  Réessayer
                </button>
              </div>
            ) : doublons === null ? (
              <p className="muted todo-vide" role="status">
                Chargement…
              </p>
            ) : null
          }
          texteVide={n.id === "doublon" ? "Aucun doublon détecté." : "Rien à signaler."}
        />
      ))}
      {role && (
        <SectionCompleter
          manques={manques}
          filtres={filtres}
          filtresActifs={filtresActifs}
          replie={completerReplie}
          onBasculer={() => setCompleterReplie((r) => !r)}
          refSection={(el) => {
            refCompleter.current = el;
          }}
          setRoute={setRoute}
          onVoirSansSalle={() => allerA("sans-salle")}
        />
      )}
    </section>
  );
}

function ControleHebdo({
  controle,
  enCours,
  onVerifier,
}: {
  controle: DoublonHebdoRun | null | undefined;
  enCours: boolean;
  onVerifier: () => void;
}) {
  if (controle === undefined) return null;
  return (
    <div className="todo-hebdo">
      {controle === null ? (
        <span className="muted">Le contrôle hebdomadaire des doublons n'a jamais encore tourné.</span>
      ) : (
        <span className="muted">{libelleControleHebdo(controle)}</span>
      )}
      <button type="button" className="btn btn--sm" onClick={onVerifier} disabled={enCours}>
        {enCours ? "Vérification…" : "Vérifier maintenant"}
      </button>
    </div>
  );
}

interface SectionNatureProps {
  nature: NatureInfo;
  points: TodoItem[];
  total: number;
  replie: boolean;
  onBasculer: () => void;
  refSection: (el: HTMLElement | null) => void;
  payload: AppPayload;
  statuts: Map<number, StatutSemaine>;
  filtresActifs: boolean;
  setRoute: (patch: Partial<Route>) => void;
  entete: ReactNode;
  /** Chargement / erreur propres à la section (doublons). */
  etat: ReactNode;
  texteVide: string;
}

function SectionNature({
  nature,
  points,
  total,
  replie,
  onBasculer,
  refSection,
  payload,
  statuts,
  filtresActifs,
  setRoute,
  entete,
  etat,
  texteVide,
}: SectionNatureProps) {
  const [limite, setLimite] = useState(PAS);
  const [passeesOuvertes, setPasseesOuvertes] = useState(false);
  const idCorps = `todo-corps-${nature.id}`;

  const actuels = points.filter((p) => p.semaine === null || statuts.get(p.semaine) !== "past");
  const passes = points.filter((p) => p.semaine !== null && statuts.get(p.semaine) === "past");
  const visibles = actuels.slice(0, limite);
  const nb = occurrences(points);
  // Section vide et sans état à montrer (chargement, erreur) : une seule
  // ligne, rien à déplier — « rien de ce type » se lit d'un coup d'œil.
  const vide = nb === 0 && !etat && !(filtresActifs && total > 0);
  const reste = actuels.length - visibles.length;

  return (
    <section
      className={`todo-section${replie && !vide ? " replie" : ""}${vide ? " vide" : ""}`}
      ref={refSection}
      aria-labelledby={`todo-titre-${nature.id}`}
    >
      <header className="todo-section-tete">
        <button
          type="button"
          className="todo-section-bascule"
          aria-expanded={vide ? undefined : !replie}
          aria-controls={vide ? undefined : idCorps}
          onClick={vide ? undefined : onBasculer}
          disabled={vide}
        >
          <ChevronDown size={16} className="todo-chevron" aria-hidden="true" />
          <h3 id={`todo-titre-${nature.id}`}>{nature.titre}</h3>
          {nb > 0 && (
            <span
              className={`pill ${nature.sev}`}
              aria-label={`${nb} ${nature.id === "doublon" ? "doublon" : "point"}${nb > 1 ? "s" : ""}`}
            >
              {nb}
            </span>
          )}
          {filtresActifs && total !== nb && <span className="muted small">sur {total}</span>}
        </button>
        {vide && (
          <span className="todo-section-rien" role="status">
            {texteVide}
          </span>
        )}
        {!replie && !vide && <p className="todo-section-aide">{nature.aide}</p>}
        {entete}
      </header>

      {!replie && !vide && (
        <div className="todo-section-corps" id={idCorps}>
          {etat}
          {!etat && points.length === 0 && (
            <p className="muted todo-vide" role="status">
              {filtresActifs && total > 0 ? "Aucun point ne correspond aux filtres." : texteVide}
            </p>
          )}
          {!etat && visibles.length > 0 && (
            <ListePoints points={visibles} payload={payload} statuts={statuts} nature={nature} setRoute={setRoute} />
          )}
          {!etat && reste > 0 && (
            <button type="button" className="btn btn--ghost btn--sm todo-plus" onClick={() => setLimite((l) => l + PAS * 2)}>
              Afficher {Math.min(reste, PAS * 2)} lignes de plus ({reste} restante{reste > 1 ? "s" : ""})
            </button>
          )}
          {!etat && passes.length > 0 && (
            <div className="todo-passees">
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                aria-expanded={passeesOuvertes}
                onClick={() => setPasseesOuvertes((o) => !o)}
              >
                {passeesOuvertes ? "Masquer" : "Afficher"} les semaines passées ({occurrences(passes)})
              </button>
              {passeesOuvertes && (
                <ListePoints points={passes} payload={payload} statuts={statuts} nature={nature} setRoute={setRoute} />
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function ListePoints({
  points,
  payload,
  statuts,
  nature,
  setRoute,
}: {
  points: TodoItem[];
  payload: AppPayload;
  statuts: Map<number, StatutSemaine>;
  nature: NatureInfo;
  setRoute: (patch: Partial<Route>) => void;
}) {
  // Intertitre à chaque changement de semaine (la liste est déjà triée).
  const nbParSemaine = new Map<number, number>();
  for (const p of points) if (p.semaine !== null) nbParSemaine.set(p.semaine, (nbParSemaine.get(p.semaine) ?? 0) + p.n);
  const sansQuand = points.every((p) => p.semaine === null);
  let semainePrecedente: number | null | undefined;

  return (
    <ul className={`todo-liste${sansQuand ? " sans-quand" : ""}`}>
      {points.map((it) => {
        const nouvelleSemaine = it.semaine !== null && it.semaine !== semainePrecedente;
        semainePrecedente = it.semaine;
        const statut = it.semaine !== null ? statuts.get(it.semaine) : undefined;
        const quand = libelleQuand(payload, it);
        return (
          <Fragment key={it.cle}>
            {nouvelleSemaine && (
              <li className="todo-semaine">
                <span>{libelleSemaine(payload, it.semaine!)}</span>
                {statut === "current" && <span className="todo-semaine-marque">cette semaine</span>}
                <span className="todo-semaine-nb">{nbParSemaine.get(it.semaine!)}</span>
              </li>
            )}
            <li>
              <button type="button" className={`todo-ligne ${it.sev}`} onClick={() => setRoute(it.route)}>
                <span className="todo-quand">{quand}</span>
                <span className="todo-quoi">
                  {it.typeDoublon && <span className="todo-tag">{it.typeDoublon}</span>}
                  <strong>{it.title}</strong>
                  {it.n > 1 && <span className="todo-fois">×{it.n}</span>}
                  {it.nouveau && <span className="pill todo-nouveau">nouveau</span>}
                  <span className="todo-detail">{it.sub}</span>
                </span>
                <span className="todo-cible">
                  {nature.cible} <ArrowRight size={13} aria-hidden="true" />
                </span>
              </button>
            </li>
          </Fragment>
        );
      })}
    </ul>
  );
}
