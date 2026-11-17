/**
 * Nouveau semestre → « Dates des SAE » (lot 6, 16/11/2026).
 *
 * Le fichier de l'établissement ne date pas les SAE de S2, S4 et S6. Sans
 * dates, rien n'est sanctuarisé : le calcul placerait des cours classiques
 * sur les journées de projet. Ici, l'administrateur saisit les journées de
 * chaque SAE par périodes (du… au…), avant de générer.
 */
import { useEffect, useState } from "react";
import { X } from "lucide-react";

import {
  ajouterPhaseSae,
  confierSaeAuCalcul,
  lireDatesSae,
  retirerPhaseSae,
  saisirDatesSae,
  type DatesSaeReponse,
  type SaeDuSemestre,
} from "../api/client";

const JOUR = new Intl.DateTimeFormat("fr-FR", {
  day: "numeric",
  month: "short",
});
const JOUR_AN = new Intl.DateTimeFormat("fr-FR", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

function versDate(iso: string): Date {
  return new Date(`${iso}T12:00:00`);
}

function versIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Les jours ouvrés (lundi à vendredi) de `debut` à `fin` compris. */
export function joursOuvres(debut: string, fin: string): string[] {
  const sortie: string[] = [];
  const d = versDate(debut);
  const limite = versDate(fin || debut);
  if (Number.isNaN(d.getTime()) || Number.isNaN(limite.getTime()))
    return sortie;
  for (let garde = 0; d <= limite && garde < 200; garde += 1) {
    if (d.getDay() >= 1 && d.getDay() <= 5) sortie.push(versIso(d));
    d.setDate(d.getDate() + 1);
  }
  return sortie;
}

/** Regroupe des dates en périodes de jours ouvrés qui se suivent (un
 * vendredi et le lundi suivant se suivent). */
export function periodes(dates: string[]): string[][] {
  const sortie: string[][] = [];
  for (const iso of [...dates].sort()) {
    const derniere = sortie[sortie.length - 1];
    if (derniere) {
      const veille = versDate(derniere[derniere.length - 1]);
      const ecart = Math.round(
        (versDate(iso).getTime() - veille.getTime()) / 86_400_000,
      );
      if (ecart === 1 || (ecart === 3 && veille.getDay() === 5)) {
        derniere.push(iso);
        continue;
      }
    }
    sortie.push([iso]);
  }
  return sortie;
}

function libellePeriode(p: string[]): string {
  if (p.length === 1) return JOUR_AN.format(versDate(p[0]));
  return `${JOUR.format(versDate(p[0]))} – ${JOUR_AN.format(versDate(p[p.length - 1]))}`;
}

function nbJours(n: number): string {
  return `${n} jour${n > 1 ? "s" : ""}`;
}

function LigneSae({
  sae,
  verrouille,
  occupe,
  onDates,
  onAction,
}: {
  sae: SaeDuSemestre;
  verrouille: boolean;
  occupe: boolean;
  onDates: (dates: string[]) => void;
  onAction: (action: (groupe: string) => Promise<DatesSaeReponse>) => void;
}) {
  const [debut, setDebut] = useState("");
  const [fin, setFin] = useState("");
  const [motifCalcul, setMotifCalcul] = useState("");
  const [phase, setPhase] = useState({ qui: "", debut: "", fin: "", motif: "" });
  const enseignants = sae.enseignants ?? [];
  const phases = sae.phases ?? [];
  const datee = sae.dates_officielles.length + sae.dates_saisies.length > 0;
  const aucune = sae.dates_officielles.length + sae.dates_saisies.length === 0;
  const ajout = debut ? joursOuvres(debut, fin || debut) : [];

  return (
    <li className="dates-sae-ligne">
      <div className="dates-sae-quoi">
        <div className="dates-sae-titre">
          <strong>{sae.code}</strong> <span>{sae.nom}</span>
          <span className="muted">
            {" "}
            · {sae.semestre} · {sae.seances} séance{sae.seances > 1 ? "s" : ""}
          </span>
        </div>
        <div className="dates-sae-dates">
          {aucune &&
            (sae.placee_par_le_calcul ? (
              <span className="pill">Placée par le calcul</span>
            ) : (
              <span className="pill warn">Aucune date</span>
            ))}
          {periodes(sae.dates_officielles).map((p) => (
            <span
              key={p[0]}
              className="pill"
              title={`${nbJours(p.length)}, fichier de l’établissement`}
            >
              {libellePeriode(p)}
            </span>
          ))}
          {periodes(sae.dates_saisies).map((p) => (
            <span
              key={p[0]}
              className="pill good dates-sae-saisie"
              title={nbJours(p.length)}
            >
              {libellePeriode(p)}
              {!verrouille && (
                <button
                  type="button"
                  disabled={occupe}
                  aria-label={`Retirer ${libellePeriode(p)} de ${sae.code}`}
                  onClick={() =>
                    onDates(sae.dates_saisies.filter((d) => !p.includes(d)))
                  }
                >
                  <X size={12} aria-hidden="true" />
                </button>
              )}
            </span>
          ))}
        </div>
      </div>
      {!verrouille && !sae.placee_par_le_calcul && (
        <form
          className="dates-sae-ajout"
          onSubmit={(e) => {
            e.preventDefault();
            if (ajout.length === 0) return;
            onDates([...new Set([...sae.dates_saisies, ...ajout])].sort());
            setDebut("");
            setFin("");
          }}
        >
          <label>
            Du
            <input
              type="date"
              value={debut}
              aria-label={`${sae.code}, du`}
              onChange={(e) => setDebut(e.target.value)}
            />
          </label>
          <label>
            au
            <input
              type="date"
              value={fin}
              min={debut || undefined}
              aria-label={`${sae.code}, au`}
              onChange={(e) => setFin(e.target.value)}
            />
          </label>
          <button
            type="submit"
            className="btn btn--sm"
            disabled={occupe || ajout.length === 0}
          >
            Ajouter{ajout.length > 0 ? ` ${nbJours(ajout.length)}` : ""}
          </button>
        </form>
      )}
      {(phases.length > 0 || (!verrouille && (datee ? enseignants.length > 1 : true))) && (
        <details className="dates-sae-plus">
          <summary>
            {datee ? "Qui encadre, et quand" : "Placement par le calcul"}
            {phases.length > 0 && (
              <span className="muted">
                {" "}
                · {phases.length} période{phases.length > 1 ? "s" : ""}
              </span>
            )}
          </summary>
          {!datee && !verrouille && (
            <div className="dates-sae-calcul">
              {sae.placee_par_le_calcul ? (
                sae.placement_saisi ? (
                  <button
                    type="button"
                    className="btn btn--sm"
                    disabled={occupe}
                    onClick={() => onAction((g) => confierSaeAuCalcul(g, sae.code, false, ""))}
                  >
                    Ne plus la faire placer par le calcul
                  </button>
                ) : (
                  <span className="muted">Réglage d’origine : le calcul place ses séances.</span>
                )
              ) : (
                <>
                  <p className="muted">
                    Sans journées réservées, le calcul peut placer les séances de cette SAE une par une,
                    comme celles d’un module.
                  </p>
                  <label className="seances-annulees-motif">
                    Motif
                    <input
                      type="text"
                      value={motifCalcul}
                      maxLength={300}
                      aria-label={`${sae.code}, motif du placement par le calcul`}
                      placeholder="Qui le demande, et pourquoi"
                      onChange={(e) => setMotifCalcul(e.target.value)}
                    />
                  </label>
                  <button
                    type="button"
                    className="btn btn--sm"
                    disabled={occupe || !motifCalcul.trim()}
                    onClick={() =>
                      onAction((g) => confierSaeAuCalcul(g, sae.code, true, motifCalcul.trim()))
                    }
                  >
                    Faire placer cette SAE par le calcul
                  </button>
                </>
              )}
            </div>
          )}
          {datee && (
            <>
              <p className="muted">
                Sans période, chaque enseignant de la SAE est tenu pour pris toutes ses journées. Avec une
                période, il ne l’est que ces jours-là et reste disponible pour ses cours le reste du temps.
              </p>
              {phases.length > 0 && (
                <ul className="dates-sae-phases">
                  {phases.map((p, i) => (
                    <li key={p.id ?? `livree-${i}`}>
                      <span>
                        <strong>{p.nom}</strong> · {libellePeriode([p.debut, p.fin].slice(0, p.debut === p.fin ? 1 : 2))}
                        {p.sauf.length > 0 && `, sauf ${nbJours(p.sauf.length)}`}
                        {p.motif && <span className="muted"> · {p.motif}</span>}
                      </span>
                      {p.origine === "livree" ? (
                        <span className="pill" title="Période livrée avec l’application">
                          D’origine
                        </span>
                      ) : (
                        !verrouille &&
                        p.id && (
                          <button
                            type="button"
                            className="btn btn--sm"
                            disabled={occupe}
                            aria-label={`Retirer la période de ${p.nom} sur ${sae.code}`}
                            onClick={() => onAction((g) => retirerPhaseSae(g, sae.code, p.id!))}
                          >
                            Retirer
                          </button>
                        )
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {!verrouille && enseignants.length > 0 && (
                <form
                  className="dates-sae-ajout"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (!phase.qui || !phase.debut) return;
                    onAction((g) =>
                      ajouterPhaseSae(g, sae.code, {
                        teacher_code: phase.qui,
                        debut: phase.debut,
                        fin: phase.fin || phase.debut,
                        motif: phase.motif.trim(),
                      }),
                    );
                    setPhase({ qui: "", debut: "", fin: "", motif: "" });
                  }}
                >
                  <label>
                    Enseignant
                    <select
                      value={phase.qui}
                      aria-label={`${sae.code}, enseignant de la période`}
                      onChange={(e) => setPhase({ ...phase, qui: e.target.value })}
                    >
                      <option value="">Choisir…</option>
                      {enseignants.map((x) => (
                        <option key={x.code} value={x.code}>
                          {x.nom}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Du
                    <input
                      type="date"
                      value={phase.debut}
                      aria-label={`${sae.code}, période du`}
                      onChange={(e) => setPhase({ ...phase, debut: e.target.value })}
                    />
                  </label>
                  <label>
                    au
                    <input
                      type="date"
                      value={phase.fin}
                      min={phase.debut || undefined}
                      aria-label={`${sae.code}, période au`}
                      onChange={(e) => setPhase({ ...phase, fin: e.target.value })}
                    />
                  </label>
                  <label>
                    Note
                    <input
                      type="text"
                      value={phase.motif}
                      maxLength={300}
                      aria-label={`${sae.code}, note de la période`}
                      onChange={(e) => setPhase({ ...phase, motif: e.target.value })}
                    />
                  </label>
                  <button type="submit" className="btn btn--sm" disabled={occupe || !phase.qui || !phase.debut}>
                    Ajouter la période
                  </button>
                </form>
              )}
            </>
          )}
        </details>
      )}
    </li>
  );
}

export function DatesSae({
  groupe,
  onModifie,
}: {
  groupe: string;
  onModifie: () => void;
}) {
  const [donnees, setDonnees] = useState<DatesSaeReponse | null>(null);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [ouvert, setOuvert] = useState(false);

  useEffect(() => {
    let perime = false;
    setDonnees(null);
    setErreur(null);
    lireDatesSae(groupe)
      .then((r) => {
        if (perime || !Array.isArray(r?.sae)) return;
        setDonnees(r);
        // Ouvert d'emblée s'il reste des SAE à dater ; ensuite, c'est
        // l'utilisateur qui plie ou déplie.
        setOuvert(
          r.sae.some(
            (s) =>
              s.dates_officielles.length + s.dates_saisies.length === 0 &&
              !s.placee_par_le_calcul,
          ),
        );
      })
      .catch(() => undefined);
    return () => {
      perime = true;
    };
  }, [groupe]);

  if (!donnees || donnees.sae.length === 0) return null;

  const sansDate = donnees.sae.filter(
    (s) =>
      s.dates_officielles.length + s.dates_saisies.length === 0 &&
      !s.placee_par_le_calcul,
  ).length;

  const enregistrer = (sae: SaeDuSemestre, dates: string[]) =>
    agir(() => saisirDatesSae(groupe, sae.code, dates));

  const agir = async (action: () => Promise<DatesSaeReponse>) => {
    setOccupe(true);
    setErreur(null);
    try {
      setDonnees(await action());
      onModifie();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "L’enregistrement a échoué");
    } finally {
      setOccupe(false);
    }
  };

  return (
    <details
      className="dates-sae"
      open={ouvert}
      onToggle={(e) => setOuvert(e.currentTarget.open)}
    >
      <summary>
        <h3>Dates des SAE</h3>
        <span className="muted">
          {sansDate > 0
            ? `${sansDate} sur ${donnees.sae.length} sans date`
            : `${donnees.sae.length} SAE, toutes datées ou placées par le calcul`}
        </span>
      </summary>
      <p className="muted">
        Les journées d’une SAE sont réservées au projet : le calcul n’y place
        aucun cours classique pour la promotion concernée. Saisissez-les par
        périodes, du lundi au vendredi.
      </p>
      {donnees.verrouille && <p className="muted">{donnees.verrouille}</p>}
      {erreur && (
        <p className="alerte" role="alert">
          {erreur}
        </p>
      )}
      <ul>
        {donnees.sae.map((s) => (
          <LigneSae
            key={s.code}
            sae={s}
            verrouille={donnees.verrouille !== null}
            occupe={occupe}
            onDates={(dates) => void enregistrer(s, dates)}
            onAction={(action) => void agir(() => action(groupe))}
          />
        ))}
      </ul>
    </details>
  );
}
