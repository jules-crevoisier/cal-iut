"""JSON-RPC Celcat **depuis la page** — jamais un fetch Python à part.

La session Timetabler Live est liée à la connexion du navigateur, pas à un
cookie. Un `page.request.post` ou un `urllib` reçoit `ESessionTimeout`. Un
`fetch` injecté par `page.evaluate` après `login.login` réutilise cette
connexion. Playwright n'est pas importé ici : les tests injectent une
fausse page.
"""

from __future__ import annotations

from cal_iut.celcat.navigateur import lire_reponse

URL_SERVICE = "/script/CTWebService.dll"
EN_TETE_DATE = "X-Use-Object-Date"

_JS_FETCH = """async ({methode, params, rpc_id}) => {
  // Client officiel Celcat (session liée à ctweb.io.Rpc, pas à un fetch).
  if (typeof ctweb !== 'undefined' && ctweb.io && ctweb.io.Rpc) {
    return await new Promise((resolve) => {
      const rpc = new ctweb.io.Rpc();
      const fin = (payload) => {
        try { rpc.dispose(); } catch (e) {}
        resolve(payload);
      };
      rpc.addListener('result', (e) => {
        fin({
          status: 200,
          texte: JSON.stringify({ jsonrpc: '2.0', id: rpc_id, result: e.getData() }),
        });
      });
      rpc.addListener('failed', (e) => {
        fin({
          status: 200,
          texte: JSON.stringify({
            jsonrpc: '2.0', id: rpc_id,
            error: { code: 'failed', message: String(e) },
          }),
        });
      });
      rpc.addListener('error', (e) => {
        let data = null;
        try { data = e.getData(); } catch (err) {}
        fin({
          status: 200,
          texte: JSON.stringify({
            jsonrpc: '2.0', id: rpc_id,
            error: data || { code: 'error', message: String(e) },
          }),
        });
      });
      const DATES = new Set(['start_time', 'end_time']);
      const hydrater = (v, cle) => {
        if (v instanceof Date) return v;
        if (DATES.has(cle) && typeof v === 'string' && v) {
          if (v.includes('T') || (v.includes('-') && v.length > 5)) return new Date(v);
          if (v.includes(':')) {
            const p = v.split(':');
            return new Date(1899, 11, 31, Number(p[0]), Number(p[1]), 0, 0);
          }
        }
        if (Array.isArray(v)) return v.map((x) => hydrater(x));
        if (!v || typeof v !== 'object') return v;
        const o = {};
        for (const [k, val] of Object.entries(v)) o[k] = hydrater(val, k);
        return o;
      };
      try { rpc.invoke(methode, hydrater(params)); }
      catch (err) {
        fin({
          status: 200,
          texte: JSON.stringify({
            jsonrpc: '2.0', id: rpc_id,
            error: { code: 'throw', message: String(err) },
          }),
        });
      }
      setTimeout(() => fin({
        status: 200,
        texte: JSON.stringify({
          jsonrpc: '2.0', id: rpc_id,
          error: { code: 'ESessionTimeout', message: 'timeout ctweb.io.Rpc' },
        }),
      }), 25000);
    });
  }
  return await new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open('POST', '/script/CTWebService.dll', true);
    x.setRequestHeader('Content-Type', 'application/json; charset=UTF-8');
    x.setRequestHeader('X-Use-Object-Date', 'yes');
    x.onload = () => resolve({ status: x.status, texte: x.responseText });
    x.onerror = () => reject(new Error('XMLHttpRequest RPC'));
    x.send(JSON.stringify({
      jsonrpc: '2.0',
      method: methode,
      params: params,
      id: rpc_id,
    }));
  });
}"""


class SessionCelcatTimeout(RuntimeError):
    """La connexion JSON-RPC n'est plus celle du login."""


class MethodeEcritureAbsente(ValueError):
    """Pas de méthode d'enregistrement relevée — on n'en invente pas une."""


def parser_reponse(texte: str) -> dict:
    lu = lire_reponse(texte)
    if not isinstance(lu, dict):
        raise TypeError(f"réponse RPC inattendue : {type(lu).__name__}")
    return lu


def _code_erreur(erreur: object) -> str:
    if isinstance(erreur, dict):
        return str(erreur.get("code") or erreur.get("message") or "")
    return str(erreur)


def _lever_si_erreur(erreur: object) -> None:
    code = _code_erreur(erreur)
    if "ESessionTimeout" in code:
        raise SessionCelcatTimeout(code)
    if erreur:
        raise RuntimeError(f"RPC Celcat : {erreur}")


def appeler(page, methode: str, params: list[object], *, rpc_id: int | None = None) -> object:
    identifiant = int(rpc_id if rpc_id is not None else __import__("time").time() * 1000)
    brut = page.evaluate(_JS_FETCH, {
        "methode": methode,
        "params": params,
        "rpc_id": identifiant,
    })
    if isinstance(brut, dict) and "error" in brut and "texte" not in brut:
        _lever_si_erreur(brut["error"])
        return None
    if isinstance(brut, dict) and "texte" in brut:
        corps = parser_reponse(str(brut["texte"]))
    elif isinstance(brut, dict):
        corps = brut
    else:
        raise TypeError("evaluate RPC n'a pas renvoyé un objet")
    if corps.get("error"):
        _lever_si_erreur(corps["error"])
    return corps.get("result")


def charger_edt(page, *, group_ids: list[int]) -> list[dict]:
    resultat = appeler(page, "udlTimetables.load", [{"GroupIDs": group_ids}])
    if resultat is None:
        return []
    if not isinstance(resultat, list):
        raise TypeError("udlTimetables.load n'a pas renvoyé une liste")
    return [e for e in resultat if isinstance(e, dict)]


def charger_ressources(page, type_id: int, filtre: dict) -> list[dict]:
    resultat = appeler(page, "udlResources.load", [type_id, filtre])
    if resultat is None:
        return []
    if not isinstance(resultat, list):
        raise TypeError("udlResources.load n'a pas renvoyé une liste")
    return [e for e in resultat if isinstance(e, dict)]


def id_ressource(enreg: dict, *cles: str) -> int | None:
    for cle in cles:
        val = enreg.get(cle)
        if val is not None:
            return int(val)
    return None


# Champs renvoyés par load, refusés par save (FORMATION, 2026-09-01).
CHAMPS_CLIENT = frozenset({
    "accessRights",
    "booking_id",
    "charge",
    "date_change",
    "deptName",
    "evCatColour",
    "evCatName",
    "evCatWeighting",
    "eventColour",
    "first_clash_id",
    "fixtureReq",
    "force_unprotect",
    "layoutCapacity",
    "layoutReq",
    "registerRequired",
    "spanName",
    "staffCategoryName",
    "staffCatReq",
    "userName",
    "user_id_change",
    "user_staff_name_change",
    "user_staff_unique_name_change",
})

_TYPES_RESSOURCE = {
    "modules": "Module",
    "rooms": "Room",
    "staff": "Staff",
    "groups": "Group",
    "students": "Student",
    "teams": "Team",
    "equipment": "Equipment",
}


def preparer_evenement(charge: dict) -> dict:
    """Clone d'écriture : `_type_`, sans champs client, ressources typées."""

    def _copier(valeur: object, cle: str | None = None) -> object:
        if isinstance(valeur, list):
            return [_copier(item, None) for item in valeur]
        if not isinstance(valeur, dict):
            return valeur
        copie: dict[str, object] = {}
        for nom, val in valeur.items():
            if nom in CHAMPS_CLIENT:
                continue
            copie[nom] = _copier(val, nom)
        if cle in _TYPES_RESSOURCE and "_type_" not in copie:
            copie["_type_"] = _TYPES_RESSOURCE[cle]
        return copie

    evenement = _copier(charge)
    if not isinstance(evenement, dict):
        raise TypeError("événement Celcat attendu")
    evenement["_type_"] = "Event"
    creer = evenement.get("event_id") in (0, -1, None)
    for cle, typ in _TYPES_RESSOURCE.items():
        brut = evenement.get(cle)
        if not isinstance(brut, list):
            continue
        nettoyes = []
        for item in brut:
            if not isinstance(item, dict):
                nettoyes.append(item)
                continue
            copie = {**item, "_type_": item.get("_type_") or typ}
            if creer:
                copie.pop("event_id", None)
            nettoyes.append(copie)
        evenement[cle] = nettoyes
    if creer:
        evenement.pop("event_id", None)
        evenement.pop("original_id", None)
    return evenement


def enregistrer_evenement(page, charge: dict, *, methode: str) -> object:
    if not methode.strip():
        raise MethodeEcritureAbsente("methode_ecriture vide : capturer un Enregistrer sur URCA_FORMATION")
    return appeler(page, methode, [[preparer_evenement(charge)]])


def masquer_semaine(*, longueur: int, indice: int) -> str:
    if indice < 0 or indice >= longueur:
        raise IndexError(f"indice semaine {indice} hors masque de {longueur}")
    return ("N" * indice) + "Y" + ("N" * (longueur - indice - 1))
