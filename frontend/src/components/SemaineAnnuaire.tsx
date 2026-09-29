/**
 * Annuaire de la Vue Semaine (gabarit v2) : quand « Afficher par »
 * Enseignant ou Salle n'a pas encore de cible, la grille laisse place à la
 * liste des enseignants (ou des salles) avec leurs chiffres de la semaine
 * affichée — jamais une boîte vide « choisissez… ». Filtrable, triable ; un
 * clic affiche la semaine de cette personne (ou de cette salle).
 */
import { useMemo, useState } from "react";

import type { Placement, RoomMeta } from "../types";
import { nomComplet } from "../utils/nomEnseignant";
import "./SemaineAnnuaire.css";

interface EntreeAnnuaire {
  id: string;
  nom: string;
  /** Code enseignant, capacité de la salle… */
  detail?: string;
}

interface SemaineAnnuaireProps {
  genre: "enseignant" | "salle";
  /** Enseignants : leurs codes et noms (« JOAN LEFEVRE »). */
  enseignants?: string[];
  teacherLabels?: Record<string, string>;
  /** Salles : le référentiel. */
  salles?: RoomMeta[];
  /** Séances de la semaine affichée (toutes cibles confondues). */
  seancesSemaine: Placement[];
  onChoisir: (id: string) => void;
}

type Tri = "nom" | "heures";

/** Nombre au format français, sans décimale inutile : « 4,5 ». */
function heures(n: number): string {
  return n.toLocaleString("fr-FR", { maximumFractionDigits: 1 });
}

function sansAccents(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export function SemaineAnnuaire({
  genre,
  enseignants = [],
  teacherLabels = {},
  salles = [],
  seancesSemaine,
  onChoisir,
}: SemaineAnnuaireProps) {
  const [filtre, setFiltre] = useState("");
  const [tri, setTri] = useState<Tri>("nom");

  const entrees = useMemo<EntreeAnnuaire[]>(
    () =>
      genre === "enseignant"
        ? enseignants.map((c) => ({ id: c, nom: teacherLabels[c] ? nomComplet(teacherLabels[c]!) : c, detail: c }))
        : salles.map((r) => ({ id: r.id, nom: r.label, detail: r.capacity ? `${r.capacity} places` : undefined })),
    [genre, enseignants, teacherLabels, salles],
  );

  const chiffres = useMemo(() => {
    const m = new Map<string, { seances: number; heures: number }>();
    for (const p of seancesSemaine) {
      const cles = genre === "enseignant" ? p.teacher_codes : p.room_id ? [p.room_id] : [];
      for (const c of cles) {
        const avant = m.get(c) ?? { seances: 0, heures: 0 };
        m.set(c, { seances: avant.seances + 1, heures: avant.heures + Math.max(1, p.duration_slots || 1) * 1.5 });
      }
    }
    return m;
  }, [seancesSemaine, genre]);

  const lignes = useMemo(() => {
    const cherche = sansAccents(filtre.trim());
    const liste = entrees
      .filter((e) => !cherche || sansAccents(`${e.nom} ${e.detail ?? ""} ${e.id}`).includes(cherche))
      .map((e) => ({ ...e, ...(chiffres.get(e.id) ?? { seances: 0, heures: 0 }) }));
    liste.sort((a, b) =>
      tri === "heures" ? b.heures - a.heures || a.nom.localeCompare(b.nom, "fr") : a.nom.localeCompare(b.nom, "fr"),
    );
    return liste;
  }, [entrees, chiffres, filtre, tri]);

  const actifs = lignes.filter((l) => l.seances > 0).length;
  const libelle = genre === "enseignant" ? "enseignant" : "salle";
  const pluriel = genre === "enseignant" ? "enseignants" : "salles";

  return (
    <div className="semaine-annuaire">
      <div className="semaine-annuaire-outils">
        <input
          type="search"
          value={filtre}
          onChange={(e) => setFiltre(e.target.value)}
          placeholder={genre === "enseignant" ? "Filtrer par nom ou code…" : "Filtrer par nom de salle…"}
          aria-label={genre === "enseignant" ? "Filtrer les enseignants" : "Filtrer les salles"}
        />
        <p className="semaine-annuaire-compte" aria-live="polite">
          {lignes.length} {lignes.length > 1 ? pluriel : libelle} · {actifs} avec cours cette semaine
        </p>
        <div className="semaine-annuaire-tri" role="group" aria-label="Trier">
          <button type="button" aria-pressed={tri === "nom"} onClick={() => setTri("nom")}>
            Par nom
          </button>
          <button type="button" aria-pressed={tri === "heures"} onClick={() => setTri("heures")}>
            Par heures
          </button>
        </div>
      </div>
      <div className="semaine-annuaire-defil">
        <table className={`ref semaine-annuaire-table semaine-annuaire-table--${genre}`}>
          <thead>
            <tr>
              <th scope="col">{genre === "enseignant" ? "Enseignant" : "Salle"}</th>
              <th scope="col">{genre === "enseignant" ? "Code" : "Capacité"}</th>
              <th scope="col" className="num">
                Séances
              </th>
              <th scope="col" className="num">
                Heures
              </th>
            </tr>
          </thead>
          <tbody>
            {lignes.map((l) => (
              <tr key={l.id} className={l.seances ? undefined : "semaine-annuaire-libre"}>
                <td>
                  <button type="button" className="semaine-annuaire-nom" onClick={() => onChoisir(l.id)}>
                    {l.nom}
                  </button>
                </td>
                <td className="semaine-annuaire-detail">{l.detail ?? ""}</td>
                <td className="num">{l.seances || "—"}</td>
                <td className="num">{l.seances ? `${heures(l.heures)} h` : "—"}</td>
              </tr>
            ))}
            {lignes.length === 0 && (
              <tr>
                <td colSpan={4} className="semaine-annuaire-vide">
                  Aucun{genre === "salle" ? "e" : ""} {libelle} ne correspond à « {filtre} ».
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
