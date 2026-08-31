import { useEffect, useMemo, useState } from "react";

import { DayStrip, todayIndex } from "../components/DayStrip";
import { SemesterAgenda } from "../components/SemesterAgenda";
import { SessionGrid } from "../components/SessionGrid";
import { BoutonsImageEdt } from "../components/BoutonsImageEdt";
import { CopyButton } from "../components/CopyButton";
import { ShareBar } from "../components/ShareBar";
import { usePreferences } from "../utils/preferences";
import { WeekBar } from "../components/WeekBar";
import { useNarrowScreen } from "../hooks/useNarrowScreen";
import type { Route } from "../hooks/useHashRoute";
import { buildLink } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { sessionsWithDates, subscribeUrl } from "../utils/ics";

interface GroupeViewProps {
  payload: AppPayload;
  route: Route;
  setRoute: (patch: Partial<Route>) => void;
  readOnly?: boolean;
}

/** Index d'affichage (dans `weekRows`, vacances incluses) le plus proche
 * d'une semaine SOLVEUR donnée — sert à faire pointer la `WeekBar` au bon
 * endroit quand on arrive depuis un lien qui ne connaît que l'index solveur
 * (recherche, panneau « à traiter »). */
function displayIndexForSolverWeek(payload: AppPayload, solverWeek: number | null): number {
  if (solverWeek === null) return 0;
  const idx = payload.weekRows.findIndex((w) => w.weekIndex === solverWeek);
  return idx >= 0 ? idx : 0;
}

export function GroupeView({ payload, route, setRoute, readOnly = false }: GroupeViewProps) {
  const groupIds = useMemo(
    () =>
      Object.keys(payload.groupLabels).sort((a, b) =>
        (payload.groupLabels[a] ?? a).localeCompare(payload.groupLabels[b] ?? b, "fr"),
      ),
    [payload.groupLabels],
  );
  const [groupId, setGroupId] = useState(route.groupe || payload.defaultGroup || groupIds[0] || "");
  const [displayWeek, setDisplayWeek] = useState(() => displayIndexForSolverWeek(payload, route.sem));
  const [mobileDay, setMobileDay] = useState(todayIndex());
  const narrow = useNarrowScreen();

  // Resynchronise depuis un lien externe (recherche, « à traiter ») qui ne
  // touche que la route sans démonter cette vue.
  useEffect(() => {
    if (route.groupe && route.groupe !== groupId) setGroupId(route.groupe);
    if (route.sem !== null) setDisplayWeek(displayIndexForSolverWeek(payload, route.sem));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.groupe, route.sem]);

  const cohort = new Set(payload.groupCohort[groupId] ?? [groupId]);
  const allItems = useMemo(
    () => sessionsWithDates(payload, payload.rows.filter((r) => r.g.some((g) => cohort.has(g)))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [payload, groupId],
  );
  const solverWeek = payload.weekRows[displayWeek]?.weekIndex ?? null;
  const rowsThisWeek = solverWeek === null ? [] : allItems.filter((r) => r.w === solverWeek);
  const couleursParMatiere = usePreferences().couleursParMatiere;

  // Heures, pas un compte de séances — retour utilisateur 28/08/2026 (relayé
  // depuis Discord, idée de Jordan) : « le nombre d'heure total de la
  // semaine ça serait cool si il pouvait être montré ».
  const hoursByWeek = new Map<number, number>();
  for (const it of allItems) hoursByWeek.set(it.w, (hoursByWeek.get(it.w) ?? 0) + (it.dur || 1) * 1.5);

  const tpPair = payload.groupTpPair[groupId];
  const parcours = payload.groupParcours[groupId] ?? "";

  const handleChangeGroup = (gid: string) => {
    setGroupId(gid);
    setRoute({ vue: "groupe", groupe: gid });
  };

  // Nom complet (parcours en préfixe) — retour utilisateur 28/08/2026 : « on
  // a pas le nom complet du groupe dessus ». Le libellé seul ("TD EF")
  // existe en double identique entre plusieurs parcours FC (cf.
  // ReferenceView.tsx, même correctif) : sans le parcours, impossible de
  // savoir lequel des deux ce planning désigne.
  const nomComplet = parcours ? `${parcours} · ${payload.groupLabels[groupId] ?? groupId}` : (payload.groupLabels[groupId] ?? groupId);

  return (
    <section className="view">
      <div className="panel controls">
        {/* Sélecteur de groupe caché en lecture seule (le lien personnel
            désigne déjà UN seul groupe) — la barre de semaines reste, elle :
            même correctif que la vue Enseignant (retour utilisateur
            28/08/2026 : « on veut les semaines comme les profs »), sinon un
            groupe ouvrant son lien perso restait bloqué sur une seule
            semaine sans pouvoir parcourir le reste du semestre. */}
        {!readOnly && (
          <label>
            Groupe étudiant
            <select value={groupId} onChange={(e) => handleChangeGroup(e.target.value)}>
              {groupIds.map((gid) => (
                <option key={gid} value={gid}>
                  {payload.groupLabels[gid]}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="field weekfield">
          <WeekBar
            weekRows={payload.weekRows}
            countByWeekIndex={hoursByWeek}
            selected={displayWeek}
            onSelect={setDisplayWeek}
            unit="heures"
          />
        </div>
      </div>

      {/* Partage/export : utile côté planification (préparer l'envoi du
          lien), hors de propos une fois que c'est LE groupe qui regarde sa
          propre page via ce même lien — retiré en lecture seule pour ne
          garder que l'essentiel (barre des semaines + planning), même
          traitement que la vue Enseignant. Le lien agenda reste accessible
          en lecture seule, déplacé dans l'en-tête du planning ci-dessous. */}
      {!readOnly && (
        <ShareBar
          onCopyLink={() =>
            buildLink({ vue: "groupe", groupe: groupId, mode: "groupe", t: payload.groupTokens[groupId] ?? "" })
          }
          onCopySubscribeLink={() => subscribeUrl("groupe", groupId, payload.groupTokens[groupId] ?? "")}
          imageEdt={() => ({
            titre: nomComplet,
            sousTitre: payload.weekRows[displayWeek]?.label ?? `Semaine ${displayWeek + 1}`,
            rows: rowsThisWeek,
            payload,
            couleursParMatiere,
          })}
        />
      )}

      {narrow && <DayStrip selected={mobileDay} onSelect={setMobileDay} />}

      {/* Lecture seule : grille seule en pleine largeur, sans la liste de
          « toutes les séances du semestre » en dessous (retour utilisateur
          28/08/2026 : « enlève les séances en dessous du planning ») —
          parcourir les semaines dans la grille couvre déjà le même besoin. */}
      {readOnly ? (
        <div className="panel">
          <div className="section-header">
            <h3>
              {nomComplet} — {payload.weekRows[displayWeek]?.label ?? `Semaine ${displayWeek + 1}`}
            </h3>
            <div className="section-header-actions no-print">
              <CopyButton
                text={() => subscribeUrl("groupe", groupId, payload.groupTokens[groupId] ?? "")}
                idleLabel="Lien agenda"
                title="Lien à coller dans Google Agenda / Apple Calendrier / Outlook — se remet à jour tout seul."
              />
              {/* À CÔTÉ du lien d'abonnement, comme demandé — et surtout
                  visible ici : c'est la page que reçoit la personne, donc
                  celle depuis laquelle elle voudra partager. */}
              <BoutonsImageEdt
                options={() => ({
                  titre: nomComplet,
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
            <SessionGrid
              payload={payload}
              rows={rowsThisWeek}
              week={solverWeek}
              parcours={parcours}
              showPac={!parcours.includes("FC")}
              split={tpPair}
              onlyDay={narrow ? mobileDay : null}
            />
          )}
        </div>
      ) : (
        <>
          <div className="panel">
            <h3>
              {payload.groupLabels[groupId] ?? groupId} —{" "}
              {payload.weekRows[displayWeek]?.label ?? `Semaine ${displayWeek + 1}`}
            </h3>
            {solverWeek === null ? (
              <p className="muted">Semaine bloquée (vacances/fermeture).</p>
            ) : (
              <SessionGrid
                payload={payload}
                rows={rowsThisWeek}
                week={solverWeek}
                parcours={parcours}
                showPac={!parcours.includes("FC")}
                split={tpPair}
                onlyDay={narrow ? mobileDay : null}
              />
            )}
          </div>

          <div className="panel">
            <h3>Toutes les séances du semestre</h3>
            <SemesterAgenda payload={payload} items={allItems} />
          </div>
        </>
      )}
    </section>
  );
}
