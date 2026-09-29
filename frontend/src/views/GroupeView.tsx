/**
 * Vue TD / TP — et, en lecture seule, le lien public d'un groupe
 * (`#vue=groupe&groupe=…&mode=groupe&t=…`) que les étudiants ouvrent sur
 * leur téléphone.
 *
 * Refonte v2 du 29/09/2026 (cf. docs/DESIGN.md « Gabarit de page ») : sans
 * groupe choisi, l'annuaire des groupes rangé par parcours avec leurs heures
 * de la semaine partagée ; la fiche suit le même gabarit que la Vue
 * Enseignant (barre d'outils à plat, bandeau d'identité, histogramme,
 * prochain cours, grille pleine largeur, agenda du semestre).
 */

import { useMemo } from "react";

import { BoutonsImageEdt } from "../components/BoutonsImageEdt";
import { FicheIdentite, FicheOutils } from "../components/FicheEntete";
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
import { heuresOccupees, libelleTypeGroupe } from "../utils/annuaires";
import { sessionsWithDates, subscribeUrl } from "../utils/ics";
import { decouperLibelleSemaine, formatHeures, pluriel } from "../utils/planning";
import { usePreferences } from "../utils/preferences";
import { compareParcoursForDisplay } from "../utils/years";
import { AnnuaireGroupes } from "./Annuaires";

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
        return compareParcoursForDisplay(pa, pb) || (payload.groupLabels[a] ?? a).localeCompare(payload.groupLabels[b] ?? b, "fr");
      }),
    [payload.groupLabels, payload.groupParcours],
  );
  // Application : sans groupe dans la route, l'annuaire. Lien public : le
  // groupe du lien (ou, à défaut, celui par défaut) — jamais d'annuaire.
  const groupId = route.groupe || (readOnly ? payload.defaultGroup || groupIds[0] || "" : "");
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

  if (!readOnly && !groupId) {
    return (
      <section className="view fiche fiche--annuaire">
        <AnnuaireGroupes
          payload={payload}
          displayWeek={c.displayWeek}
          onOuvrir={(gid) => setRoute({ vue: "groupe", groupe: gid })}
        />
      </section>
    );
  }

  const rowsThisWeek = c.solverWeek === null ? [] : allItems.filter((r) => r.w === c.solverWeek);
  // Heures, pas un compte de séances (retour utilisateur 28/08/2026) —
  // chaque créneau compté une fois : les deux TP jumelés d'un TD, en
  // parallèle, durent 1 h 30 et non 3 h (même mesure que l'annuaire).
  const parSemaine = new Map<number, typeof allItems>();
  for (const it of allItems) parSemaine.set(it.w, [...(parSemaine.get(it.w) ?? []), it]);
  const hoursByWeek = new Map<number, number>([...parSemaine].map(([w, l]) => [w, heuresOccupees(l)]));

  const tpPair = payload.groupTpPair[groupId];
  const parcours = payload.groupParcours[groupId] ?? "";
  // Nom complet, parcours en préfixe — retour utilisateur 28/08/2026 : « on
  // a pas le nom complet du groupe dessus ». « TD EF » existe à l'identique
  // dans plusieurs parcours FC.
  const nomComplet = parcours ? `${parcours} · ${payload.groupLabels[groupId] ?? groupId}` : (payload.groupLabels[groupId] ?? groupId);
  const token = payload.groupTokens[groupId] ?? "";
  const semaineLabel = payload.weekRows[c.displayWeek]?.label ?? `Semaine ${c.displayWeek + 1}`;
  const titreSemaine = decouperLibelleSemaine(semaineLabel).titre;
  const imageEdt = () => ({
    titre: nomComplet,
    sousTitre: semaineLabel,
    rows: rowsThisWeek,
    payload,
    couleursParMatiere,
  });
  const cohorte = payload.groupCohort[groupId] ?? [];

  const grille = (
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
  );

  // Lien public : pas de liste du semestre sous la grille (retour
  // utilisateur 28/08/2026 : « enlève les séances en dessous du planning »),
  // et sa propre navigation de semaine.
  if (readOnly) {
    return (
      <section className="view fiche">
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
          <MenuAgenda url={subscribeUrl("groupe", groupId, token)} />
          <BoutonsImageEdt options={imageEdt} />
          <button type="button" className="btn btn--ghost btn--sm fiche-imprimer" onClick={() => window.print()}>
            Imprimer
          </button>
        </NavSemaine>
        <div className="fiche-corps">
          <div className="fiche-grille" id="planning">
            {grille}
          </div>
        </div>
      </section>
    );
  }

  const genre = [libelleTypeGroupe(payload.groupKind[groupId] ?? ""), payload.groupIsFc[groupId] ? "FC" : parcours.includes("FI") ? "FI" : ""]
    .filter(Boolean)
    .join(" · ");

  return (
    <section className="view fiche">
      <FicheOutils
        libelle="Groupe étudiant"
        valeur={groupId}
        options={groupIds.map((gid) => ({
          value: gid,
          label: `${payload.groupParcours[gid] ? `${payload.groupParcours[gid]} · ` : ""}${payload.groupLabels[gid] ?? gid}`,
        }))}
        onChoisir={(gid) => setRoute({ vue: "groupe", groupe: gid })}
        onAnnuaire={() => setRoute({ vue: "groupe", groupe: "" })}
        actions={
          <ShareBar
            onCopyLink={() => buildLink({ vue: "groupe", groupe: groupId, mode: "groupe", t: token })}
            onCopySubscribeLink={() => subscribeUrl("groupe", groupId, token)}
            imageEdt={imageEdt}
          />
        }
      />

      <FicheIdentite
        titre={nomComplet}
        faits={[
          genre,
          cohorte.length > 1 && (
            <span title="Groupes dont les séances apparaissent dans ce planning">
              suit {cohorte.map((gid) => payload.groupLabels[gid] ?? gid).join(", ")}
            </span>
          ),
          tpPair && (
            <>
              TP {payload.groupLabels[tpPair[0]] ?? tpPair[0]} / {payload.groupLabels[tpPair[1]] ?? tpPair[1]}
            </>
          ),
          c.solverWeek !== null && (
            <>
              <strong>{formatHeures(hoursByWeek.get(c.solverWeek) ?? 0)}</strong> en {titreSemaine.toLowerCase()}
            </>
          ),
          <>
            <strong>{formatHeures(heuresOccupees(allItems))}</strong> au semestre · {pluriel(allItems.length, "séance")}
          </>,
        ]}
      />

      <NavSemaine
        weekRows={payload.weekRows}
        selected={c.displayWeek}
        onSelect={c.setDisplayWeek}
        countByWeekIndex={hoursByWeek}
        onAujourdhui={c.narrow ? c.jourAujourdhui : undefined}
      />

      <ProchainCours payload={payload} items={allItems} onVoir={(it) => c.allerA(it.w, it.d)} />

      <div className="fiche-corps">
        <div className="fiche-grille" id="planning">
          {grille}
        </div>
      </div>

      <section className="panel fiche-semestre">
        <h3>Toutes les séances du semestre</h3>
        <SemesterAgenda
          payload={payload}
          items={allItems}
          semaineAffichee={c.solverWeek}
          onChoisirSemaine={(w) => c.allerA(w)}
        />
      </section>
    </section>
  );
}
