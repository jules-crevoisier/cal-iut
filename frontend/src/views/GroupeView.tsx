/**
 * Vue TD / TP — et, en lecture seule, le lien public d'un groupe
 * (`#vue=groupe&groupe=…&mode=groupe&t=…`) que les étudiants ouvrent sur
 * leur téléphone.
 *
 * Même organisation que la Vue Enseignant (refonte du 29/09/2026) :
 * prochain cours, navigation de semaine avec aujourd'hui repéré, grille
 * pleine largeur, lecture jour par jour sur téléphone. Le panneau « Profil »
 * qui répétait le nom du groupe devient une ligne sous le sélecteur.
 */

import { useMemo } from "react";

import { BoutonsImageEdt } from "../components/BoutonsImageEdt";
import { FicheIntrouvable } from "../components/FicheIntrouvable";
import { MenuAgenda } from "../components/MenuAgenda";
import { NavSemaine } from "../components/NavSemaine";
import { PlanningSemaine } from "../components/PlanningSemaine";
import { ProchainCours } from "../components/ProchainCours";
import { SemesterAgenda } from "../components/SemesterAgenda";
import { ShareBar } from "../components/ShareBar";
import { useConsultation } from "../hooks/useConsultation";
import type { Route } from "../hooks/useHashRoute";
import { buildLink } from "../hooks/useHashRoute";
import type { AppPayload } from "../types/app";
import { sessionsWithDates, subscribeUrl } from "../utils/ics";
import { formatHeures, heuresDe, pluriel } from "../utils/planning";
import { usePreferences } from "../utils/preferences";

import "./fiches.css";

interface GroupeViewProps {
  payload: AppPayload;
  route: Route;
  setRoute: (patch: Partial<Route>) => void;
  readOnly?: boolean;
  onOpenSearch?: () => void;
}

export function GroupeView({ payload, route, setRoute, readOnly = false, onOpenSearch }: GroupeViewProps) {
  const groupIds = useMemo(
    () =>
      Object.keys(payload.groupLabels).sort((a, b) => {
        // Rangés par parcours puis libellé : « TD AB » existe dans plusieurs
        // parcours, trié au seul libellé la liste les mélangeait.
        const pa = payload.groupParcours[a] ?? "";
        const pb = payload.groupParcours[b] ?? "";
        return pa.localeCompare(pb, "fr") || (payload.groupLabels[a] ?? a).localeCompare(payload.groupLabels[b] ?? b, "fr");
      }),
    [payload.groupLabels, payload.groupParcours],
  );
  const groupId = route.groupe || payload.defaultGroup || groupIds[0] || "";
  const c = useConsultation(payload, route.sem);
  const couleursParMatiere = usePreferences().couleursParMatiere;

  // La cohorte : le groupe + son CM de promo + son TP jumelé — ce qu'un
  // étudiant de ce groupe suit réellement.
  const allItems = useMemo(() => {
    const cohort = new Set(payload.groupCohort[groupId] ?? [groupId]);
    return sessionsWithDates(payload, payload.rows.filter((r) => r.g.some((g) => cohort.has(g))));
  }, [payload, groupId]);

  if (!readOnly && route.groupe && !(route.groupe in payload.groupLabels)) {
    return <FicheIntrouvable libelle="Groupe" id={route.groupe} onOpenSearch={onOpenSearch} />;
  }

  const rowsThisWeek = c.solverWeek === null ? [] : allItems.filter((r) => r.w === c.solverWeek);
  // Heures, pas un compte de séances (retour utilisateur 28/08/2026).
  const hoursByWeek = new Map<number, number>();
  for (const it of allItems) hoursByWeek.set(it.w, (hoursByWeek.get(it.w) ?? 0) + heuresDe([it]));

  const tpPair = payload.groupTpPair[groupId];
  const parcours = payload.groupParcours[groupId] ?? "";
  // Nom complet, parcours en préfixe — retour utilisateur 28/08/2026 : « on
  // a pas le nom complet du groupe dessus ». « TD EF » existe à l'identique
  // dans plusieurs parcours FC.
  const nomComplet = parcours ? `${parcours} · ${payload.groupLabels[groupId] ?? groupId}` : (payload.groupLabels[groupId] ?? groupId);
  const token = payload.groupTokens[groupId] ?? "";
  const semaineLabel = payload.weekRows[c.displayWeek]?.label ?? `Semaine ${c.displayWeek + 1}`;
  const imageEdt = () => ({
    titre: nomComplet,
    sousTitre: semaineLabel,
    rows: rowsThisWeek,
    payload,
    couleursParMatiere,
  });
  const cohorte = payload.groupCohort[groupId] ?? [];

  return (
    <section className="view fiche">
      {!readOnly && (
        <div className="fiche-entete">
          <label className="fiche-choix">
            <span>Groupe étudiant</span>
            <select value={groupId} onChange={(e) => setRoute({ vue: "groupe", groupe: e.target.value })}>
              {groupIds.map((gid) => (
                <option key={gid} value={gid}>
                  {payload.groupParcours[gid] ? `${payload.groupParcours[gid]} · ` : ""}
                  {payload.groupLabels[gid]}
                </option>
              ))}
            </select>
          </label>
          <p className="fiche-identite">
            <span className="mono">{groupId}</span>
            <span>
              {[payload.groupKind[groupId]?.toUpperCase(), payload.groupIsFc[groupId] ? "FC" : parcours.includes("FI") ? "FI" : ""]
                .filter(Boolean)
                .join(" · ")}
            </span>
            {cohorte.length > 1 && (
              <span title="Groupes dont les séances apparaissent dans ce planning">
                suit : {cohorte.map((gid) => payload.groupLabels[gid] ?? gid).join(", ")}
              </span>
            )}
            {tpPair && (
              <span>
                TP : {payload.groupLabels[tpPair[0]] ?? tpPair[0]} / {payload.groupLabels[tpPair[1]] ?? tpPair[1]}
              </span>
            )}
            <span>
              {pluriel(allItems.length, "séance")} · {formatHeures(heuresDe(allItems))} au semestre
            </span>
          </p>
        </div>
      )}

      {!readOnly && (
        <ShareBar
          onCopyLink={() => buildLink({ vue: "groupe", groupe: groupId, mode: "groupe", t: token })}
          onCopySubscribeLink={() => subscribeUrl("groupe", groupId, token)}
          imageEdt={imageEdt}
        />
      )}

      <ProchainCours payload={payload} items={allItems} onVoir={(it) => c.allerA(it.w, it.d)} />

      <NavSemaine
        weekRows={payload.weekRows}
        selected={c.displayWeek}
        onSelect={c.setDisplayWeek}
        countByWeekIndex={hoursByWeek}
        onAujourdhui={c.narrow ? c.jourAujourdhui : undefined}
        resume={
          c.solverWeek !== null && (
            <strong>{formatHeures(hoursByWeek.get(c.solverWeek) ?? 0)} cette semaine</strong>
          )
        }
      >
        {readOnly && (
          <>
            <MenuAgenda url={subscribeUrl("groupe", groupId, token)} />
            <BoutonsImageEdt options={imageEdt} />
            <button type="button" className="btn btn--ghost btn--sm fiche-imprimer" onClick={() => window.print()}>
              Imprimer
            </button>
          </>
        )}
      </NavSemaine>

      <div className="fiche-corps">
        <div className="fiche-grille" id="planning">
          <PlanningSemaine
            payload={payload}
            rows={rowsThisWeek}
            displayIndex={c.displayWeek}
            onSelectWeek={c.setDisplayWeek}
            parcours={parcours}
            showPac={!parcours.includes("FC")}
            split={tpPair}
            narrow={c.narrow}
            jour={c.jour}
            onJour={c.setJour}
            titreImpression={nomComplet}
          />
        </div>
      </div>

      {/* Lecture seule : pas de liste du semestre sous la grille (retour
          utilisateur 28/08/2026 : « enlève les séances en dessous du
          planning »). */}
      {!readOnly && (
        <section className="panel fiche-semestre">
          <h3>Toutes les séances du semestre</h3>
          <SemesterAgenda
            payload={payload}
            items={allItems}
            semaineAffichee={c.solverWeek}
            onChoisirSemaine={(w) => c.allerA(w)}
          />
        </section>
      )}
    </section>
  );
}
