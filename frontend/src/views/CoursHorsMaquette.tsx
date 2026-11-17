/**
 * Nouveau semestre → « Cours hors maquette » (17/11/2026).
 *
 * Un module absent de la maquette officielle (intervention, atelier) se
 * déclarait dans un fichier. Il s'ajoute ici : le calcul le place comme les
 * autres, avec un seul enseignant qui voit tous les groupes.
 */
import { useEffect, useState } from "react";

import {
  ajouterCoursHorsMaquette,
  lireCoursHorsMaquette,
  retirerCoursHorsMaquette,
  type CoursHorsMaquette as Cours,
  type CoursHorsMaquetteReponse,
} from "../api/client";

const AUTRE = "__autre__";
const TYPES = [
  { cle: "cm", libelle: "CM" },
  { cle: "td", libelle: "TD" },
  { cle: "tp", libelle: "TP" },
] as const;

/** « 1 CM, 2 TD » : les séances par étudiant. */
export function volumeLisible(c: Pick<Cours, "cm" | "td" | "tp">): string {
  return TYPES.filter((t) => c[t.cle] > 0)
    .map((t) => `${c[t.cle]} ${t.libelle}`)
    .join(", ");
}

export function CoursHorsMaquette({ groupe, onModifie }: { groupe: string; onModifie: () => void }) {
  const [donnees, setDonnees] = useState<CoursHorsMaquetteReponse | null>(null);
  const [code, setCode] = useState("");
  const [nom, setNom] = useState("");
  const [semestre, setSemestre] = useState("");
  const [parcours, setParcours] = useState("");
  const [qui, setQui] = useState("");
  const [autre, setAutre] = useState({ code: "", nom: "", prenom: "" });
  const [volumes, setVolumes] = useState({ cm: 0, td: 0, tp: 0 });
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    let perime = false;
    setDonnees(null);
    setErreur(null);
    lireCoursHorsMaquette(groupe)
      .then((r) => {
        if (!perime && r?.cours && r?.semestres) setDonnees(r);
      })
      .catch(() => undefined);
    return () => {
      perime = true;
    };
  }, [groupe]);

  if (!donnees) return null;

  const promotions = donnees.semestres[semestre] ?? [];
  const enseignant =
    qui === AUTRE
      ? { code: autre.code.trim().toUpperCase(), nom: autre.nom.trim(), prenom: autre.prenom.trim() }
      : donnees.enseignants.find((e) => e.code === qui);
  const maxi = donnees.seances_maxi;
  const volumesValides = TYPES.every(
    (t) => Number.isInteger(volumes[t.cle]) && volumes[t.cle] >= 0 && volumes[t.cle] <= maxi,
  );
  const pret =
    code.trim().length >= 3 &&
    nom.trim() !== "" &&
    promotions.includes(parcours) &&
    !!enseignant &&
    enseignant.code.length >= 2 &&
    (qui !== AUTRE || enseignant.nom !== "") &&
    volumesValides &&
    volumes.cm + volumes.td + volumes.tp > 0;

  const agir = async (action: () => Promise<CoursHorsMaquetteReponse>) => {
    setOccupe(true);
    setErreur(null);
    try {
      setDonnees(await action());
      onModifie();
      return true;
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "L’enregistrement a échoué");
      return false;
    } finally {
      setOccupe(false);
    }
  };

  const nomEnseignant = (c: string) => donnees.enseignants.find((e) => e.code === c)?.libelle ?? c;

  return (
    <details className="dates-sae regles-modules">
      <summary>
        <h3>Cours hors maquette</h3>
        <span className="muted">
          {donnees.cours.length === 0
            ? "Aucun"
            : `${donnees.cours.length} module${donnees.cours.length > 1 ? "s" : ""} : ${donnees.cours
                .map((c) => c.code)
                .join(", ")}`}
        </span>
      </summary>
      <p className="muted">
        Une intervention ou un atelier absent de la maquette officielle. Le module est placé par le calcul comme les
        autres : un seul enseignant, qui voit tous les groupes de la promotion. Les volumes sont des séances de
        1 h 30 par étudiant.
      </p>
      {donnees.verrouille && <p className="muted">{donnees.verrouille}</p>}
      {donnees.cours.length > 0 && (
        <ul className="seances-annulees-liste">
          {donnees.cours.map((c) => (
            <li key={`${c.origine}-${c.code}-${c.parcours}`}>
              <span>
                <strong>{c.code}</strong> · {c.nom || "Sans intitulé"} · {c.semestre} {c.parcours} ·{" "}
                {volumeLisible(c) || "aucune séance"} · {nomEnseignant(c.teacher_code)}
                {c.origine === "livree" && <span className="muted"> · livré avec l’application</span>}
              </span>
              {c.id && !donnees.verrouille && (
                <button
                  type="button"
                  className="btn btn--sm"
                  disabled={occupe}
                  aria-label={`Retirer le module ${c.code}`}
                  onClick={() => {
                    const id = c.id;
                    if (id && window.confirm(`Retirer le module ${c.code} ?`))
                      void agir(() => retirerCoursHorsMaquette(groupe, id));
                  }}
                >
                  Retirer
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}
      {!donnees.verrouille && (
        <form
          className="seances-annulees-ajout"
          onSubmit={(e) => {
            e.preventDefault();
            if (!pret || !enseignant) return;
            void agir(() =>
              ajouterCoursHorsMaquette(groupe, {
                code: code.trim().toUpperCase(),
                nom: nom.trim(),
                semestre,
                parcours,
                teacher_code: enseignant.code,
                teacher_nom: enseignant.nom,
                teacher_prenom: enseignant.prenom,
                ...volumes,
              }),
            ).then((ok) => {
              if (ok) {
                setCode("");
                setNom("");
                setVolumes({ cm: 0, td: 0, tp: 0 });
              }
            });
          }}
        >
          <label>
            Code du module
            <input value={code} maxLength={12} placeholder="WX2ATEL" onChange={(e) => setCode(e.target.value)} />
          </label>
          <label>
            Intitulé
            <input value={nom} maxLength={120} onChange={(e) => setNom(e.target.value)} />
          </label>
          <label>
            Semestre
            <select
              value={semestre}
              onChange={(e) => {
                const s = e.target.value;
                setSemestre(s);
                const possibles = donnees.semestres[s] ?? [];
                setParcours(possibles.length === 1 ? possibles[0] : "");
              }}
            >
              <option value="">Choisir…</option>
              {Object.keys(donnees.semestres).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label>
            Promotion
            <select value={parcours} disabled={promotions.length === 0} onChange={(e) => setParcours(e.target.value)}>
              <option value="">Choisir…</option>
              {promotions.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <label>
            Enseignant
            <select value={qui} onChange={(e) => setQui(e.target.value)}>
              <option value="">Choisir…</option>
              {donnees.enseignants.map((e) => (
                <option key={e.code} value={e.code}>
                  {e.libelle} ({e.code})
                </option>
              ))}
              <option value={AUTRE}>Autre enseignant…</option>
            </select>
          </label>
          {qui === AUTRE && (
            <>
              <label>
                Code de l’enseignant
                <input
                  value={autre.code}
                  maxLength={8}
                  placeholder="VMA"
                  onChange={(e) => setAutre({ ...autre, code: e.target.value })}
                />
              </label>
              <label>
                Nom de l’enseignant
                <input value={autre.nom} onChange={(e) => setAutre({ ...autre, nom: e.target.value })} />
              </label>
              <label>
                Prénom de l’enseignant
                <input value={autre.prenom} onChange={(e) => setAutre({ ...autre, prenom: e.target.value })} />
              </label>
            </>
          )}
          {TYPES.map((t) => (
            <label key={t.cle}>
              Séances de {t.libelle}
              <span className="plafonds-champ">
                <input
                  type="number"
                  min={0}
                  max={maxi}
                  value={Number.isFinite(volumes[t.cle]) ? volumes[t.cle] : ""}
                  onChange={(e) => setVolumes({ ...volumes, [t.cle]: e.target.valueAsNumber })}
                />
              </span>
            </label>
          ))}
          <button type="submit" className="btn btn--sm" disabled={occupe || !pret}>
            Ajouter ce module
          </button>
        </form>
      )}
    </details>
  );
}
