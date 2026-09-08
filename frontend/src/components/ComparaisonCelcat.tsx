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

import { fetchCelcatComparaison, type CelcatComparaison, type LigneComparaison } from "../api/client";
import { CopyButton } from "./CopyButton";

const JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi"];

const LIBELLE: Record<LigneComparaison["statut"], string> = {
  ecart: "Écart",
  absente_celcat: "Absente de Celcat",
  en_trop_celcat: "En trop dans Celcat",
  identique: "Identique",
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

  const aAgir = toutes.filter((l) => l.statut !== "identique");
  const identiques = toutes.filter((l) => l.statut === "identique");

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
