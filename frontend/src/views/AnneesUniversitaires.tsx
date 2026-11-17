/**
 * Référence → Réglages → années universitaires (17/11/2026).
 *
 * L'application ne connaissait qu'une année, écrite dans le code. Ce bloc
 * montre ses dates, permet de préparer la suivante et d’y passer : rentrée, semestres,
 * vacances et jours fériés (ces derniers sont calculés, il reste à les
 * relire).
 */
import { useEffect, useState } from "react";

import {
  lireAnnees,
  preparerAnnee,
  retirerAnnee,
  utiliserAnnee,
  type AnneeSaisie,
  type AnneeUniversitaire,
  type AnneesReponse,
} from "../api/client";

function jour(iso: string): string {
  if (!iso) return "—";
  const [a, m, j] = iso.split("-").map(Number);
  return new Date(a, m - 1, j).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
}

/** « du 26 au 30 octobre 2026 », en toutes lettres. */
export function periodeLisible(debut: string, fin: string): string {
  return debut === fin ? `le ${jour(debut)}` : `du ${jour(debut)} au ${jour(fin)}`;
}

const DATES: { cle: "rentree" | "fin_impair" | "debut_pair" | "fin"; libelle: string }[] = [
  { cle: "rentree", libelle: "Rentrée (premier jour de cours)" },
  { cle: "fin_impair", libelle: "Dernier jour du semestre impair" },
  { cle: "debut_pair", libelle: "Premier jour du semestre pair" },
  { cle: "fin", libelle: "Dernier jour de cours de l’année" },
];

function Resume({ annee }: { annee: AnneeUniversitaire }) {
  return (
    <>
      <p>
        Cours {periodeLisible(annee.rentree, annee.fin)}. Semestre impair jusqu’au {jour(annee.fin_impair)}, semestre
        pair à partir du {jour(annee.debut_pair)}.{" "}
        <span className="muted">
          {annee.semaines} semaines de cours ({annee.semaines_impair} à l’impair, {annee.semaines_pair} au pair).
        </span>
      </p>
      <p className="muted">
        Vacances et pauses :{" "}
        {annee.vacances.length === 0
          ? "aucune"
          : annee.vacances.map((v) => periodeLisible(v.debut, v.fin)).join(" ; ")}
        .
      </p>
      <p className="muted">
        Jours fériés : {annee.feries.length === 0 ? "aucun" : annee.feries.map((f) => `${jour(f.date)} (${f.nom})`).join(", ")}.
      </p>
    </>
  );
}

function Formulaire({
  label,
  depart,
  occupe,
  onEnregistrer,
}: {
  label: string;
  depart: AnneeSaisie;
  occupe: boolean;
  onEnregistrer: (a: AnneeSaisie) => void;
}) {
  const [saisie, setSaisie] = useState<AnneeSaisie>(depart);
  useEffect(() => setSaisie(depart), [depart]);

  const pret = DATES.every((d) => saisie[d.cle] !== "");
  const vacance = (i: number, champ: "nom" | "debut" | "fin", valeur: string) =>
    setSaisie({ ...saisie, vacances: saisie.vacances.map((v, k) => (k === i ? { ...v, [champ]: valeur } : v)) });
  const ferie = (i: number, champ: "nom" | "date", valeur: string) =>
    setSaisie({ ...saisie, feries: saisie.feries.map((f, k) => (k === i ? { ...f, [champ]: valeur } : f)) });

  return (
    <form
      className="reglages-ajout"
      aria-label={`Année ${label}`}
      onSubmit={(e) => {
        e.preventDefault();
        if (pret) onEnregistrer(saisie);
      }}
    >
      <div className="reglages-champs">
        {DATES.map((d) => (
          <label key={d.cle}>
            {d.libelle}
            <input type="date" value={saisie[d.cle]} onChange={(e) => setSaisie({ ...saisie, [d.cle]: e.target.value })} />
          </label>
        ))}
      </div>
      <fieldset className="reglages-annee-liste">
        <legend>Vacances et pauses pédagogiques</legend>
        {saisie.vacances.map((v, i) => (
          <div key={i} className="reglages-annee-ligne">
            <input
              type="text"
              value={v.nom}
              aria-label={`Nom de la période ${i + 1}`}
              placeholder="Nom"
              onChange={(e) => vacance(i, "nom", e.target.value)}
            />
            <input
              type="date"
              value={v.debut}
              aria-label={`Premier jour de ${v.nom || `la période ${i + 1}`}`}
              onChange={(e) => vacance(i, "debut", e.target.value)}
            />
            <input
              type="date"
              value={v.fin}
              min={v.debut || undefined}
              aria-label={`Dernier jour de ${v.nom || `la période ${i + 1}`}`}
              onChange={(e) => vacance(i, "fin", e.target.value)}
            />
            <button
              type="button"
              className="btn btn--sm"
              aria-label={`Retirer ${v.nom || `la période ${i + 1}`}`}
              onClick={() => setSaisie({ ...saisie, vacances: saisie.vacances.filter((_, k) => k !== i) })}
            >
              Retirer
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn btn--sm"
          onClick={() => setSaisie({ ...saisie, vacances: [...saisie.vacances, { nom: "", debut: "", fin: "" }] })}
        >
          Ajouter une période
        </button>
      </fieldset>
      <fieldset className="reglages-annee-liste">
        <legend>Jours fériés (calculés, à relire)</legend>
        {saisie.feries.map((f, i) => (
          <div key={i} className="reglages-annee-ligne">
            <input
              type="text"
              value={f.nom}
              aria-label={`Nom du jour férié ${i + 1}`}
              placeholder="Nom"
              onChange={(e) => ferie(i, "nom", e.target.value)}
            />
            <input
              type="date"
              value={f.date}
              aria-label={`Date de ${f.nom || `jour férié ${i + 1}`}`}
              onChange={(e) => ferie(i, "date", e.target.value)}
            />
            <button
              type="button"
              className="btn btn--sm"
              aria-label={`Retirer ${f.nom || `le jour férié ${i + 1}`}`}
              onClick={() => setSaisie({ ...saisie, feries: saisie.feries.filter((_, k) => k !== i) })}
            >
              Retirer
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn btn--sm"
          onClick={() => setSaisie({ ...saisie, feries: [...saisie.feries, { nom: "", date: "" }] })}
        >
          Ajouter un jour férié
        </button>
      </fieldset>
      <div className="reglages-annee-actions">
        <button type="submit" className="btn btn--primary" disabled={occupe || !pret}>
          Enregistrer l’année {label}
        </button>
      </div>
    </form>
  );
}

export function AnneesUniversitaires() {
  const [donnees, setDonnees] = useState<AnneesReponse | null>(null);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let perime = false;
    lireAnnees()
      .then((r) => {
        if (!perime && r?.annees && r?.proposition) setDonnees(r);
      })
      .catch(() => undefined);
    return () => {
      perime = true;
    };
  }, []);

  if (!donnees) return null;

  const agir = async (action: () => Promise<AnneesReponse>, texte: string) => {
    setOccupe(true);
    setErreur(null);
    setMessage(null);
    try {
      setDonnees(await action());
      setMessage(texte);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "L’enregistrement a échoué");
    } finally {
      setOccupe(false);
    }
  };
  const derniere = donnees.annees[donnees.annees.length - 1];

  return (
    <section className="panel reglages-famille" aria-labelledby="reglages-annees">
      <header>
        <h2 id="reglages-annees">Années universitaires</h2>
        <p className="muted">
          Les dates qui encadrent une année : rentrée, semestres, vacances, jours fériés. L’application utilise une
          seule année à la fois, pour tous ses écrans. Préparez ici l’année suivante dès que le calendrier de
          l’établissement est connu, puis passez à cette année quand la précédente est terminée.
        </p>
      </header>
      {message && (
        <p className="reglages-message" role="status">
          {message}
        </p>
      )}
      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}
      {donnees.annees.length > 1 && donnees.verrou && (
        <p className="muted" role="note">
          Changement d’année impossible pour l’instant. {donnees.verrou}
        </p>
      )}
      {donnees.annees.map((a) => (
        <details key={a.label} className="reglages-parcours" open={a.en_cours && donnees.annees.length === 1}>
          <summary>
            {a.label}
            <span className="muted">
              {" "}
              {a.en_cours ? "(année en cours)" : a.origine ? "(année d’origine)" : "(préparée)"}
            </span>
          </summary>
          <Resume annee={a} />
          {a.origine ? (
            <p className="muted">Les dates de cette année sont celles livrées avec l’application : elles ne se modifient pas ici.</p>
          ) : (
            <Formulaire
              label={a.label}
              depart={a}
              occupe={occupe}
              onEnregistrer={(s) => void agir(() => preparerAnnee(a.label, s), `Année ${a.label} enregistrée.`)}
            />
          )}
          <div className="reglages-annee-actions">
            {!a.en_cours && (
              <button
                type="button"
                className="btn btn--sm"
                disabled={occupe || donnees.verrou !== null}
                title={donnees.verrou ?? undefined}
                onClick={() => {
                  if (
                    window.confirm(
                      `Passer toute l’application à l’année ${a.label} ? Le calendrier, les numéros de semaine et ` +
                        "les dates des semestres changent. Les brouillons déjà calculés ne pourront plus être publiés.",
                    )
                  )
                    void agir(() => utiliserAnnee(a.label), `L’application utilise maintenant l’année ${a.label}.`);
                }}
              >
                Passer à l’année {a.label}
              </button>
            )}
            {!a.origine && !a.en_cours && a.label === derniere.label && (
              <button
                type="button"
                className="btn btn--sm"
                disabled={occupe}
                onClick={() => {
                  if (window.confirm(`Retirer l’année ${a.label} ?`))
                    void agir(() => retirerAnnee(a.label), `Année ${a.label} retirée.`);
                }}
              >
                Retirer l’année {a.label}
              </button>
            )}
          </div>
        </details>
      ))}
      <details className="reglages-parcours">
        <summary>Préparer {donnees.proposition.label}</summary>
        <p className="muted">
          Les dates proposées reprennent le rythme de l’année en cours et les jours fériés sont calculés. Les
          vacances changent chaque année : saisissez-les à partir du calendrier de l’établissement, ou laissez une
          ligne vide pour l’ignorer.
        </p>
        <Formulaire
          label={donnees.proposition.label}
          depart={donnees.proposition}
          occupe={occupe}
          onEnregistrer={(s) =>
            void agir(
              () => preparerAnnee(donnees.proposition.label, s),
              `Année ${donnees.proposition.label} enregistrée.`,
            )
          }
        />
      </details>
    </section>
  );
}
