/**
 * Référence : salles, cours, calendrier institutionnel, liens de partage et
 * notifications.
 *
 * Refonte du 29/09/2026 : vrais onglets (le dernier ouvert est mémorisé),
 * tableaux filtrables et triables par colonne, nombres alignés à droite,
 * identifiants techniques traduits (« tp_standard » -> « TP standard »),
 * calendrier daté avec ce qui est passé / en cours / à venir, annuaire des
 * liens filtrable avec ses actions groupées dans une seule barre.
 */

import { useMemo, useState } from "react";

import { sendTeacherMails } from "../api/client";
import { ChampRecherche } from "../components/ChampRecherche";
import { CopyButton } from "../components/CopyButton";
import { NotificationsPanel } from "../components/NotificationsPanel";
import { OpenLinkButton } from "../components/OpenLinkButton";
import { SendTeacherMailsModal } from "../components/SendTeacherMailsModal";
import { TriColonne, useTri } from "../components/TriColonne";
import type { Route } from "../hooks/useHashRoute";
import { buildLink } from "../hooks/useHashRoute";
import type { AppPayload, CourseCatalogEntry, InstitutionalEvent, RoomCatalogEntry } from "../types/app";
import { confirmAsync } from "../utils/confirmDialog";
import { downloadDirectoryCsv, type CsvRow } from "../utils/csv";
import { sessionsWithDates, subscribeUrl } from "../utils/ics";
import { ecrireLocal, lireLocal } from "../utils/stockageLocal";
import { Onglets } from "../components/Onglets";
import "../styles/outils.css";
import "./ReferenceView.css";

type SubTab = "salles" | "cours" | "calendrier" | "liens" | "notifications";

const ONGLETS: { id: SubTab; label: string }[] = [
  { id: "salles", label: "Salles" },
  { id: "cours", label: "Cours" },
  { id: "calendrier", label: "Calendrier" },
  { id: "liens", label: "Liens & partage" },
  { id: "notifications", label: "Notifications" },
];

const CLE_ONGLET = "cal-iut:reference:onglet:v1";

function estOnglet(v: unknown): v is SubTab {
  return ONGLETS.some((o) => o.id === v);
}

function normaliser(t: string): string {
  return t
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
}

const MOTS: Record<string, string> = {
  tp: "TP",
  td: "TD",
  cm: "CM",
  av: "AV",
  vr: "VR",
  pc: "PC",
  "3d": "3D",
  mac: "Mac",
  apple: "Apple",
  videoprojecteur: "vidéoprojecteur",
  televiseur: "téléviseur",
  camera: "caméra",
  regie: "régie",
  reseaux: "réseaux",
  evaluation: "évaluation",
  evier: "évier",
  ilots: "îlots",
  combined: "salles réunies",
  amphi: "amphithéâtre",
};

/** « tp_standard » -> « TP standard », « cloison_amovible_h008 » ->
 * « cloison amovible H.008 » : les identifiants de configuration, lisibles. */
export function humaniser(id: string): string {
  const mots = id
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((m) => {
      const bas = m.toLowerCase();
      if (/^[a-z]\d{3}$/.test(bas)) return `${bas[0].toUpperCase()}.${bas.slice(1)}`;
      return MOTS[bas] ?? bas;
    });
  const texte = mots.join(" ");
  return texte.charAt(0).toUpperCase() + texte.slice(1);
}

interface ReferenceViewProps {
  payload: AppPayload;
  setRoute: (patch: Partial<Route>) => void;
}

export function ReferenceView({ payload, setRoute }: ReferenceViewProps) {
  const [sub, setSubState] = useState<SubTab>(() => lireLocal(CLE_ONGLET, "salles", estOnglet));
  const setSub = (s: SubTab) => {
    setSubState(s);
    ecrireLocal(CLE_ONGLET, s);
  };

  const compteurs: Partial<Record<SubTab, number>> = {
    salles: payload.rooms.length,
    cours: new Set(payload.courses.map((c) => c.code)).size,
    calendrier: payload.institutionalCalendar.length,
  };

  return (
    <section className="view ref-view">
      <Onglets
        onglets={ONGLETS.map((o) => ({ id: o.id, label: o.label, nb: compteurs[o.id] }))}
        actif={sub}
        onChoisir={setSub}
        label="Rubriques du référentiel"
        prefixeId="ref-onglet"
        controle="ref-panneau"
      />

      <div id="ref-panneau" role="tabpanel" aria-labelledby={`ref-onglet-${sub}`} className="ref-panneau">
        {sub === "salles" && <RoomsTable payload={payload} setRoute={setRoute} />}
        {sub === "cours" && <CoursesTable payload={payload} setRoute={setRoute} />}
        {sub === "calendrier" && <CalendarTimeline payload={payload} />}
        {sub === "liens" && <LinksDirectory payload={payload} />}
        {/* Sous-onglet À PART, pas au pied de l'annuaire des liens : sous un
            long tableau, le panneau était introuvable. */}
        {sub === "notifications" && <NotificationsPanel />}
      </div>
    </section>
  );
}

// ── Salles ──────────────────────────────────────────────────────────────

type CleSalle = "label" | "capacity" | "type" | "nSessions";
const VALEURS_SALLE: Record<CleSalle, (r: RoomCatalogEntry) => string | number> = {
  label: (r) => r.label,
  capacity: (r) => r.capacity,
  type: (r) => humaniser(r.type),
  nSessions: (r) => r.nSessions,
};

function RoomsTable({ payload, setRoute }: { payload: AppPayload; setRoute: (patch: Partial<Route>) => void }) {
  const [texte, setTexte] = useState("");
  const [type, setType] = useState("");
  const types = useMemo(() => [...new Set(payload.rooms.map((r) => r.type))].sort(), [payload.rooms]);
  const filtrees = useMemo(() => {
    const q = normaliser(texte.trim());
    return payload.rooms.filter(
      (r) =>
        (!type || r.type === type) &&
        (!q || normaliser(`${r.label} ${r.id} ${humaniser(r.type)} ${r.equipment.map(humaniser).join(" ")}`).includes(q)),
    );
  }, [payload.rooms, texte, type]);
  const { triees, tri, trierPar } = useTri<RoomCatalogEntry, CleSalle>(filtrees, VALEURS_SALLE, { cle: "label", sens: 1 });
  const horsAuto = payload.rooms.filter((r) => !r.placementAuto).length;

  return (
    <>
      <div className="page-outils ref-barre">
        <ChampRecherche
          className="ref-recherche"
          placeholder="Filtrer : nom, équipement…"
          libelle="Filtrer les salles"
          valeur={texte}
          onChange={(v) => setTexte(v)}
        />
        <select aria-label="Type de salle" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">Tous les types</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {humaniser(t)}
            </option>
          ))}
        </select>
        <span className="ref-resume">
          {filtrees.length === payload.rooms.length ? `${payload.rooms.length} salles` : `${filtrees.length} sur ${payload.rooms.length} salles`}
          {horsAuto > 0 && ` · ${horsAuto} hors placement automatique`}
        </span>
      </div>
      <div className="panel carte-tableau carte-tableau--haute ref-tableau">
        <table className="ref">
          <thead>
            <tr>
              <TriColonne cle="label" tri={tri} onTrier={trierPar}>
                Salle
              </TriColonne>
              <TriColonne cle="capacity" tri={tri} onTrier={trierPar} num>
                Places
              </TriColonne>
              <TriColonne cle="type" tri={tri} onTrier={trierPar} className="ref-optionnel">
                Type
              </TriColonne>
              <th className="ref-secondaire">Équipement</th>
              <TriColonne cle="nSessions" tri={tri} onTrier={trierPar} num>
                Séances
              </TriColonne>
            </tr>
          </thead>
          <tbody>
            {triees.map((r) => (
              <tr key={r.id}>
                <td>
                  <button
                    type="button"
                    className="ref-lien"
                    onClick={() => setRoute({ vue: "salle", salle: r.id })}
                    title="Ouvrir la Vue Salle"
                  >
                    {r.label}
                  </button>
                  {/* Marqueur TEXTE, pas seulement couleur (retour utilisateur
                      22/09/2026) : une salle hors placement automatique reste
                      choisissable à la main, cf. `Room.placement_auto`. */}
                  {!r.placementAuto && <span className="pill ref-marque">hors auto</span>}
                </td>
                <td className="num">{r.capacity}</td>
                <td className="ref-optionnel">{humaniser(r.type)}</td>
                <td className="ref-doux ref-secondaire">{r.equipment.map(humaniser).join(", ") || "—"}</td>
                <td className="num">{r.nSessions}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {triees.length === 0 && <p className="ref-vide">Aucune salle ne correspond.</p>}
      </div>
    </>
  );
}

// ── Cours ───────────────────────────────────────────────────────────────

type CleCours = "code" | "name" | "semestre" | "parcours" | "nCM" | "nTD" | "nTP" | "nEval" | "nPlaced";
const VALEURS_COURS: Record<CleCours, (c: CourseCatalogEntry) => string | number> = {
  code: (c) => c.code,
  name: (c) => c.name,
  semestre: (c) => c.semestre,
  parcours: (c) => c.parcours,
  nCM: (c) => c.nCM,
  nTD: (c) => c.nTD,
  nTP: (c) => c.nTP,
  nEval: (c) => c.nEval,
  nPlaced: (c) => c.nPlaced,
};

function CoursesTable({ payload, setRoute }: { payload: AppPayload; setRoute: (patch: Partial<Route>) => void }) {
  const [texte, setTexte] = useState("");
  const [parcours, setParcours] = useState("");
  const [semestre, setSemestre] = useState("");
  const listeParcours = useMemo(
    () => [...new Set(payload.courses.map((c) => c.parcours).filter(Boolean))].sort((a, b) => a.localeCompare(b, "fr")),
    [payload.courses],
  );
  const listeSemestres = useMemo(
    () => [...new Set(payload.courses.map((c) => c.semestre).filter(Boolean))].sort(),
    [payload.courses],
  );
  const filtres = useMemo(() => {
    const q = normaliser(texte.trim());
    return payload.courses.filter((c) => {
      if (parcours && c.parcours !== parcours) return false;
      if (semestre && c.semestre !== semestre) return false;
      if (!q) return true;
      const profs = c.teachers.map((t) => `${t} ${payload.teacherLabels[t] ?? ""}`).join(" ");
      return normaliser(`${c.code} ${c.name} ${profs}`).includes(q);
    });
  }, [payload.courses, payload.teacherLabels, texte, parcours, semestre]);
  const { triees, tri, trierPar } = useTri<CourseCatalogEntry, CleCours>(filtres, VALEURS_COURS, { cle: "code", sens: 1 });
  const col = (cle: CleCours, libelle: string, num = false, className?: string) => (
    <TriColonne cle={cle} tri={tri} onTrier={trierPar} num={num} className={className}>
      {libelle}
    </TriColonne>
  );

  return (
    <>
      <div className="page-outils ref-barre">
        <ChampRecherche
          className="ref-recherche"
          placeholder="Filtrer : code, nom, enseignant…"
          libelle="Filtrer les cours"
          valeur={texte}
          onChange={(v) => setTexte(v)}
        />
        <select aria-label="Parcours" value={parcours} onChange={(e) => setParcours(e.target.value)}>
          <option value="">Tous les parcours</option>
          {listeParcours.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select aria-label="Semestre" value={semestre} onChange={(e) => setSemestre(e.target.value)}>
          <option value="">Tous les semestres</option>
          {listeSemestres.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <span className="ref-resume">
          {filtres.length === payload.courses.length ? `${filtres.length} lignes` : `${filtres.length} sur ${payload.courses.length} lignes`}
        </span>
      </div>
      <div className="panel carte-tableau carte-tableau--haute ref-tableau">
        <table className="ref">
          <thead>
            <tr>
              {col("code", "Code")}
              {col("name", "Nom", false, "ref-optionnel")}
              {col("semestre", "Sem.", false, "ref-optionnel")}
              {col("parcours", "Parcours")}
              {col("nCM", "CM", true, "ref-optionnel")}
              {col("nTD", "TD", true, "ref-optionnel")}
              {col("nTP", "TP", true, "ref-optionnel")}
              {col("nEval", "Éval", true, "ref-optionnel")}
              {col("nPlaced", "Placées", true)}
              <th className="ref-secondaire">Enseignants</th>
            </tr>
          </thead>
          <tbody>
            {triees.map((c) => (
              <tr key={`${c.code}-${c.parcours}`}>
                <td>
                  <button
                    type="button"
                    className="ref-lien mono"
                    onClick={() => setRoute({ vue: "cours", cours: c.code })}
                    title="Ouvrir la Vue Cours"
                  >
                    {c.code}
                  </button>
                </td>
                <td className="ref-optionnel">{c.name}</td>
                <td className="ref-optionnel">{c.semestre}</td>
                <td className="ref-doux ref-parcours">{c.parcours}</td>
                <td className="num ref-optionnel">{c.nCM || <span className="ref-zero">0</span>}</td>
                <td className="num ref-optionnel">{c.nTD || <span className="ref-zero">0</span>}</td>
                <td className="num ref-optionnel">{c.nTP || <span className="ref-zero">0</span>}</td>
                <td className="num ref-optionnel">{c.nEval || <span className="ref-zero">0</span>}</td>
                <td className="num">{c.nPlaced}</td>
                <td className="ref-doux ref-secondaire">{c.teachers.map((t) => payload.teacherLabels[t] ?? t).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {triees.length === 0 && <p className="ref-vide">Aucun cours ne correspond.</p>}
      </div>
    </>
  );
}

// ── Calendrier ──────────────────────────────────────────────────────────

const LIBELLE_TYPE: Record<InstitutionalEvent["kind"], string> = {
  vacances: "Vacances",
  ferie: "Jour férié",
  rentree: "Rentrée",
  special: "Événement",
};

const FMT_DATE = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const FMT_DATE_SANS_AN = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short" });

function dateLocale(iso: string): Date {
  return new Date(`${iso}T00:00:00`);
}

/** « lun. 26 oct. → ven. 30 oct. 2026 » (année une seule fois si identique). */
export function libellePeriode(debut: string, fin: string): string {
  const d = dateLocale(debut);
  const f = dateLocale(fin);
  if (Number.isNaN(d.getTime()) || Number.isNaN(f.getTime())) return debut === fin ? debut : `${debut} → ${fin}`;
  if (debut === fin) return FMT_DATE.format(d);
  const memeAnnee = d.getFullYear() === f.getFullYear();
  return `${(memeAnnee ? FMT_DATE_SANS_AN : FMT_DATE).format(d)} → ${FMT_DATE.format(f)}`;
}

/** État d'une période par rapport à aujourd'hui, en mots. */
export function etatPeriode(debut: string, fin: string, aujourdhui: Date = new Date()): { etat: "passe" | "encours" | "avenir"; texte: string } {
  const jour = new Date(aujourdhui.getFullYear(), aujourdhui.getMonth(), aujourdhui.getDate()).getTime();
  const d = dateLocale(debut).getTime();
  const f = dateLocale(fin).getTime();
  if (f < jour) return { etat: "passe", texte: "passé" };
  if (d <= jour) return { etat: "encours", texte: "en cours" };
  const jours = Math.round((d - jour) / 86_400_000);
  if (jours === 1) return { etat: "avenir", texte: "demain" };
  if (jours < 14) return { etat: "avenir", texte: `dans ${jours} jours` };
  if (jours < 62) return { etat: "avenir", texte: `dans ${Math.round(jours / 7)} semaines` };
  return { etat: "avenir", texte: `dans ${Math.round(jours / 30)} mois` };
}

function CalendarTimeline({ payload }: { payload: AppPayload }) {
  const evenements = useMemo(
    () => [...payload.institutionalCalendar].sort((a, b) => a.start.localeCompare(b.start)),
    [payload.institutionalCalendar],
  );
  if (evenements.length === 0) {
    return <p className="empty-state">Aucune période déclarée dans le calendrier institutionnel.</p>;
  }
  return (
    <div className="panel carte-tableau ref-tableau">
      <table className="ref ref-calendrier">
        <thead>
          <tr>
            <th>Période</th>
            <th>Type</th>
            <th>Dates</th>
            <th className="num">Jours</th>
            <th>Quand</th>
          </tr>
        </thead>
        <tbody>
          {evenements.map((ev) => {
            const { etat, texte } = etatPeriode(ev.start, ev.end);
            const jours = Math.round((dateLocale(ev.end).getTime() - dateLocale(ev.start).getTime()) / 86_400_000) + 1;
            return (
              <tr key={`${ev.label}-${ev.start}`} className={`ref-cal-${etat}`}>
                <td>
                  <strong>{ev.label}</strong>
                </td>
                <td>
                  <span className={`ref-type ref-type--${ev.kind}`}>{LIBELLE_TYPE[ev.kind] ?? ev.kind}</span>
                </td>
                <td>{libellePeriode(ev.start, ev.end)}</td>
                <td className="num">{Number.isFinite(jours) ? jours : ""}</td>
                <td className={`ref-quand ref-quand--${etat}`}>{texte}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Liens & partage ─────────────────────────────────────────────────────

interface LigneAnnuaire {
  code: string;
  kind: "prof" | "groupe";
  token: string;
  label: string;
  items: ReturnType<typeof sessionsWithDates>;
  link: string;
  mail: string;
}

function LinksDirectory({ payload }: { payload: AppPayload }) {
  const [showMailModal, setShowMailModal] = useState(false);
  const [texte, setTexte] = useState("");
  const teacherCodes = useMemo(
    () =>
      Object.keys(payload.teacherLabels).sort((a, b) =>
        (payload.teacherLabels[a] ?? a).localeCompare(payload.teacherLabels[b] ?? b, "fr"),
      ),
    [payload.teacherLabels],
  );
  // Groupes "promo" (CM seul) écartés (retour utilisateur 28/08/2026 : « clean
  // up les groupes étudiant... les promo, les groupe à 0h... on peut
  // enlever ») : un TD/TP a déjà les CM de sa promo dans son propre lien. Les
  // groupes à 0 séance sont écartés plus bas, une fois les séances comptées.
  const groupIds = useMemo(
    () =>
      Object.keys(payload.groupLabels)
        .filter((gid) => payload.groupKind[gid] !== "promo")
        .sort((a, b) => {
          const pa = payload.groupParcours[a] ?? "";
          const pb = payload.groupParcours[b] ?? "";
          return pa !== pb
            ? pa.localeCompare(pb, "fr")
            : (payload.groupLabels[a] ?? a).localeCompare(payload.groupLabels[b] ?? b, "fr");
        }),
    [payload.groupLabels, payload.groupKind, payload.groupParcours],
  );

  const teacherItems: LigneAnnuaire[] = useMemo(
    () =>
      teacherCodes.map((code) => ({
        code,
        kind: "prof" as const,
        token: payload.teacherTokens[code] ?? "",
        label: payload.teacherLabels[code] ?? code,
        items: sessionsWithDates(payload, payload.rows.filter((r) => r.te.includes(code))),
        link: buildLink({ vue: "prof", prof: code, mode: "prof", t: payload.teacherTokens[code] ?? "" }),
        mail: payload.teacherEmails[code] || "",
      })),
    [payload, teacherCodes],
  );
  const groupItems: LigneAnnuaire[] = useMemo(
    () =>
      groupIds
        .map((gid) => {
          const cohort = new Set(payload.groupCohort[gid] ?? [gid]);
          const parcours = payload.groupParcours[gid];
          return {
            code: gid,
            kind: "groupe" as const,
            token: payload.groupTokens[gid] ?? "",
            // « TD GH » existe en double (BUT2-CREACOM-FC ET BUT3-CREACOM-FC) :
            // le parcours en préfixe désambiguïse.
            label: parcours ? `${parcours} · ${payload.groupLabels[gid] ?? gid}` : (payload.groupLabels[gid] ?? gid),
            items: sessionsWithDates(payload, payload.rows.filter((r) => r.g.some((g) => cohort.has(g)))),
            link: buildLink({ vue: "groupe", groupe: gid, mode: "groupe", t: payload.groupTokens[gid] ?? "" }),
            mail: "",
          };
        })
        .filter((g) => g.items.length > 0),
    [payload, groupIds],
  );

  const q = normaliser(texte.trim());
  const garde = (r: LigneAnnuaire) => !q || normaliser(`${r.label} ${r.code} ${r.mail}`).includes(q);
  const profsVisibles = teacherItems.filter(garde);
  const groupesVisibles = groupItems.filter(garde);
  const sansAdresse = teacherItems.filter((t) => !t.mail).length;

  const allRows = (): CsvRow[] =>
    [
      ...teacherItems.map((t) => ({ type: "Enseignant", ...t })),
      ...groupItems.map((g) => ({ type: "Groupe", ...g })),
    ].map((r) => ({
      type: r.type,
      label: r.label,
      code: r.code,
      mail: r.mail,
      count: r.items.length,
      hours: r.items.reduce((n, it) => n + (it.dur || 1), 0) * 1.5,
      link: r.link,
    }));

  const lienPromo = buildLink({ vue: "promo", mode: "promo", t: "promo" });
  // Lien public « Salles libres » (retour utilisateur 25/09/2026, Jules) —
  // présence de `t` suffit (`api/auth.py::verify_personal_link_param`),
  // lecture seule, sans compte. « Salles libres » n'est plus un onglet de la
  // nav : ce lien est son accès public.
  const lienSalles = buildLink({ vue: "salles-libres", mode: "salles", t: "salles" });

  return (
    <div className="ref-liens">
      {/* Liens publics, un seul chacun (retour utilisateur 31/08/2026 : « un
          lien en plus ouvert à tout le monde [...] accès à la vue promo ») :
          lecture seule, aucun glisser-déposer, aucune création de séance. */}
      <section className="panel ref-publics" aria-labelledby="ref-publics-titre">
        <h3 id="ref-publics-titre">Liens publics</h3>
        <p className="ref-aide">Un seul lien pour tout le monde, en lecture seule, sans mot de passe.</p>
        <div className="ref-lien-public">
          <div>
            <strong>Vue Promo — accès public</strong>
            <span className="ref-doux">Toutes les promotions, jour par jour.</span>
          </div>
          <span className="lien-boutons">
            <CopyButton text={lienPromo} idleLabel="Copier le lien" />
            <OpenLinkButton href={lienPromo} />
          </span>
        </div>
        <div className="ref-lien-public">
          <div>
            <strong>Occupation des salles — accès public</strong>
            <span className="ref-doux">Le tableau salles × créneaux.</span>
          </div>
          <span className="lien-boutons">
            <CopyButton text={lienSalles} idleLabel="Copier le lien" />
            <OpenLinkButton href={lienSalles} />
          </span>
        </div>
      </section>

      <div className="page-outils ref-barre">
        <ChampRecherche
          className="ref-recherche"
          placeholder="Filtrer : nom, code, groupe…"
          libelle="Filtrer l'annuaire"
          valeur={texte}
          onChange={(v) => setTexte(v)}
        />
        <span className="page-outils-actions">
          <CopyButton
            text={() => [...teacherItems, ...groupItems].map((r) => `${r.label}\t${r.link}`).join("\n")}
            idleLabel="Copier tous les liens"
            className="btn btn--sm"
          />
          <button type="button" className="btn btn--sm" onClick={() => downloadDirectoryCsv(allRows())}>
            Annuaire (.csv)
          </button>
          <button type="button" className="btn btn--primary btn--sm" onClick={() => setShowMailModal(true)}>
            Envoyer les liens par mail…
          </button>
        </span>
      </div>
      <p className="ref-aide">
        Chaque lien personnel ouvre directement SON planning, en lecture seule. « Lien agenda » copie l'adresse à
        coller dans Google Agenda, Apple Calendrier ou Outlook (« ajouter un agenda par URL ») : l'agenda se met à
        jour tout seul.
      </p>
      {showMailModal && <SendTeacherMailsModal onClose={() => setShowMailModal(false)} />}

      <section className="panel carte-tableau carte-tableau--haute ref-tableau" aria-labelledby="ref-annuaire-profs">
        <div className="carte-tete">
          <h3 id="ref-annuaire-profs">
            Enseignants <span className="carte-tete-nb">{profsVisibles.length}</span>
          </h3>
          {sansAdresse > 0 && <span className="carte-tete-note">{sansAdresse} sans adresse mail</span>}
        </div>
        <table className="ref">
          <thead>
            <tr>
              <th>Enseignant</th>
              <th className="num ref-optionnel">Séances</th>
              <th className="num">Heures</th>
              <th>Lien personnel</th>
              <th>Agenda</th>
              <th>Mail</th>
            </tr>
          </thead>
          <tbody>
            {profsVisibles.map((t) => (
              <DirectoryRow key={t.code} row={t} showMail />
            ))}
          </tbody>
        </table>
        {profsVisibles.length === 0 && <p className="ref-vide">Aucun enseignant ne correspond.</p>}
      </section>

      <section className="panel carte-tableau carte-tableau--haute ref-tableau" aria-labelledby="ref-annuaire-groupes">
        <div className="carte-tete">
          <h3 id="ref-annuaire-groupes">
            Groupes étudiants <span className="carte-tete-nb">{groupesVisibles.length}</span>
          </h3>
        </div>
        <table className="ref">
          <thead>
            <tr>
              <th>Groupe</th>
              <th className="num ref-optionnel">Séances</th>
              <th className="num">Heures</th>
              <th>Lien personnel</th>
              <th>Agenda</th>
            </tr>
          </thead>
          <tbody>
            {groupesVisibles.map((g) => (
              <DirectoryRow key={g.code} row={g} />
            ))}
          </tbody>
        </table>
        {groupesVisibles.length === 0 && <p className="ref-vide">Aucun groupe ne correspond.</p>}
      </section>
    </div>
  );
}

function DirectoryRow({ row, showMail = false }: { row: LigneAnnuaire; showMail?: boolean }) {
  const hours = (row.items.reduce((n, it) => n + (it.dur || 1), 0) * 1.5).toLocaleString("fr-FR");
  // Envoi ciblé à CETTE seule personne (retour utilisateur 28/08/2026 : « un
  // bouton qui envoie le mail à la personne avec son lien ») — même endpoint
  // que l'envoi groupé, avec un seul code.
  const [etatEnvoi, setEtatEnvoi] = useState<"repos" | "envoi" | "ok" | "echec">("repos");
  const [erreurEnvoi, setErreurEnvoi] = useState<string | null>(null);

  const envoyer = async () => {
    // Vraie popup de confirmation AVANT l'envoi (retour utilisateur
    // 28/08/2026), interne (`confirmAsync`), jamais `window.confirm`.
    const confirme = await confirmAsync(`Envoyer l'emploi du temps à ${row.label} (${row.mail}) ?`, {
      title: "Confirmer l'envoi",
      confirmLabel: "Envoyer",
      cancelLabel: "Annuler",
    });
    if (!confirme) return;

    setEtatEnvoi("envoi");
    setErreurEnvoi(null);
    try {
      const { results } = await sendTeacherMails([row.code]);
      const resultat = results[0];
      if (resultat?.ok) {
        setEtatEnvoi("ok");
      } else {
        setEtatEnvoi("echec");
        setErreurEnvoi(resultat?.error ?? "Échec de l'envoi.");
      }
    } catch (e) {
      setEtatEnvoi("echec");
      setErreurEnvoi(e instanceof Error ? e.message : "Échec de l'envoi.");
    }
  };

  return (
    <tr>
      <td>
        <strong className="ref-nom">{row.label}</strong> <span className="mono ref-code">{row.code}</span>
      </td>
      <td className="num ref-optionnel">{row.items.length}</td>
      <td className="num ref-heures">{hours} h</td>
      <td>
        <span className="lien-boutons">
          <CopyButton text={row.link} idleLabel="Copier" />
          <OpenLinkButton href={row.link} />
        </span>
      </td>
      <td>
        <CopyButton
          text={() => subscribeUrl(row.kind, row.code, row.token)}
          idleLabel="Lien agenda"
          title="À coller dans Google Agenda / Apple Calendrier / Outlook (« ajouter un agenda par URL ») — se met à jour tout seul."
        />
      </td>
      {showMail && (
        <td>
          {row.mail ? (
            <button
              type="button"
              className={`btn btn--ghost btn--sm${etatEnvoi === "ok" ? " is-copied" : ""}${etatEnvoi === "echec" ? " is-copy-failed" : ""}${etatEnvoi === "envoi" ? " is-busy" : ""}`}
              onClick={envoyer}
              disabled={etatEnvoi === "envoi"}
              title={row.mail}
              aria-live="polite"
            >
              {etatEnvoi === "envoi" ? "Envoi…" : etatEnvoi === "ok" ? "Envoyé" : etatEnvoi === "echec" ? "Échec" : "Envoyer"}
            </button>
          ) : (
            <span className="ref-sans-mail" title="Adresse à compléter dans data/config/teacher_contacts.yaml">
              pas d'adresse
            </span>
          )}
          {erreurEnvoi && <div className="alerte small">{erreurEnvoi}</div>}
        </td>
      )}
    </tr>
  );
}
