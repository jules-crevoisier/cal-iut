/**
 * La question qu'on vient poser : la semaine concorde-t-elle avec Celcat ?
 *
 * Critique design du 16/09/2026 : l'écran s'ouvrait sur des réglages et le
 * verdict vivait deux clics plus loin, en gris. Il est la première chose de
 * la page, dans la couleur de son état, avec ses compteurs par nature
 * d'écart (refonte du 29/09/2026) : « 2 à modifier, 1 à créer, 2 en trop »
 * se lit d'un coup d'œil, sans ouvrir le détail.
 *
 * Le bouton principal corrige SANS supprimer. Il incluait les suppressions,
 * si bien que le geste par défaut était le seul irréversible ; elles ont
 * leur propre panneau, où l'on voit ce qu'on supprime avant de le faire.
 *
 * L'action ne s'arrête pas à la mise en file : elle suit jusqu'à la lecture
 * suivante de Celcat (cf. `useBoucleCelcat`), étape par étape.
 */
import type { CelcatComparaison } from "../api/client";
import type { EtapeBoucle, EtatBoucle } from "../hooks/useBoucleCelcat";
import { PILULE, verdictSemaine, type Ton } from "../utils/celcatStatut";
import { CompteRenduCorrection } from "./CompteRenduCorrection";
import { Tuile, Tuiles, type TonTuile } from "./Tuile";

export interface SemaineChoisissable {
  indice: number;
  libelle: string;
}

const ETAPES: Array<{ cle: EtapeBoucle; libelle: string }> = [
  { cle: "envoi", libelle: "Mise en file" },
  { cle: "attente_worker", libelle: "Passage du robot d’envoi" },
  { cle: "attente_releve", libelle: "Nouvelle lecture de Celcat" },
];

function avancement(etape: EtapeBoucle, cle: EtapeBoucle, avecCorrection: boolean): "fait" | "en cours" | "à venir" | null {
  if (!avecCorrection && cle !== "attente_releve") return null;
  const ordre: EtapeBoucle[] = ["envoi", "attente_worker", "attente_releve"];
  if (etape === "verifie") return "fait";
  const ici = ordre.indexOf(etape);
  const la = ordre.indexOf(cle);
  if (ici < 0) return null;
  if (la < ici) return "fait";
  if (la === ici) return "en cours";
  return "à venir";
}

function Chevron({ sens }: { sens: "gauche" | "droite" }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        d={sens === "gauche" ? "M15 5l-7 7 7 7" : "M9 5l7 7-7 7"}
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Semaine précédente / choix daté / semaine suivante, et le retour à la
 * semaine en cours quand on s'en est éloigné. */
export function NavigationSemaine({
  semaines,
  semaine,
  courante,
  onSemaine,
  occupe,
}: {
  semaines: SemaineChoisissable[];
  semaine: number;
  courante: number | null;
  onSemaine: (indice: number) => void;
  occupe: boolean;
}) {
  const position = semaines.findIndex((s) => s.indice === semaine);
  const precedente = position > 0 ? semaines[position - 1] : null;
  const suivante = position >= 0 && position < semaines.length - 1 ? semaines[position + 1] : null;
  return (
    <div className="celcat-semaine-nav" role="group" aria-label="Semaine comparée">
      <button
        type="button"
        className="btn celcat-nav-fleche"
        aria-label={precedente ? `Semaine précédente : ${precedente.libelle}` : "Pas de semaine précédente"}
        disabled={!precedente || occupe}
        onClick={() => precedente && onSemaine(precedente.indice)}
      >
        <Chevron sens="gauche" />
      </button>
      <label className="celcat-semaine-choix">
        <span className="sr-only">Semaine comparée</span>
        <select value={semaine} disabled={occupe} onChange={(e) => onSemaine(Number(e.target.value))}>
          {semaines.map(({ indice, libelle }) => (
            <option key={indice} value={indice}>
              {libelle}
              {indice === courante ? " — en cours" : ""}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="btn celcat-nav-fleche"
        aria-label={suivante ? `Semaine suivante : ${suivante.libelle}` : "Pas de semaine suivante"}
        disabled={!suivante || occupe}
        onClick={() => suivante && onSemaine(suivante.indice)}
      >
        <Chevron sens="droite" />
      </button>
      {courante !== null && courante !== semaine && semaines.some((s) => s.indice === courante) ? (
        <button type="button" className="btn btn--ghost" disabled={occupe} onClick={() => onSemaine(courante)}>
          Semaine en cours
        </button>
      ) : null}
    </div>
  );
}

const MOT_TON: Record<Ton, string> = { ok: "concorde", attention: "à traiter", panne: "bloqué" };

export function VerdictCelcat({
  donnees,
  erreur,
  boucle,
  onCorriger,
  onVerifier,
  onArreter,
  occupe,
  enFile = null,
}: {
  donnees: CelcatComparaison | null;
  erreur: string | null;
  boucle: EtatBoucle;
  /** Corrections en file vers Celcat (`null` : file illisible). */
  enFile?: number | null;
  onCorriger: () => void;
  onVerifier: () => void;
  onArreter: () => void;
  occupe: boolean;
}) {
  const verdict = donnees ? verdictSemaine(donnees) : null;
  const ton: Ton = verdict?.ton ?? "attention";
  const aCorriger = verdict ? verdict.aModifier + verdict.aCreer : 0;
  const releveAbsentOuPerime = !!donnees && (!donnees.releve_le || donnees.perime);
  const enCours = boucle.etape !== "repos";
  const avecCorrection = boucle.correction !== null || boucle.etape === "envoi" || boucle.etape === "attente_worker";

  // Refonte v2 (29/09/2026) : les compteurs sortent du verdict et passent en
  // tuiles, en tête d'écran — même langage que l'Accueil.
  const compteurs: Array<{ cle: string; libelle: string; n: number; ton: TonTuile; detail: string }> =
    verdict
      ? [
          { cle: "modifier", libelle: "À modifier", n: verdict.aModifier, ton: "warn", detail: "séances qui diffèrent" },
          { cle: "creer", libelle: "À créer", n: verdict.aCreer, ton: "warn", detail: "absentes de Celcat" },
          { cle: "trop", libelle: "En trop", n: verdict.enTrop, ton: "bad", detail: "dans Celcat seulement" },
          {
            cle: "identiques",
            libelle: verdict.identiques > 1 ? "Identiques" : "Identique",
            n: verdict.identiques,
            ton: "good",
            detail: "rien à faire",
          },
        ]
      : [];

  return (
    <>
      {compteurs.length > 0 ? (
        <Tuiles label="Écarts de la semaine avec Celcat" className="celcat-tuiles" testId="verdict-compteurs">
          {/* Relevé absent ou périmé : pas de chiffre plutôt qu'un faux zéro. */}
          {compteurs.map((c) => (
            <Tuile
              key={c.cle}
              libelle={c.libelle}
              valeur={releveAbsentOuPerime ? "—" : c.n}
              detail={releveAbsentOuPerime ? "Celcat à relire" : c.detail}
              ton={!releveAbsentOuPerime && c.n > 0 ? c.ton : undefined}
              nul={releveAbsentOuPerime || c.n === 0}
            />
          ))}
          <Tuile
            libelle="En file vers Celcat"
            valeur={enFile ?? "—"}
            detail={enFile === null ? "file illisible" : enFile > 0 ? "le robot d’envoi les enverra" : "rien en attente"}
            nul={!enFile}
          />
        </Tuiles>
      ) : null}
      <section
        className={`panel celcat-verdict celcat-verdict--${verdict ? ton : "chargement"}`}
        aria-labelledby="celcat-verdict-titre"
        aria-busy={!verdict && !erreur}
      >
        <div className="celcat-verdict-corps">
          <div className="celcat-verdict-texte">
            {erreur ? (
              <>
                <h2 id="celcat-verdict-titre" className="celcat-verdict-titre">
                  Comparaison impossible
                </h2>
                <p className="celcat-texte-panne" role="alert">
                  {erreur}
                </p>
              </>
            ) : !verdict ? (
              <>
                <h2 id="celcat-verdict-titre" className="celcat-verdict-titre celcat-verdict-titre--attente">
                  Comparaison avec Celcat…
                </h2>
                <p className="celcat-sous-texte">Lecture des séances de la semaine.</p>
              </>
            ) : (
              <>
                <p className="celcat-verdict-mot">
                  <span className={`pill dot ${PILULE[ton]}`}>{MOT_TON[ton]}</span>
                </p>
                <h2 id="celcat-verdict-titre" className="celcat-verdict-titre">
                  {verdict.titre}
                </h2>
                <p className="celcat-verdict-detail">{verdict.detail}</p>
              </>
            )}
          </div>

        </div>

        <div className="celcat-actions">
          {releveAbsentOuPerime ? (
            <button type="button" className="btn btn--accent" disabled={occupe} onClick={onVerifier}>
              Relire Celcat
            </button>
          ) : (
            <>
              {aCorriger > 0 ? (
                <button type="button" className="btn btn--accent" disabled={occupe} onClick={onCorriger}>
                  {boucle.etape === "envoi" ? "Envoi des corrections…" : `Corriger ${aCorriger > 1 ? `les ${aCorriger} écarts` : "l’écart"}`}
                </button>
              ) : null}
              {donnees ? (
                <button type="button" className="btn" disabled={occupe} onClick={onVerifier}>
                  Relire Celcat et vérifier
                </button>
              ) : null}
            </>
          )}
          {occupe ? (
            <button type="button" className="btn btn--ghost" onClick={onArreter}>
              Arrêter d’attendre
            </button>
          ) : null}
          {aCorriger > 0 && !releveAbsentOuPerime ? (
            <p className="celcat-actions-note">
              Modifie et crée dans Celcat. Ne supprime jamais rien : les évènements en trop se traitent à part, plus bas.
            </p>
          ) : null}
        </div>

        {/* Toujours rendu, même vide : une région live ajoutée après coup n'est
            pas annoncée par les lecteurs d'écran. */}
        <div className="celcat-suivi" role="status" aria-live="polite" data-testid="suivi-boucle">
          {enCours ? (
            <>
              {boucle.verification ? (
                <ol className="celcat-etapes">
                  {ETAPES.map(({ cle, libelle }) => {
                    const a = avancement(boucle.etape, cle, avecCorrection);
                    if (a === null) return null;
                    const classe = a === "fait" ? "fait" : a === "en cours" ? "en-cours" : "a-venir";
                    return (
                      <li key={cle} className={`celcat-etape-suivi celcat-etape-suivi--${classe}`}>
                        <span className="celcat-etape-libelle">{libelle}</span>
                        <span className={`pill dot ${a === "fait" ? "good" : a === "en cours" ? "warn" : ""}`}>{a}</span>
                      </li>
                    );
                  })}
                </ol>
              ) : null}
              {boucle.message ? (
                <p
                  className={
                    boucle.etape === "erreur"
                      ? "celcat-texte-panne"
                      : boucle.etape === "interrompu"
                        ? "celcat-texte-attention"
                        : boucle.etape === "verifie"
                          ? "celcat-texte-ok"
                          : ""
                  }
                >
                  {boucle.message}
                </p>
              ) : null}
              {boucle.correction ? <CompteRenduCorrection correction={boucle.correction} /> : null}
            </>
          ) : null}
        </div>
      </section>
    </>
  );
}
