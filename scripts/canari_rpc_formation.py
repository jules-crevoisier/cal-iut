"""Canari RPC via `ctweb.io.Rpc` (le vrai client), URCA_FORMATION seulement."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from cal_iut.celcat import navigateur as nav  # noqa: E402
from cal_iut.celcat import reseau  # noqa: E402

GROUP_ID = 47925
MARQUE = "cal-iut-canari"

_JS_CANARI = """async ({groupId, marque, ecrire, restaurer, creer}) => {
    const invoquer = (methode, params) => new Promise((resolve) => {
    const rpc = new ctweb.io.Rpc();
    let got = null;
    const seen = [];
    const orig = rpc.fireEvent.bind(rpc);
    rpc.fireEvent = function() {
      seen.push(String(arguments[0]));
      return orig.apply(this, arguments);
    };
    const fin = (payload) => {
      if (got) return;
      got = payload;
      payload.seen = seen;
      try { rpc.dispose(); } catch (e) {}
      resolve(payload);
    };
    rpc.addListener('result', (e) => fin({ type: 'result', data: e.getData() }));
    rpc.addListener('error', (e) => {
      let data = null;
      try { data = e.getData(); } catch (err) {}
      fin({ type: 'error', data, error: String(e) });
    });
    rpc.addListener('failed', (e) => fin({ type: 'failed', error: String(e) }));
    try { rpc.invoke(methode, params); }
    catch (err) { fin({ type: 'throw', error: String(err) }); }
    setTimeout(() => {
      if (!got) {
        try { rpc.dispose(); } catch (e) {}
        resolve({ type: 'timeout', seen });
      }
    }, 15000);
  });
  const load = await invoquer('udlTimetables.load', [{ GroupIDs: [groupId] }]);
  const events = Array.isArray(load.data) ? load.data : [];
  const cours = events.filter((e) => e && String(e.weeks || '').split('Y').length - 1 === 1
    && e.protected !== 'Y' && e.modules && e.modules.length);
  const out = { loadType: load.type, n: events.length, nCours: cours.length };
  if (!ecrire && !creer) {
    const ex = cours[0] || events[0];
    out.exemple = ex && { event_id: ex.event_id, notes: ex.notes, start_time: ex.start_time, day_of_week: ex.day_of_week };
    return out;
  }
  if (!cours.length) { out.erreur = 'aucun cours 1-semaine'; return out; }
  const cible = cours[0];
  const ancien = cible.notes;
  const INTERDITS = new Set([
    'accessRights', 'deptName', 'evCatColour', 'evCatName', 'evCatWeighting',
    'eventColour', 'userName', 'user_staff_name_change',
    'user_staff_unique_name_change', 'spanName',
    'booking_id', 'date_change', 'user_id_change', 'first_clash_id',
    'force_unprotect', 'registerRequired', 'fixtureReq', 'layoutReq',
    'staffCatReq', 'charge', 'layoutCapacity', 'staffCategoryName',
  ]);
  const TYPES = {
    modules: 'Module', rooms: 'Room', staff: 'Staff', groups: 'Group',
    students: 'Student', teams: 'Team', equipment: 'Equipment',
  };
  const DATES = new Set(['start_time', 'end_time']);
  const versDate = (v) => {
    if (v instanceof Date) return v;
    if (typeof v === 'number') {
      const h = Math.floor(v / 60); const m = v % 60;
      const d = new Date(2026, 0, 1, h, m, 0, 0);
      return d;
    }
    if (typeof v === 'string' && v.includes('T')) return new Date(v);
    if (typeof v === 'string' && v.includes(':')) {
      const p = v.split(':');
      return new Date(2026, 0, 1, Number(p[0]), Number(p[1]), 0, 0);
    }
    return v;
  };
  const cloner = (v, cle) => {
    if (v instanceof Date) return v;
    if (DATES.has(cle) && v != null && v !== '') return versDate(v);
    if (Array.isArray(v)) return v.map((x) => cloner(x));
    if (!v || typeof v !== 'object') return v;
    const o = {};
    for (const [k, val] of Object.entries(v)) {
      if (INTERDITS.has(k)) continue;
      o[k] = cloner(val, k);
    }
    return o;
  };
  const plain = cloner(cible);
  plain._type_ = cible._type_ || 'Event';
  for (const [cle, typ] of Object.entries(TYPES)) {
    if (!Array.isArray(plain[cle])) continue;
    plain[cle] = plain[cle].map((x) => {
      if (!x || typeof x !== 'object') return x;
      x._type_ = x._type_ || typ;
      if (creer) delete x.event_id;
      return x;
    });
  }
  if (creer) {
    delete plain.event_id;
    delete plain.original_id;
  }
  plain.notes = marque;
  out.type_origine = cible._type_ || null;
  out.event_id = cible.event_id || plain.event_id;
  out.ancien = ancien;
  out.types_heures = {
    start: plain.start_time instanceof Date ? 'Date' : typeof plain.start_time,
    end: plain.end_time instanceof Date ? 'Date' : typeof plain.end_time,
  };
  const apercu = (sav) => ({
    type: sav.type,
    seen: sav.seen,
    error: sav.error || null,
    data: sav.data && typeof sav.data === 'object' ? sav.data : (sav.data === undefined ? null : String(sav.data).slice(0, 240)),
  });
  const retirer = (obj, nom) => {
    if (Array.isArray(obj)) { obj.forEach((x) => retirer(x, nom)); return; }
    if (!obj || typeof obj !== 'object') return;
    delete obj[nom];
    Object.values(obj).forEach((v) => retirer(v, nom));
  };
  const PROTEGES = new Set(
    creer
      ? ['_type_', 'notes', 'weeks', 'start_time', 'end_time', 'day_of_week']
      : ['_type_', 'event_id', 'notes', 'weeks', 'start_time', 'end_time', 'day_of_week']
  );
  out.retraits = [];
  out.conversions = [];
  let sav = { type: 'none' };
  for (let i = 0; i < 25; i++) {
    sav = await invoquer('udlTimetables.save', [[plain]]);
    out.save = apercu(sav);
    if (sav.type === 'result') break;
    const msg = String((sav.data && sav.data.message) || '');
    const m = msg.match(/Champ '([^']+)' non trouvé/)
      || msg.match(/You cannot modify the field '([^']+)'/)
      || msg.match(/Valeur non valide pour le champ '([^']+)'/);
    if (!m) break;
    const champ = m[1];
    if (DATES.has(champ) && plain[champ] instanceof Date) {
      const d = plain[champ];
      plain[champ] = d.getHours() * 60 + d.getMinutes();
      out.conversions.push(champ + ':Date->min');
      continue;
    }
    if (PROTEGES.has(champ)) { out.bloque = champ; break; }
    out.retraits.push(champ);
    retirer(plain, champ);
  }
  out.n_cles = Object.keys(plain).length;
  out.cles = Object.keys(plain).sort();
  const revu = await invoquer('udlTimetables.load', [{ GroupIDs: [groupId] }]);
  const liste = Array.isArray(revu.data) ? revu.data : [];
  if (creer) {
    const cree = liste.find((e) => e && e.notes === marque && e.event_id !== cible.event_id);
    out.nouveau_id = cree && cree.event_id;
    out.n_semaines = cree ? String(cree.weeks || '').split('Y').length - 1 : 0;
    out.ok = Boolean(out.nouveau_id) && out.n_semaines === 1;
    return out;
  }
  const trouve = liste.find((e) => e && e.event_id === cible.event_id);
  out.notes = trouve && trouve.notes;
  out.ok = out.notes === marque;
  if (out.ok && restaurer) {
    plain.notes = ancien;
    const sav2 = await invoquer('udlTimetables.save', [[plain]]);
    out.restore = apercu(sav2);
    const revu2 = await invoquer('udlTimetables.load', [{ GroupIDs: [groupId] }]);
    const liste2 = Array.isArray(revu2.data) ? revu2.data : [];
    const t2 = liste2.find((e) => e && e.event_id === cible.event_id);
    out.notes_apres_restore = t2 && t2.notes;
    out.restaure = (t2 && t2.notes) === ancien;
    out.ok = out.ok && out.restaure;
  }
  return out;
}"""


def principal() -> int:
    parseur = argparse.ArgumentParser()
    parseur.add_argument("--vpn", action="store_true")
    parseur.add_argument("--ecrire", action="store_true")
    parseur.add_argument("--creer", action="store_true")
    parseur.add_argument("--production", action="store_true")
    parseur.add_argument("--restaurer", action="store_true")
    args = parseur.parse_args()
    base = nav.BASE_PRODUCTION if args.production else nav.BASE_ENTRAINEMENT
    group_id = 1661972 if args.production else GROUP_ID
    marque = "cal-iut-create" if args.creer else (
        "cal-iut-canari-prod" if args.production else MARQUE
    )
    restaurer = bool(args.restaurer or (args.production and not args.creer))
    try:
        from dotenv import load_dotenv
        load_dotenv(RACINE / ".env")
    except ImportError:
        pass
    diag = reseau.exiger_acces(os.environ["CELCAT_URL"], monter_le_vpn=args.vpn)
    if not diag:
        print(diag.detail, file=sys.stderr)
        return 3
    from playwright.sync_api import sync_playwright
    preuve: dict = {}
    with sync_playwright() as p:
        navg = p.chromium.launch(headless=True)
        page = navg.new_page(viewport={"width": 1920, "height": 1080})
        try:
            print(f"Connexion {base}…")
            nav.connexion(page, base=base, role=nav.ROLE_ECRITURE)
            print("canari JS load/save via ctweb.io.Rpc…")
            brut = page.evaluate(_JS_CANARI, {
                "groupId": group_id,
                "marque": marque,
                "ecrire": bool(args.ecrire or args.creer),
                "restaurer": restaurer and not args.creer,
                "creer": bool(args.creer),
            })
            preuve["canari"] = brut
            print(json.dumps(brut, ensure_ascii=False, default=str)[:1500])
            if args.creer and isinstance(brut, dict) and brut.get("ok"):
                print("canari CREATE OK : event_id", brut.get("nouveau_id"), "1 semaine")
                return 0
            if args.ecrire and isinstance(brut, dict) and brut.get("ok"):
                if restaurer:
                    print("canari OK : notes écrites puis restaurées sur", base)
                else:
                    print("canari OK : notes écrites par udlTimetables.save")
                return 0
            if args.ecrire:
                return 8
        finally:
            (RACINE / "data" / "releves" / "celcat-rpc-canari.json").write_text(
                json.dumps(preuve, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
            try:
                nav.deconnexion(page)
            except Exception:  # noqa: BLE001
                pass
            navg.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
