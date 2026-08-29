/**
 * Panneau « À traiter » — portage de `buildTodoList` depuis
 * `export/templates/timetable.html`. Agrège ce qui existait déjà mais
 * dispersé : violations de contrainte enseignant, règles globales en échec,
 * et un signal calculé côté client — les journées « gruyère » (cohorte
 * présente en début et fin de journée avec ≥2 créneaux vides entre les deux).
 */

import type { AppPayload } from "../types/app";
import type { Route } from "../hooks/useHashRoute";
import { DAY_LABELS, SLOT_TIMES } from "./slots";

export interface TodoItem {
  sev: "bad" | "warn";
  title: string;
  sub: string;
  route: Partial<Route>;
}

export function buildTodoList(payload: AppPayload): TodoItem[] {
  const items: TodoItem[] = [];

  // En TÊTE, avant les questions de confort : une séance non placée est une
  // heure d'enseignement qui n'aura pas lieu. Rien d'autre dans cette liste
  // n'a ce poids. Chaque ligne renvoie vers l'onglet « À placer », le seul
  // endroit d'où on peut la rattraper.
  for (const s of payload.seancesNonPlacees ?? []) {
    items.push({
      sev: "bad",
      title: `${s.code} — séance non placée`,
      sub: `${s.type} · ${s.groupes.join(", ")} · ${s.profs.join(", ")}`,
      route: { vue: "aplacer" },
    });
  }

  // Juste après les non-placées, et avant les questions de confort : une
  // séance sans salle est un cours que personne ne sait où suivre. Le cas
  // n'est PAS accidentel — un CM dont aucune grande salle n'est libre reste
  // volontairement sans salle plutôt que d'atterrir dans une salle de 15
  // places (retour utilisateur 29/08/2026 : « il faut laisser la salle vide,
  // elle sera rentrée par la suite »). Encore faut-il que « par la suite »
  // soit visible quelque part : sans cette liste, une salle vide ne se
  // remarque qu'en tombant dessus dans la grille.
  for (const r of payload.rows) {
    if (r.r) continue;
    const groupes = r.g.map((g) => payload.groupLabels[g] ?? g).join(", ");
    items.push({
      sev: "bad",
      title: `${r.c} — aucune salle`,
      sub: `${r.t} · ${groupes} · ${payload.weekLabels[r.w] ?? `Semaine ${r.w + 1}`} · ${DAY_LABELS[r.d]} ${
        SLOT_TIMES[r.s]?.label ?? ""
      }`,
      // Vue Promo : le seul écran d'où la salle se change directement.
      route: { vue: "promo", sem: r.w, jour: r.d },
    });
  }

  for (const t of payload.teachers) {
    for (const v of t.violations) {
      const when = v.date
        ? v.date
        : `${payload.weekLabels[v.week ?? 0] ?? `Semaine ${(v.week ?? 0) + 1}`} · ${
            DAY_LABELS[v.day ?? 0]
          } ${SLOT_TIMES[v.slot ?? 0]?.label ?? ""}`;
      // Compromis MOU accepté (encadrement SAE, `--no-sae-supervisor-hard`)
      // : une préférence pas respectée, pas une règle cassée — sévérité et
      // libellé distincts d'une vraie indisponibilité déclarée non
      // respectée (retour utilisateur 11/08/2026, cf. docs/DATA.md §59).
      const isSaeCompromise = v.reason === "sae_supervision";
      items.push({
        sev: isSaeCompromise ? "warn" : "bad",
        title: isSaeCompromise
          ? `${t.name} — encadrement SAE ce jour-là (compromis accepté)`
          : `${t.name} — contrainte non respectée`,
        sub: `${v.course_code} · ${when}`,
        route: { vue: "prof", prof: t.code, sem: v.week ?? null },
      });
    }
  }

  const byGroupDay = new Map<string, number[]>();
  for (const r of payload.rows) {
    for (const g of r.g) {
      const key = `${g}|${r.w}|${r.d}`;
      if (!byGroupDay.has(key)) byGroupDay.set(key, []);
      byGroupDay.get(key)!.push(r.s);
    }
  }
  for (const [key, slots] of byGroupDay) {
    const [gid, wRaw, dRaw] = key.split("|");
    const w = Number(wRaw);
    const d = Number(dRaw);
    if (payload.groupKind[gid] === "promo") continue;
    const used = new Set(slots);
    const lo = Math.min(...slots);
    const hi = Math.max(...slots);
    let gap = 0;
    for (let s = lo; s <= hi; s++) if (!used.has(s)) gap++;
    if (gap >= 2) {
      items.push({
        sev: "warn",
        title: `${payload.groupLabels[gid] || gid} — journée trouée`,
        sub: `${payload.weekLabels[w] ?? `Semaine ${w + 1}`} · ${DAY_LABELS[d]} · ${gap} créneaux vides entre deux cours`,
        route: { vue: "groupe", groupe: gid, sem: w },
      });
    }
  }

  for (const c of payload.ruleChecks) {
    if (c.status === "fail") {
      items.push({ sev: "bad", title: c.label, sub: c.detail, route: { vue: "contraintes" } });
    }
  }

  return items;
}
