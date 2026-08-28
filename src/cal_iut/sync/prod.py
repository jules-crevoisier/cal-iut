"""Synchronisation entre le planning LOCAL et celui de PRODUCTION.

Le problème d'origine (29/08/2026) : il existe deux bases, celle du poste de
développement et celle du serveur déployé, et rien ne les reliait. Des
corrections faites en local (réaffectation de salles, disponibilité d'un
vacataire) restaient invisibles en production, parce qu'un redéploiement ne
réécrit JAMAIS le volume Docker — c'est précisément ce qui protège les
modifications faites en ligne.

Le parti pris ici : ne pas « fusionner intelligemment » deux bases
divergentes, mais faire de la PRODUCTION la source de vérité du planning, et
donner de quoi la lire et l'écrire explicitement :

- `comparer`  : ce qui diffère, sans rien changer nulle part ;
- `tirer`     : ramener le planning de production en local ;
- `pousser`   : appliquer les différences locales sur la production.

`pousser` passe par l'API, pas par un remplacement du fichier de base :
chaque modification emprunte les mêmes contrôles qu'une modification faite à
la main, la production n'est jamais arrêtée, et le reste de son état
(journal des corrections, salles créées, envois de mails) est préservé.

Aucune de ces opérations n'est implicite : rien ne part en production sans
un appel explicite ET une confirmation (`appliquer=True`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

URL_ENV = "CAL_IUT_PROD_URL"
MDP_ENV = "CAL_IUT_PROD_PASSWORD"

# Une séance, réduite à ce qui peut différer entre deux instances.
Etat = tuple[int, int, int, str | None]  # (semaine, jour, créneau, room_id)


class SyncError(RuntimeError):
    pass


@dataclass
class Instance:
    """Une instance cal-iut joignable par HTTP (locale ou distante)."""

    url: str
    mot_de_passe: str
    _client: httpx.Client | None = field(default=None, repr=False)

    def __enter__(self) -> Instance:
        self._client = httpx.Client(base_url=self.url.rstrip("/"), timeout=30.0, follow_redirects=True)
        r = self._client.post("/auth/login", json={"password": self.mot_de_passe})
        if r.status_code != 200:
            raise SyncError(f"Connexion refusée sur {self.url} (HTTP {r.status_code}).")
        return self

    def __exit__(self, *_exc) -> None:
        if self._client:
            self._client.close()

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            raise SyncError("Instance non connectée (utiliser `with Instance(...)`).")
        return self._client

    def planning(self) -> dict[str, Etat]:
        r = self.client.get("/timetable")
        r.raise_for_status()
        data = r.json()
        placements = data if isinstance(data, list) else data.get("placements", [])
        return {
            p["session_id"]: (p["week"], p["day"], p["slot"], p.get("room_id"))
            for p in placements
        }


@dataclass
class Difference:
    session_id: str
    local: Etat | None
    distant: Etat | None

    @property
    def genre(self) -> str:
        if self.distant is None:
            return "absente_en_prod"
        if self.local is None:
            return "absente_en_local"
        if self.local[:3] != self.distant[:3]:
            return "creneau"
        return "salle"


@dataclass
class Comparaison:
    differences: list[Difference] = field(default_factory=list)
    identiques: int = 0

    def par_genre(self) -> dict[str, list[Difference]]:
        groupes: dict[str, list[Difference]] = {}
        for d in self.differences:
            groupes.setdefault(d.genre, []).append(d)
        return groupes

    def resume(self) -> str:
        g = self.par_genre()
        if not self.differences:
            return f"Identique ({self.identiques} séances)."
        parts = [f"{len(v)} {k.replace('_', ' ')}" for k, v in sorted(g.items())]
        return f"{len(self.differences)} différence(s) sur {self.identiques + len(self.differences)} : " + ", ".join(parts) + "."


def comparer(local: dict[str, Etat], distant: dict[str, Etat]) -> Comparaison:
    """Compare deux plannings. Ne touche à rien : sert autant à décider quoi
    pousser qu'à simplement savoir ce qui a bougé en production."""
    c = Comparaison()
    for sid in sorted(set(local) | set(distant)):
        a, b = local.get(sid), distant.get(sid)
        if a == b:
            c.identiques += 1
        else:
            c.differences.append(Difference(sid, a, b))
    return c


def prod_depuis_env() -> Instance:
    url = os.environ.get(URL_ENV)
    mdp = os.environ.get(MDP_ENV)
    if not url or not mdp:
        raise SyncError(
            f"Production non configurée : renseigner {URL_ENV} et {MDP_ENV} "
            "(par exemple dans le fichier `.env`, jamais commité)."
        )
    return Instance(url=url, mot_de_passe=mdp)


@dataclass
class ResultatPoussee:
    appliquees: list[str] = field(default_factory=list)
    echecs: list[tuple[str, str]] = field(default_factory=list)
    ignorees: list[tuple[str, str]] = field(default_factory=list)

    def resume(self) -> str:
        base = f"{len(self.appliquees)} appliquée(s)"
        if self.ignorees:
            base += f", {len(self.ignorees)} ignorée(s)"
        if self.echecs:
            base += f", {len(self.echecs)} en échec"
        return base + "."


def pousser(
    cible: Instance,
    comparaison: Comparaison,
    *,
    appliquer: bool = False,
    force: bool = True,
) -> ResultatPoussee:
    """Applique les différences LOCALES sur `cible` (la production).

    `appliquer=False` (défaut) : simulation — rien n'est envoyé, le résultat
    dit seulement ce qui SERAIT fait. Envoyer en production est une action
    sortante et difficile à défaire ; elle ne doit jamais arriver par
    inadvertance.

    `force=True` par défaut : les positions poussées viennent d'un planning
    déjà vérifié en local, et l'ordre d'application fait forcément passer par
    des états intermédiaires en conflit (deux séances qui s'échangent). Sans
    forçage, la moitié d'un échange échouerait.

    Les séances absentes d'un côté ne sont PAS traitées : créer ou supprimer
    une séance à distance demande une décision humaine, pas une
    synchronisation automatique. Elles ressortent en `ignorees`.
    """
    resultat = ResultatPoussee()
    for d in comparaison.differences:
        if d.local is None or d.distant is None:
            resultat.ignorees.append((d.session_id, d.genre))
            continue
        semaine, jour, creneau, salle = d.local
        if not appliquer:
            resultat.appliquees.append(d.session_id)
            continue
        try:
            if d.genre == "creneau":
                r = cible.client.patch(
                    f"/placements/{d.session_id}",
                    json={"week": semaine, "day": jour, "slot": creneau, "room_id": salle, "force": force},
                )
                if r.status_code != 200:
                    raise SyncError(f"HTTP {r.status_code} : {r.text[:160]}")
            # La salle est repoussée dans les deux cas : un déplacement peut
            # la faire recalculer côté serveur, il faut donc la réaffirmer
            # après coup pour que les deux instances finissent identiques.
            r = cible.client.patch(
                f"/placements/{d.session_id}/salle",
                json={"room_id": salle or "", "force": force},
            )
            if r.status_code != 200:
                raise SyncError(f"salle : HTTP {r.status_code} : {r.text[:160]}")
            resultat.appliquees.append(d.session_id)
        except Exception as exc:  # noqa: BLE001 — un échec isolé ne doit pas tout arrêter
            resultat.echecs.append((d.session_id, str(exc)))
    return resultat


def planning_local_depuis_db(db_path=None) -> dict[str, Etat]:
    """Lit le planning local directement dans SQLite, sans passer par l'API.

    Le serveur local n'a pas à tourner pour comparer avec la production : le
    plus souvent on veut justement savoir ce qui diffère AVANT de relancer
    quoi que ce soit. C'est aussi la même source que celle que l'API sert
    (`current_placements` du dernier run), donc les deux chemins donnent le
    même résultat.
    """
    from cal_iut.db.repository import PlanningRepository
    from cal_iut.db.session import get_db, init_db

    init_db(db_path)
    db = get_db(db_path)
    try:
        run = PlanningRepository(db).get_latest_run()
        if run is None:
            raise SyncError("Aucun run en base locale : rien à comparer.")
        from cal_iut.db.models import CurrentPlacement

        lignes = db.query(CurrentPlacement).filter(CurrentPlacement.run_id == run.id).all()
        return {r.session_id: (r.week, r.day, r.slot, r.room_id) for r in lignes}
    finally:
        db.close()
