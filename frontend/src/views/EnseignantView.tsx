/**
 * Vue Enseignant — et, en lecture seule, le lien personnel envoyé à chaque
 * enseignant (`#vue=prof&prof=KBR&mode=prof&t=…`), très souvent ouvert sur
 * téléphone.
 *
 * Refonte du 29/09/2026. La page répond d'abord à « quand est-ce que j'ai
 * cours ? » : prochain cours en une ligne, semaine en cours avec aujourd'hui
 * repéré, flèches semaine précédente / suivante (← → au clavier, T pour
 * revenir à aujourd'hui), lecture jour par jour sur téléphone. Côté
 * planification, la contrainte déclarée et ses violations restent, rangées
 * dans une colonne à droite de la grille au lieu d'un empilement de
 * panneaux (profil, callout, contrainte, agenda) qui répétait le nom.
 */

import { useMemo, useState } from "react";

import { BoutonsImageEdt } from "../components/BoutonsImageEdt";
import { FicheIntrouvable } from "../components/FicheIntrouvable";
import { MenuAgenda } from "../components/MenuAgenda";
import { NavSemaine } from "../components/NavSemaine";
import { PlanningSemaine } from "../components/PlanningSemaine";
import { ProchainCours } from "../components/ProchainCours";
import { SemesterAgenda } from "../components/SemesterAgenda";
import { ShareBar } from "../components/ShareBar";
import { TeacherLinksList } from "../components/TeacherLinksList";
import { useConsultation } from "../hooks/useConsultation";
import type { Route } from "../hooks/useHashRoute";
import { buildLink } from "../hooks/useHashRoute";
import type { AppPayload, TeacherInfo } from "../types/app";
import { sessionsWithDates, subscribeUrl } from "../utils/ics";
import { mailtoForTeacher } from "../utils/mailto";
import { formatHeures, heuresDe, jourCourt, pluriel } from "../utils/planning";
import { usePreferences } from "../utils/preferences";
import { DAY_LABELS, SLOT_TIMES } from "../utils/slots";

import "./fiches.css";

interface EnseignantViewProps {
  payload: AppPayload;
  route: Route;
  setRoute: (patch: Partial<Route>) => void;
  readOnly?: boolean;
  onOpenSearch?: () => void;
  /** Adresse du compte connecté : ouvre la vue sur SA fiche quand elle
   *  correspond à un enseignant. */
  emailCompte?: string;
}

/** Code de l'enseignant dont l'adresse est celle du compte connecté. */
export function enseignantDuCompte(payload: AppPayload, email: string | undefined): string {
  const cherche = (email ?? "").trim().toLowerCase();
  if (!cherche) return "";
  const trouve = Object.entries(payload.teacherEmails).find(([, e]) => e.trim().toLowerCase() === cherche);
  return trouve && trouve[0] in payload.teacherLabels ? trouve[0] : "";
}

export function EnseignantView({
  payload,
  route,
  setRoute,
  readOnly = false,
  onOpenSearch,
  emailCompte,
}: EnseignantViewProps) {
  const teacherCodes = useMemo(
    () =>
      Object.keys(payload.teacherLabels).sort((a, b) =>
        (payload.teacherLabels[a] ?? a).localeCompare(payload.teacherLabels[b] ?? b, "fr"),
      ),
    [payload.teacherLabels],
  );
  // Onglet ouvert sans enseignant : la fiche du compte connecté s'il en est
  // un, sinon une invitation à choisir. Avant, le premier par ordre
  // alphabétique, souvent quelqu'un sans aucune séance (« 0 séance »).
  const code = route.prof || enseignantDuCompte(payload, emailCompte);
  const c = useConsultation(payload, route.sem);
  // « Tous les liens » — retour utilisateur 27/08/2026 : « ajoute moi une
  // vue simple avec tous les lien de tous les prof ». Planification seule.
  const [showAllLinks, setShowAllLinks] = useState(false);
  const couleursParMatiere = usePreferences().couleursParMatiere;

  const allItems = useMemo(
    () => sessionsWithDates(payload, payload.rows.filter((r) => r.te.includes(code))),
    [payload, code],
  );

  if (!readOnly && route.prof && !(route.prof in payload.teacherLabels)) {
    return <FicheIntrouvable libelle="Enseignant" id={route.prof} onOpenSearch={onOpenSearch} />;
  }

  const choix = (
    <label className="fiche-choix">
      <span>Enseignant</span>
      <select value={code} onChange={(e) => setRoute({ vue: "prof", prof: e.target.value })}>
        {!code && <option value="">Choisir un enseignant…</option>}
        {teacherCodes.map((tc) => (
          <option key={tc} value={tc}>
            {payload.teacherLabels[tc]}
            {payload.teachers.find((t) => t.code === tc)?.hasConstraint ? " •" : ""}
          </option>
        ))}
      </select>
    </label>
  );

  if (!readOnly && !code && !showAllLinks) {
    return (
      <section className="view fiche">
        <div className="fiche-entete">
          {choix}
          <button type="button" className="btn btn--ghost btn--sm fiche-bascule" onClick={() => setShowAllLinks(true)}>
            Tous les liens
          </button>
        </div>
        <p className="empty-state">Choisissez un enseignant, ou cherchez-le avec Ctrl+K.</p>
      </section>
    );
  }

  const rowsThisWeek = c.solverWeek === null ? [] : allItems.filter((r) => r.w === c.solverWeek);
  // Parcours où cet enseignant a RÉELLEMENT cours cette semaine : filtre les
  // évènements de planning (rentrées…) de la grille. Sans eux, chacun voyait
  // les rentrées de tous les parcours (Romain Delon, 09/09/2026).
  const parcoursDeLaSemaine = Array.from(
    new Set(
      rowsThisWeek.flatMap((r) =>
        (r.g ?? []).map((g) => payload.groupParcours[g]).filter((p): p is string => Boolean(p)),
      ),
    ),
  );
  // Heures, pas un compte de séances — retour utilisateur 28/08/2026 (idée
  // de Jordan) : « le nombre d'heure total de la semaine ».
  const hoursByWeek = new Map<number, number>();
  for (const it of allItems) hoursByWeek.set(it.w, (hoursByWeek.get(it.w) ?? 0) + heuresDe([it]));

  const nom = payload.teacherLabels[code] ?? code;
  const email = payload.teacherEmails[code] ?? "";
  const info = payload.teachers.find((t) => t.code === code);
  const manquantes = (payload.seancesNonPlacees ?? []).filter((s) => s.profs.includes(code));
  const absences = payload.exceptions.filter(
    (e) => e.kind === "teacher_absence" && e.active && e.teacher_code === code,
  );
  const token = payload.teacherTokens[code] ?? "";
  // `t` rend le lien public (cf. api/auth.py) — retour utilisateur
  // 28/08/2026 : « on s'en fiche on veut qu'il soit public ».
  const personalLink = buildLink({ vue: "prof", prof: code, mode: "prof", t: token });
  const semaineLabel = payload.weekRows[c.displayWeek]?.label ?? `Semaine ${c.displayWeek + 1}`;
  const imageEdt = () => ({
    titre: nom,
    sousTitre: semaineLabel,
    rows: rowsThisWeek,
    payload,
    couleursParMatiere,
  });

  if (showAllLinks) {
    return (
      <section className="view fiche">
        <div className="fiche-entete">
          <button type="button" className="btn btn--sm" onClick={() => setShowAllLinks(false)}>
            ← Revenir au planning
          </button>
        </div>
        <TeacherLinksList payload={payload} />
      </section>
    );
  }

  return (
    <section className="view fiche">
      {!readOnly && (
        <div className="fiche-entete">
          {choix}
          <p className="fiche-identite">
            <span className="mono">{code}</span>
            {email ? (
              <a href={`mailto:${email}`}>{email}</a>
            ) : (
              <span className="fiche-manque" title="À compléter dans data/config/teacher_contacts.yaml">
                adresse mail inconnue
              </span>
            )}
            <span>
              {pluriel(allItems.length, "séance")} · {formatHeures(heuresDe(allItems))} au semestre
            </span>
            {manquantes.length > 0 && (
              <span className="fiche-manque">{pluriel(manquantes.length, "séance non placée", "séances non placées")}</span>
            )}
          </p>
          <button type="button" className="btn btn--ghost btn--sm fiche-bascule" onClick={() => setShowAllLinks(true)}>
            Tous les liens
          </button>
        </div>
      )}

      {!readOnly && (
        <ShareBar
          onCopyLink={() => personalLink}
          onCopySubscribeLink={() => subscribeUrl("prof", code, token)}
          imageEdt={imageEdt}
          extra={
            <a
              className="btn btn--ghost btn--sm"
              href={mailtoForTeacher(payload, code, allItems, personalLink)}
              title={email || "Adresse inconnue : le brouillon s'ouvrira sans destinataire."}
            >
              Écrire un mail
            </a>
          }
        />
      )}

      <ProchainCours payload={payload} items={allItems} showPromo onVoir={(it) => c.allerA(it.w, it.d)} />

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
            <MenuAgenda url={subscribeUrl("prof", code, token)} />
            <BoutonsImageEdt options={imageEdt} />
            <button type="button" className="btn btn--ghost btn--sm fiche-imprimer" onClick={() => window.print()}>
              Imprimer
            </button>
          </>
        )}
      </NavSemaine>

      <div className={`fiche-corps${!readOnly && info ? " avec-cote" : ""}`}>
        <div className="fiche-grille" id="planning">
          <PlanningSemaine
            payload={payload}
            rows={rowsThisWeek}
            displayIndex={c.displayWeek}
            onSelectWeek={c.setDisplayWeek}
            parcours={parcoursDeLaSemaine}
            showPromo
            narrow={c.narrow}
            jour={c.jour}
            onJour={c.setJour}
            titreImpression={nom}
            exclureProf={code}
          />
        </div>
        {!readOnly && info && (
          <aside className="fiche-cote" aria-label="Contrainte et matières">
            <ContrainteEnseignant info={info} absences={absences.map((e) => ({ id: e.id, date: e.exception_date, motif: e.reason }))} />
            <SesMatieres
              items={allItems}
              manquantes={manquantes.map((s) => `${s.code} ${s.type} · ${s.groupes.join(", ")}`)}
              onCours={(cc) => setRoute({ vue: "cours", cours: cc })}
            />
          </aside>
        )}
      </div>

      {/* Lecture seule : ni agenda du semestre ni contrainte (retour
          utilisateur 27/08/2026 : « juste l'essentiel c'est à dire la barre
          des semaine et le planing qui fit bien l'écran »). */}
      {!readOnly && (
        <section className="panel fiche-semestre">
          <h3>Toutes ses interventions du semestre</h3>
          <SemesterAgenda
            payload={payload}
            items={allItems}
            showPromo
            semaineAffichee={c.solverWeek}
            onChoisirSemaine={(w) => c.allerA(w)}
          />
        </section>
      )}
    </section>
  );
}

function dateLisible(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : jourCourt(d);
}

/** La contrainte déclarée de l'enseignant et ce que le planning en fait. */
function ContrainteEnseignant({
  info,
  absences,
}: {
  info: TeacherInfo;
  absences: { id: number; date: string; motif: string | null }[];
}) {
  // Compromis MOU (encadrement SAE ce jour-là) distingué d'une vraie
  // indisponibilité déclarée non respectée — sinon un référent SAE ressort à
  // tort « en échec » (retour utilisateur 11/08/2026, cf. docs/DATA.md §59).
  const sae = info.violations.filter((v) => v.reason === "sae_supervision");
  const vraies = info.violations.filter((v) => v.reason !== "sae_supervision");
  const etat = !info.hasConstraint ? "neutre" : vraies.length ? "bad" : sae.length ? "warn" : "good";
  const libelleViolation = (v: TeacherInfo["violations"][number]) =>
    v.date
      ? dateLisible(v.date)
      : `sem. ${(v.week ?? 0) + 1} ${DAY_LABELS[v.day ?? 0]?.toLowerCase() ?? ""} ${SLOT_TIMES[v.slot ?? 0]?.label ?? ""}`;
  const aTexte = info.rawIndisponibilites || info.rawDisponibilites || info.rawContraintes;

  return (
    <section className="panel cote-bloc">
      <h3>Contrainte déclarée</h3>
      <p className={`contrainte-etat contrainte-etat--${etat}`}>
        {!info.hasConstraint ? (
          "Aucune contrainte déclarée dans le fichier CONTRAINTES ENSEIGNANTS."
        ) : info.violations.length === 0 ? (
          <>
            <span aria-hidden="true">✓ </span>Respectée sur {pluriel(info.nPlaced, "séance placée", "séances placées")}.
          </>
        ) : (
          <>
            <span aria-hidden="true">{vraies.length ? "! " : "i "}</span>
            {vraies.length > 0 && pluriel(vraies.length, "violation", "violations")}
            {vraies.length > 0 && sae.length > 0 && " et "}
            {sae.length > 0 && pluriel(sae.length, "compromis accepté (SAE)", "compromis acceptés (SAE)")}
            {" "}sur {pluriel(info.nPlaced, "séance", "séances")}.
          </>
        )}
      </p>

      {info.rawIndisponibilites && (
        <>
          <h4>Indisponibilités</h4>
          <p className="raw">{info.rawIndisponibilites}</p>
        </>
      )}
      {info.rawDisponibilites && (
        <>
          <h4>Disponibilités</h4>
          <p className="raw">{info.rawDisponibilites}</p>
        </>
      )}
      {info.rawContraintes && (
        <>
          <h4>Contraintes / progression</h4>
          <p className="raw">{info.rawContraintes}</p>
        </>
      )}
      {!aTexte && info.hasConstraint && <p className="muted">Pas de texte libre.</p>}

      {info.forbiddenSlots.length > 0 && (
        <>
          <h4>Créneaux interdits</h4>
          <p>
            {info.forbiddenSlots
              .map(([d, s]) => `${DAY_LABELS[d] ?? d} ${SLOT_TIMES[s]?.label ?? s}`)
              .join(" · ")}
          </p>
        </>
      )}
      {info.forbiddenDates.length > 0 && (
        <details className="cote-details">
          <summary>{pluriel(info.forbiddenDates.length, "date interdite", "dates interdites")}</summary>
          <p>{info.forbiddenDates.map(dateLisible).join(" · ")}</p>
        </details>
      )}
      {absences.length > 0 && (
        <>
          <h4>Absences</h4>
          <ul className="cote-liste">
            {absences.map((a) => (
              <li key={a.id}>
                {dateLisible(a.date)}
                {a.motif ? ` — ${a.motif}` : ""}
              </li>
            ))}
          </ul>
        </>
      )}
      {info.violations.length > 0 && (
        <details className="cote-details" open={vraies.length > 0 && info.violations.length <= 8}>
          <summary>Détail des {pluriel(info.violations.length, "écart", "écarts")}</summary>
          <ul className="cote-liste">
            {[...vraies, ...sae].map((v, i) => (
              <li
                key={i}
                className={v.reason === "sae_supervision" ? "ecart ecart--sae" : "ecart"}
                title={
                  v.reason === "sae_supervision"
                    ? "Compromis accepté : encadrement SAE ce jour-là (préférence, pas un interdit)"
                    : "Indisponibilité déclarée non respectée"
                }
              >
                <span className="mono">{v.course_code}</span> — {libelleViolation(v)}
                {v.reason === "sae_supervision" ? " (SAE)" : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

/** Ses matières, avec les heures du semestre — un clic ouvre la Vue Cours. */
function SesMatieres({
  items,
  manquantes,
  onCours,
}: {
  items: ReturnType<typeof sessionsWithDates>;
  manquantes: string[];
  onCours: (code: string) => void;
}) {
  const parCode = new Map<string, { nom: string; types: Set<string>; heures: number }>();
  for (const it of items) {
    const cur = parCode.get(it.c) ?? { nom: it.n, types: new Set<string>(), heures: 0 };
    cur.types.add(it.t);
    cur.heures += heuresDe([it]);
    parCode.set(it.c, cur);
  }
  if (!parCode.size && !manquantes.length) return null;
  return (
    <section className="panel cote-bloc">
      <h3>Ses matières</h3>
      {parCode.size > 0 && (
        <table className="cote-table">
          <tbody>
            {[...parCode.entries()]
              .sort((a, b) => b[1].heures - a[1].heures)
              .map(([cc, v]) => (
                <tr key={cc}>
                  <td>
                    <button type="button" className="linklike mono" onClick={() => onCours(cc)}>
                      {cc}
                    </button>
                    <span className="cote-sous">
                      {v.nom} · {[...v.types].join(", ")}
                    </span>
                  </td>
                  <td className="num">{formatHeures(v.heures)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      )}
      {manquantes.length > 0 && (
        <>
          <h4 className="fiche-manque">Non placées</h4>
          <ul className="cote-liste">
            {manquantes.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
