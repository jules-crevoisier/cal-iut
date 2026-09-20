/**
 * La question qu'on vient poser : la semaine concorde-t-elle avec Celcat ?
 *
 * Critique design du 16/09/2026 : l'écran s'ouvrait sur « Pilotage » — des
 * réglages — et le verdict vivait deux clics plus loin, en gris. Il est
 * désormais la première chose de la page, dans la couleur de son état.
 *
 * Le bouton principal corrige SANS supprimer. Il incluait les suppressions,
 * si bien que le geste par défaut était le seul irréversible ; elles ont
 * maintenant leur propre panneau, où l'on voit ce qu'on supprime avant de le
 * faire.
 *
 * Et surtout, l'action ne s'arrête plus à la mise en file : elle suit
 * jusqu'au relevé suivant (cf. `useBoucleCelcat`), étape par étape.
 */
import type { CelcatComparaison } from "../api/client";
import type { EtapeBoucle, EtatBoucle } from "../hooks/useBoucleCelcat";
import { PILULE, verdictSemaine, type Ton } from "../utils/celcatStatut";
import { CompteRenduCorrection } from "./CompteRenduCorrection";

export interface SemaineChoisissable {
  indice: number;
  libelle: string;
}

const ETAPES: Array<{ cle: EtapeBoucle; libelle: string }> = [
  { cle: "envoi", libelle: "Mise en file" },
  { cle: "attente_worker", libelle: "Passage du worker" },
  { cle: "attente_releve", libelle: "Nouveau relevé de Celcat" },
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
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
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

export function VerdictCelcat({
  semaines,
  semaine,
  onSemaine,
  donnees,
  erreur,
  boucle,
  onCorriger,
  onVerifier,
  onArreter,
  occupe,
}: {
  semaines: SemaineChoisissable[];
  semaine: number;
  onSemaine: (indice: number) => void;
  donnees: CelcatComparaison | null;
  erreur: string | null;
  boucle: EtatBoucle;
  onCorriger: () => void;
  onVerifier: () => void;
  onArreter: () => void;
  occupe: boolean;
}) {
  const position = semaines.findIndex((s) => s.indice === semaine);
  const precedente = position > 0 ? semaines[position - 1] : null;
  const suivante = position >= 0 && position < semaines.length - 1 ? semaines[position + 1] : null;

  const verdict = donnees ? verdictSemaine(donnees) : null;
  const ton: Ton = verdict?.ton ?? "attention";
  const aCorriger = verdict ? verdict.aModifier + verdict.aCreer : 0;
  const releveAbsentOuPerime = !!donnees && (!donnees.releve_le || donnees.perime);
  const enCours = boucle.etape !== "repos";
  const avecCorrection = boucle.correction !== null || boucle.etape === "envoi" || boucle.etape === "attente_worker";

  return (
    <section className={`panel celcat-verdict celcat-verdict--${verdict ? ton : "chargement"}`} aria-labelledby="celcat-verdict-titre">
      <div className="celcat-semaine-nav">
        <button
          type="button"
          className="btn btn--ghost celcat-nav-fleche"
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
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="btn btn--ghost celcat-nav-fleche"
          aria-label={suivante ? `Semaine suivante : ${suivante.libelle}` : "Pas de semaine suivante"}
          disabled={!suivante || occupe}
          onClick={() => suivante && onSemaine(suivante.indice)}
        >
          <Chevron sens="droite" />
        </button>
      </div>

      {erreur ? (
        <p className="alerte" role="alert">
          Comparaison impossible : {erreur}
        </p>
      ) : !verdict ? (
        <p className="celcat-sous-texte" aria-busy="true">
          Comparaison de la semaine avec Celcat…
        </p>
      ) : (
        <>
          <h2 id="celcat-verdict-titre" className="celcat-verdict-titre">
            <span className={`pill ${PILULE[ton]}`}>
              {ton === "ok" ? "concorde" : ton === "panne" ? "bloqué" : "à traiter"}
            </span>{" "}
            {verdict.titre}
          </h2>
          <p className="celcat-verdict-detail">{verdict.detail}</p>
        </>
      )}

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
              <button type="button" className="btn btn--ghost" disabled={occupe} onClick={onVerifier}>
                Vérifier à nouveau
              </button>
            ) : null}
          </>
        )}
        {occupe ? (
          <button type="button" className="btn btn--ghost" onClick={onArreter}>
            Arrêter d’attendre
          </button>
        ) : null}
      </div>
      {aCorriger > 0 && !releveAbsentOuPerime ? (
        <p className="celcat-sous-texte">Modifie et crée dans Celcat. Les évènements en trop ne sont jamais supprimés par ce bouton.</p>
      ) : null}

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
                return (
                  <li
                    key={cle}
                    className={`celcat-etape-suivi celcat-etape-suivi--${a === "fait" ? "fait" : a === "en cours" ? "en-cours" : "a-venir"}`}
                  >
                    <span className={`pill ${a === "fait" ? "good" : a === "en cours" ? "warn" : ""}`}>{a}</span>
                    {libelle}
                  </li>
                );
              })}
            </ol>
            ) : null}
            {boucle.message ? (
              <p className={boucle.etape === "erreur" ? "celcat-texte-panne" : boucle.etape === "interrompu" ? "celcat-texte-attention" : ""}>
                {boucle.message}
              </p>
            ) : null}
            {boucle.correction ? <CompteRenduCorrection correction={boucle.correction} /> : null}
          </>
        ) : null}
      </div>
    </section>
  );
}
