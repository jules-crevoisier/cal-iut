/**
 * Celcat vs cal-iut, côte à côte, pour une semaine.
 *
 * Demande utilisateur 08/09/2026 : « je voudrais un peu une interface promo
 * où l'on voit ce qu'il y a dans Celcat et que l'on puisse comparer avec ce
 * que l'on a sur cal-iut ».
 *
 * Le rapprochement est fait PAR LE SERVEUR (`celcat/comparaison.py`) : ses
 * règles — matière, groupe, jour, et l'heure avec son décalage de 9'21" dû
 * au fuseau historique de Paris — y sont déjà écrites et testées. Ce
 * composant ne juge rien, il affiche.
 *
 * Deux partis pris d'affichage, tirés de la semaine écoulée :
 *
 *   - les lignes qui DEMANDENT une action passent en premier (le serveur les
 *     trie ainsi) et les lignes identiques sont repliées derrière un compte.
 *     Un écran de supervision où l'on doit chercher le problème parmi cent
 *     lignes vertes ne sert à rien ;
 *
 *   - l'âge du relevé est affiché AVEC la comparaison. Comparer contre un
 *     instantané de trois heures en le présentant comme l'état courant
 *     serait exactement la faute réparée cette semaine — une information qui
 *     a l'air fraîche sans l'être.
 */
import { useCallback, useEffect, useState } from "react";

import {
  corrigerEcartsCelcat,
  fetchCelcatComparaison,
  type CelcatComparaison,
  type LigneComparaison,
} from "../api/client";
import { confirmAsync } from "../utils/confirmDialog";
import { EtatFileCelcat } from "./EtatFileCelcat";
import { CopyButton } from "./CopyButton";

const JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi"];

const LIBELLE: Record<LigneComparaison["statut"], string> = {
  ecart: "Écart",
  absente_celcat: "Absente de Celcat",
  en_trop_celcat: "En trop dans Celcat",
  identique: "Identique",
  hors_celcat: "Hors Celcat",
};

function jour(n: number | null | undefined): string {
  return typeof n === "number" && n >= 0 && n < JOURS.length ? JOURS[n] : "—";
}

/** « mardi 08/09 » plutôt que « mardi » : un jour sans date oblige à
 * recompter depuis le numéro de semaine pour savoir de quoi on parle —
 * et c'est justement en comptant qu'on se trompe. */
function jourDate(n: number | null | undefined, lundi: string | null): string {
  const nom = jour(n);
  if (!lundi || typeof n !== "number" || n < 0 || n >= JOURS.length) return nom;
  const d = new Date(`${lundi}T00:00:00`);
  if (Number.isNaN(d.getTime())) return nom;
  d.setDate(d.getDate() + n);
  return `${nom} ${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function texteLignes(lignes: LigneComparaison[]): string {
  return lignes
    .map((l) => {
      const gauche = l.caliut ? `${jour(l.caliut.jour)} ${l.caliut.heure} ${l.caliut.salle ?? ""}` : "—";  // texte copié : le nom suffit
      const droite = l.celcat
        ? `${jour(l.celcat.jour)} ${l.celcat.heure ?? ""} ${l.celcat.salle ?? ""} (event_id=${l.celcat.event_id})`
        : "—";
      return `${LIBELLE[l.statut]} | ${l.session_id || l.course_code} | cal-iut: ${gauche} | Celcat: ${droite}`;
    })
    .join("\n");
}

export function ComparaisonCelcat({ semaine }: { semaine: number }) {
  const [donnees, setDonnees] = useState<CelcatComparaison | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [voirIdentiques, setVoirIdentiques] = useState(false);
  const [correction, setCorrection] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);

  const charger = useCallback(async () => {
    try {
      setDonnees(await fetchCelcatComparaison(semaine));
      setErreur(null);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Comparaison impossible");
    }
  }, [semaine]);

  useEffect(() => {
    void charger();
  }, [charger]);

  if (erreur) return <p className="alerte" role="alert">{erreur}</p>;
  if (!donnees) return <p className="muted">Chargement…</p>;

  // `?? []` et `!donnees.releve_le` plutôt que `=== null` : une réponse
  // inattendue (serveur plus ancien, erreur enveloppée) ne doit pas faire
  // planter tout l'écran Celcat autour. Le même oubli avait déjà cassé le
  // panneau instantané quelques heures plus tôt.
  const toutes = donnees.lignes ?? [];
  if (!donnees.releve_le) {
    return (
      <p className="muted" data-testid="comparaison-sans-releve">
        Aucun relevé Celcat pour l’instant — rien à comparer. Utilisez « Rafraîchir » ci-dessus.
      </p>
    );
  }

  // « hors_celcat » n'est pas un écart : ce sont des séances sans équivalent
  // module dans Celcat (BU, évènements officiels) — rien à corriger, et les
  // mélanger aux vrais écarts noierait ces derniers.
  const aAgir = toutes.filter((l) => l.statut !== "identique" && l.statut !== "hors_celcat");
  const identiques = toutes.filter((l) => l.statut === "identique");
  const horsCelcat = toutes.filter((l) => l.statut === "hors_celcat");

  const corrigerTout = async (supprimer = true) => {
    const suppressions = aAgir.filter((l) => l.statut === "en_trop_celcat").length;
    if (!supprimer) {
      // Pas de confirmation : sans suppression, l'action est rattrapable —
      // une modification de trop se re-corrige, une suppression non. Demander
      // pour un geste sûr apprend à cliquer « oui » sans lire, et c'est
      // justement ce qui rend la confirmation des suppressions inutile.
      setEnCours(true);
      try {
        setCorrection((await corrigerEcartsCelcat(semaine, { supprimer: false })).message);
        setErreur(null);
      } catch (e) {
        setErreur(e instanceof Error ? e.message : "Correction impossible");
      } finally {
        setEnCours(false);
      }
      return;
    }
    // Une confirmation, pas une par ligne : l'action est irréversible côté
    // Celcat, et le nombre de SUPPRESSIONS est ce qu'il faut voir avant de
    // valider — créer en trop se rattrape, supprimer non.
    const ok = await confirmAsync(
      `${aAgir.length} correction(s) vont être mises en file pour Celcat, dont ` +
        `${suppressions} suppression(s) définitive(s).

` +
        "Le worker les poussera à son prochain passage.",
      {
        title: "Corriger les écarts de cette semaine",
        confirmLabel: "Envoyer les corrections",
      },
    );
    if (!ok) return;
    setEnCours(true);
    try {
      const r = await corrigerEcartsCelcat(semaine);
      setCorrection(r.message);
      setErreur(null);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Correction impossible");
    } finally {
      setEnCours(false);
    }
  };

  return (
    <div data-testid="comparaison-celcat">
      <p className={donnees.perime ? "bad" : "muted"}>
        {/* La DATE, pas un numéro : l'app numérote les semaines autrement que
            l'indice interne, et deux numérotations pour la même chose font
            comparer la mauvaise semaine sans s'en apercevoir. */}
        {donnees.lundi
          ? `Semaine du lundi ${donnees.lundi.split("-").reverse().slice(0, 2).join("/")}`
          : `Semaine ${donnees.semaine + 1}`}{" "}
        — {aAgir.length} écart(s) sur {toutes.length} séance(s)
        {donnees.perime ? " — relevé périmé, à rafraîchir" : ""}
      </p>

      {aAgir.length === 0 ? (
        <p className="muted">Tout concorde avec Celcat sur cette semaine.</p>
      ) : (
        <>
          <CopyButton text={() => texteLignes(aAgir)} idleLabel="Copier les écarts" />
          {/* « tous les écarts » se lisait « toutes les semaines » : le
              bouton n'a jamais agi que sur la semaine affichée, mais rien ne
              le disait (signalé le 08/09/2026). Le libellé porte donc
              maintenant sa portée. */}
          <button type="button" disabled={enCours} onClick={() => void corrigerTout()}>
            Corriger les écarts de cette semaine
          </button>
          {/* Le mode sûr quand quelqu'un travaille dans Celcat en même temps :
              un écart mal poussé se re-corrige, une suppression non. Le
              08/09/2026, quatre des neuf « en trop » de la semaine 1 venaient
              d'être créés à la main par un collègue en train de corriger. */}
          {aAgir.some((l) => l.statut === "en_trop_celcat") ? (
            <button
              type="button"
              disabled={enCours}
              data-testid="corriger-sans-supprimer"
              onClick={() => void corrigerTout(false)}
            >
              Corriger sans supprimer
            </button>
          ) : null}
          {correction ? <p className="muted">{correction}</p> : null}
          {/* Ce qui attend et ce que le worker en a fait : sans ça, le
              bouton annonçait un envoi et plus rien ne suivait. */}
          <EtatFileCelcat />
          <table className="comparaison-table">
            <thead>
              <tr>
                <th>Séance</th>
                <th>cal-iut</th>
                <th>Celcat</th>
                <th>Verdict</th>
              </tr>
            </thead>
            <tbody>
              {aAgir.map((l, i) => (
                <tr key={`${l.session_id || l.course_code}-${i}`} className={`comparaison-${l.statut}`}>
                  <td>{l.session_id || l.course_code}</td>
                  <td>
                    {l.caliut
                      ? `${jourDate(l.caliut.jour, donnees.lundi)} ${l.caliut.heure}${l.caliut.salle ? ` — ${l.caliut.salle}` : ""}`
                      : "—"}
                  </td>
                  <td>
                    {l.celcat
                      ? `${jourDate(l.celcat.jour, donnees.lundi)} ${l.celcat.heure ?? ""}${l.celcat.salle ? ` — ${l.celcat.salle}` : ""}`
                      : "—"}
                  </td>
                  <td>
                    <span className={`pill mini ${l.statut === "identique" ? "good" : "bad"}`}>
                      {LIBELLE[l.statut]}
                    </span>
                    {l.ecarts.length ? <span className="muted"> ({l.ecarts.join(", ")})</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {horsCelcat.length > 0 ? (
        <p className="muted">
          {horsCelcat.length} séance(s) sans équivalent dans Celcat (BU, évènements officiels) —
          ignorées.
        </p>
      ) : null}

      {identiques.length > 0 ? (
        <p className="muted">
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => setVoirIdentiques((v) => !v)}>
            {voirIdentiques ? "Masquer" : "Afficher"} les {identiques.length} séance(s) identique(s)
          </button>
        </p>
      ) : null}
      {voirIdentiques ? (
        <ul className="celcat-journal-list" data-testid="comparaison-identiques">
          {identiques.map((l, i) => (
            <li key={`${l.session_id}-${i}`} className="celcat-journal-item">
              {l.session_id} — {jour(l.caliut?.jour)} {l.caliut?.heure}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
