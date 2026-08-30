import { useEffect, useMemo, useState } from "react";

import { DayStrip, todayIndex } from "../components/DayStrip";
import { SemesterAgenda } from "../components/SemesterAgenda";
import { SessionGrid } from "../components/SessionGrid";
import { BoutonsImageEdt } from "../components/BoutonsImageEdt";
import { ShareBar } from "../components/ShareBar";
import { usePreferences } from "../utils/preferences";
import { TeacherLinksList } from "../components/TeacherLinksList";
import { WeekBar } from "../components/WeekBar";
import { useNarrowScreen } from "../hooks/useNarrowScreen";
import type { Route } from "../hooks/useHashRoute";
import { buildLink } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { copyToClipboard } from "../utils/clipboard";
import { sessionsWithDates, subscribeUrl } from "../utils/ics";
import { mailtoForTeacher } from "../utils/mailto";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";

interface EnseignantViewProps {
  payload: AppPayload;
  route: Route;
  setRoute: (patch: Partial<Route>) => void;
  readOnly?: boolean;
}

function displayIndexForSolverWeek(payload: AppPayload, solverWeek: number | null): number {
  if (solverWeek === null) return 0;
  const idx = payload.weekRows.findIndex((w) => w.weekIndex === solverWeek);
  return idx >= 0 ? idx : 0;
}

export function EnseignantView({ payload, route, setRoute, readOnly = false }: EnseignantViewProps) {
  const teacherCodes = useMemo(
    () =>
      Object.keys(payload.teacherLabels).sort((a, b) =>
        (payload.teacherLabels[a] ?? a).localeCompare(payload.teacherLabels[b] ?? b, "fr"),
      ),
    [payload.teacherLabels],
  );
  const [code, setCode] = useState(route.prof || teacherCodes[0] || "");
  const [displayWeek, setDisplayWeek] = useState(() => displayIndexForSolverWeek(payload, route.sem));
  const [mobileDay, setMobileDay] = useState(todayIndex());
  const narrow = useNarrowScreen();
  // Bascule "un enseignant" / "tous les liens" — retour utilisateur
  // 27/08/2026 : « ajoute moi une vue simple avec tous les lien de tous
  // les prof ». N'a de sens que côté planification (readOnly = déjà le
  // lien d'UN seul enseignant, rien à lister).
  const [showAllLinks, setShowAllLinks] = useState(false);
  const [abonnementCopie, setAbonnementCopie] = useState(false);

  useEffect(() => {
    if (route.prof && route.prof !== code) setCode(route.prof);
    if (route.sem !== null) setDisplayWeek(displayIndexForSolverWeek(payload, route.sem));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.prof, route.sem]);

  const allItems = useMemo(
    () => sessionsWithDates(payload, payload.rows.filter((r) => r.te.includes(code))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [payload, code],
  );
  const solverWeek = payload.weekRows[displayWeek]?.weekIndex ?? null;
  const rowsThisWeek = solverWeek === null ? [] : allItems.filter((r) => r.w === solverWeek);
  const couleursParMatiere = usePreferences().couleursParMatiere;

  // Heures, pas un compte de séances — retour utilisateur 28/08/2026 (relayé
  // depuis Discord, idée de Jordan) : « le nombre d'heure total de la
  // semaine ça serait cool si il pouvait être montré ».
  const hoursByWeek = new Map<number, number>();
  for (const it of allItems) hoursByWeek.set(it.w, (hoursByWeek.get(it.w) ?? 0) + (it.dur || 1) * 1.5);

  const info = payload.teachers.find((t) => t.code === code);

  const handleChangeTeacher = (next: string) => {
    setCode(next);
    setRoute({ vue: "prof", prof: next });
  };

  // `t` : rend ce lien public (cf. api/auth.py) — sans lui, il exigerait le
  // mot de passe partagé comme n'importe quelle autre page (retour
  // utilisateur 28/08/2026 : « uniquement les prof ai accès a leur lien
  // sans mot de passe », puis « on s'en fiche on veut qu'il soit public »).
  const personalLink = buildLink({ vue: "prof", prof: code, mode: "prof", t: payload.teacherTokens[code] ?? "" });

  return (
    <section className="view">
      <div className="panel controls">
        {/* Sélecteur d'enseignant caché en lecture seule (le lien personnel
            désigne déjà UN seul enseignant, pas de raison d'en changer) —
            mais la barre de semaines reste, elle : sans elle, un enseignant
            ouvrant son lien perso était bloqué sur une seule semaine dans la
            grille, sans aucun moyen de parcourir le reste du semestre
            (retour utilisateur 27/08/2026 : « on ne peut pas consulter
            toutes les semaine[s] »). C'était un oubli, pas une intention —
            rien dans `.weekfield` ci-dessous n'est propre au mode édition. */}
        {!readOnly && !showAllLinks && (
          <label>
            Enseignant
            <select value={code} onChange={(e) => handleChangeTeacher(e.target.value)}>
              {teacherCodes.map((c) => (
                <option key={c} value={c}>
                  {payload.teacherLabels[c]}
                  {payload.teachers.find((t) => t.code === c)?.hasConstraint ? " •" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        {!showAllLinks && (
          <div className="field weekfield">
            <WeekBar
              weekRows={payload.weekRows}
              countByWeekIndex={hoursByWeek}
              selected={displayWeek}
              onSelect={setDisplayWeek}
              unit="heures"
            />
          </div>
        )}
        {!readOnly && (
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => setShowAllLinks((v) => !v)}
          >
            {showAllLinks ? "← Revenir au planning" : "Tous les liens"}
          </button>
        )}
      </div>

      {showAllLinks ? (
        <TeacherLinksList payload={payload} />
      ) : (
        <>{/* le reste de la vue continue ci-dessous */}

      {/* Partage/mail/callout de conformité : utiles côté planification
          (on y prépare l'envoi du lien à CE prof), hors de propos une fois
          que c'est LUI qui regarde sa propre page via ce même lien — retiré
          en lecture seule pour ne garder que l'essentiel demandé (barre des
          semaines + planning), cf. commentaire plus bas sur `.layout`. */}
      {!readOnly && (
        <ShareBar
          onCopyLink={() => personalLink}
          onCopySubscribeLink={() => subscribeUrl("prof", code, payload.teacherTokens[code] ?? "")}
          imageEdt={() => ({
            titre: payload.teacherLabels[code] ?? code,
            sousTitre: payload.weekRows[displayWeek]?.label ?? `Semaine ${displayWeek + 1}`,
            rows: rowsThisWeek,
            payload,
            couleursParMatiere,
          })}
          extra={
            <a
              className="btn btn--ghost btn--sm"
              href={mailtoForTeacher(payload, code, allItems, personalLink)}
              title={payload.teacherEmails[code] || "Adresse inconnue — à compléter dans data/config/teacher_contacts.yaml"}
            >
              Écrire{payload.teacherEmails[code] ? "" : " ⚠"}
            </a>
          }
        />
      )}

      {!readOnly && info && (() => {
        // Compromis MOU (encadrement SAE ce jour-là, `--no-sae-supervisor-hard`)
        // distingué d'une vraie indisponibilité déclarée non respectée —
        // sinon un enseignant référent SAE ressort à tort comme "en échec"
        // au même titre qu'un enseignant dont on a réellement ignoré les
        // disponibilités (retour utilisateur 11/08/2026, cf. docs/DATA.md §59).
        const saeCount = info.violations.filter((v) => v.reason === "sae_supervision").length;
        const declaredCount = info.violations.length - saeCount;
        const anyReal = declaredCount > 0;
        return (
          <div className={`callout ${!info.hasConstraint ? "" : anyReal ? "fail" : info.violations.length ? "warn" : "pass"}`}>
            {!info.hasConstraint ? (
              <span>Aucune contrainte déclarée dans le fichier CONTRAINTES ENSEIGNANTS pour {info.name}.</span>
            ) : info.violations.length === 0 ? (
              <span>
                <span className="icon">✓</span> Contrainte respectée sur les {info.nPlaced} séance(s) placée(s) pour{" "}
                {info.name}.
              </span>
            ) : (
              <span>
                <span className="icon">{anyReal ? "!" : "i"}</span>{" "}
                {declaredCount > 0 && <>{declaredCount} vraie(s) violation(s) de disponibilité déclarée</>}
                {declaredCount > 0 && saeCount > 0 && " + "}
                {saeCount > 0 && <>{saeCount} compromis accepté(s) (encadrement SAE ce jour-là)</>}
                {" "}sur les {info.nPlaced} séance(s) placée(s) pour {info.name}.
              </span>
            )}
          </div>
        );
      })()}

      {narrow && <DayStrip selected={mobileDay} onSelect={setMobileDay} />}

      {/* Lecture seule : l'essentiel demandé (retour utilisateur
          27/08/2026, verbatim : « juste l'essentiel c'est à dire la barre
          des semaine et le planing qui fit bien l'écran ») — la grille
          seule, en pleine largeur, sans le partage `.layout` à 2 colonnes
          (qui réserverait une colonne de 300px vide à droite dès qu'il n'y
          a plus de second panneau à côté) ni les panneaux annexes
          (contraintes brutes, agenda du semestre en liste à part) : parcourir
          les semaines dans CETTE grille couvre déjà « voir tous ses cours du
          semestre », ce que demandait le message précédent. Ces panneaux
          restent tels quels côté planification (non readOnly). */}
      {readOnly ? (
        <div className="panel">
          <div className="section-header">
            <h3>{payload.weekRows[displayWeek]?.label ?? `Semaine ${displayWeek + 1}`}</h3>
            <div className="section-header-actions no-print">
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={async () => {
                  const ok = await copyToClipboard(subscribeUrl("prof", code, payload.teacherTokens[code] ?? ""));
                  if (ok) {
                    setAbonnementCopie(true);
                    setTimeout(() => setAbonnementCopie(false), 1400);
                  }
                }}
                title="Lien à coller dans Google Agenda / Apple Calendrier / Outlook — se remet à jour tout seul."
              >
                {abonnementCopie ? "Copié ✓" : "Lien agenda"}
              </button>
              {/* À CÔTÉ du lien d'abonnement, comme demandé — et surtout
                  visible ici : c'est la page que reçoit la personne, donc
                  celle depuis laquelle elle voudra partager. */}
              <BoutonsImageEdt
                options={() => ({
                  titre: payload.teacherLabels[code] ?? code,
                  sousTitre: payload.weekRows[displayWeek]?.label ?? `Semaine ${displayWeek + 1}`,
                  rows: rowsThisWeek,
                  payload,
                  couleursParMatiere,
                })}
              />
            </div>
          </div>
          {solverWeek === null ? (
            <p className="muted">Semaine bloquée (vacances/fermeture).</p>
          ) : (
            <SessionGrid payload={payload} rows={rowsThisWeek} week={solverWeek} onlyDay={narrow ? mobileDay : null} showPromo />
          )}
        </div>
      ) : (
        <>
          <div className="layout">
            <div className="panel">
              <h3>
                {payload.teacherLabels[code] ?? code} —{" "}
                {payload.weekRows[displayWeek]?.label ?? `Semaine ${displayWeek + 1}`}
              </h3>
              {solverWeek === null ? (
                <p className="muted">Semaine bloquée (vacances/fermeture).</p>
              ) : (
                <SessionGrid payload={payload} rows={rowsThisWeek} week={solverWeek} onlyDay={narrow ? mobileDay : null} showPromo />
              )}
            </div>

            {info && (info.rawIndisponibilites || info.rawDisponibilites || info.rawContraintes || info.violations.length > 0) && (
              <div className="panel">
                <h3>Sa contrainte, telle que déclarée</h3>
                {info.rawIndisponibilites && (
                  <>
                    <div className="raw-label">Indisponibilités déclarées</div>
                    <div className="raw">{info.rawIndisponibilites}</div>
                  </>
                )}
                {info.rawDisponibilites && (
                  <>
                    <div className="raw-label">Disponibilités déclarées</div>
                    <div className="raw">{info.rawDisponibilites}</div>
                  </>
                )}
                {info.rawContraintes && (
                  <>
                    <div className="raw-label">Contraintes / progression</div>
                    <div className="raw">{info.rawContraintes}</div>
                  </>
                )}
                {info.violations.length > 0 && (
                  <>
                    <div className="raw-label">Violations détectées</div>
                    <div className="slotlist">
                      {info.violations.map((v, i) => (
                        <span
                          key={i}
                          className={`slotchip${v.reason === "sae_supervision" ? " sae" : ""}`}
                          title={v.reason === "sae_supervision" ? "Compromis accepté : encadrement SAE ce jour-là (objectif mou)" : "Indisponibilité déclarée non respectée"}
                        >
                          {v.course_code} —{" "}
                          {v.date ?? `sem.${(v.week ?? 0) + 1} ${DAY_LABELS[v.day ?? 0]} ${SLOT_TIMES[v.slot ?? 0]?.label ?? ""}`}
                        </span>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          <div className="panel">
            <h3>Toutes ses interventions du semestre</h3>
            <SemesterAgenda payload={payload} items={allItems} showPromo />
          </div>
        </>
      )}
        </>
      )}
    </section>
  );
}
