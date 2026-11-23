"""Processus qui déroule une génération : `python -m cal_iut.generation.ouvrier <dossier>`.

Lancé par `taches.lancer` (donc par l'API), détaché du serveur. Il n'écrit
que dans son dossier, jusqu'à la dernière étape, qui enregistre le résultat
en base comme BROUILLON (`PlanningRun.etat = "brouillon"`) : le planning en
service n'est jamais touché, et rien ne part vers Celcat.

Chaque étape est reprenable : relancé sur un dossier entamé, l'ouvrier
saute ce qui est fait (séances préparées, tentatives déjà jouées, meilleur
résultat gardé).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter
from pathlib import Path

from cal_iut.generation import taches, verification

RACINE = taches.RACINE
PREMIERE_GRAINE = 2027
PAS_DE_GRAINE = 1013
# Défauts de la boucle de `scripts/solve_until_ok.py` : dix tentatives de
# graines différentes valent mieux qu'une qui s'acharne.
DERNIER_RECOURS_SECONDES = 90
DERNIER_RECOURS_GRAINES = 3


class Annulee(Exception):
    pass


class Ouvrier:
    def __init__(self, dossier: Path) -> None:
        self.dossier = dossier
        self.etat = taches.lire_dossier(dossier)
        self.params = self.etat["parametres"]
        self.groupe = self.params["semestre_group"]
        self._arret = threading.Event()

    # ── État ──────────────────────────────────────────────────────────

    def enregistrer(self) -> None:
        taches.ecrire(self.dossier, self.etat)

    def _etape(self, cle: str) -> dict:
        return next(e for e in self.etat["etapes"] if e["cle"] == cle)

    def debut(self, cle: str) -> None:
        etape = self._etape(cle)
        etape["statut"] = "en_cours"
        etape.setdefault("debut", taches._maintenant())
        print(f"\n=== {etape['libelle']}", flush=True)
        self.enregistrer()

    def fin(self, cle: str, detail: str | None = None) -> None:
        etape = self._etape(cle)
        etape["statut"] = "faite"
        etape["fin"] = taches._maintenant()
        if detail:
            etape["detail"] = detail
            print(f"    {detail}", flush=True)
        self.enregistrer()

    def faite(self, cle: str) -> bool:
        return self._etape(cle)["statut"] == "faite"

    def verifier_annulation(self) -> None:
        if (self.dossier / "annuler").exists():
            raise Annulee

    def _battre(self) -> None:
        while not self._arret.wait(taches.PERIODE_BATTEMENT_S):
            (self.dossier / "battement").touch()

    # ── Déroulé ───────────────────────────────────────────────────────

    def executer(self) -> int:
        (self.dossier / "battement").touch()
        threading.Thread(target=self._battre, daemon=True).start()
        self.etat["statut"] = "en_cours"
        self.etat.setdefault("demarre_le", taches._maintenant())
        self.etat["pid"] = _pid()
        self.enregistrer()
        try:
            self.verifier_annulation()
            self.preparer()
            self.verifier()
            self.calculer()
            self.finir()
            self.enregistrer_brouillon()
        except Annulee:
            self._clore("annulee", None)
            print("\nGénération annulée.", flush=True)
            return 0
        except Exception as exc:  # noqa: BLE001 — l'échec doit se lire dans l'interface
            traceback.print_exc()
            self._clore("echec", f"{exc.__class__.__name__} : {exc}")
            return 1
        finally:
            self._arret.set()
        self._clore("terminee", None)
        print("\nGénération terminée.", flush=True)
        return 0

    def _clore(self, statut: str, erreur: str | None) -> None:
        self.etat["statut"] = statut
        self.etat["erreur"] = erreur
        self.etat["termine_le"] = taches._maintenant()
        if statut != "terminee":
            taches._clore_etapes(self.etat, statut)
        self.enregistrer()

    # ── 1. Séances à placer ───────────────────────────────────────────

    def preparer(self) -> None:
        if self.faite("preparation") and (self.dossier / "sessions.json").exists():
            return
        self.debut("preparation")
        from cal_iut.ingestion.pipeline import run_ingestion

        resultat = run_ingestion(RACINE / "data" / "config", semestre_group=self.groupe)
        if not resultat.sessions:
            raise RuntimeError(
                "Aucune séance à placer pour ce semestre : la maquette ne contient "
                "aucun module pour " + ", ".join(taches.GROUPES[self.groupe]["semestres"]) + "."
            )
        # L'audit et `cal-iut solve` lisent aussi `data/generated/` : mêmes
        # fichiers que `cal-iut ingest`.
        seances = verification.ecrire_les_fichiers_generes(RACINE, resultat)
        (self.dossier / "sessions.json").write_text(seances, encoding="utf-8")
        self.etat["seances_total"] = len(resultat.sessions)
        # D'où vient la maquette de cette génération (cf. ingestion/mmi_previ.py).
        from cal_iut.ingestion import mmi_previ

        copie = mmi_previ.etat_de_la_copie(RACINE, self.groupe)
        self.etat["source"] = {"origine": "copie_livree"} if copie is None else {"origine": "mmi_previ", **copie}
        origine = "copie livrée avec l'application" if copie is None else "MMI Prévi"
        self.fin(
            "preparation",
            f"{len(resultat.sessions)} séances, {len(resultat.courses)} modules (maquette : {origine})",
        )

    # ── 2. Audit des données ──────────────────────────────────────────

    def verifier(self) -> None:
        if self.faite("verification"):
            return
        self.debut("verification")
        rapport = verification.rapport_des_donnees(
            RACINE, self.groupe, weeks=self.params["weeks"], fi_max_week=self.params["fi_max_week"]
        )
        self.etat["verification"] = rapport
        # Lancer des heures de calcul sur des données que l'audit prouve
        # infaisables ne sert à rien : même refus qu'à l'écran.
        restants = verification.bloquants(rapport) + [
            c for c in verification.controle_celcat(RACINE) if verification.est_bloquant(c)
        ]
        if restants:
            raise RuntimeError(
                f"{len(restants)} point(s) à régler avant de générer : "
                + " ; ".join(c["message"] for c in restants[:3])
            )
        resume = rapport["resume"]
        self.fin(
            "verification",
            f"{resume['erreurs']} erreur(s), {resume['alertes']} alerte(s), "
            f"{resume['controles_ok']} contrôle(s) passé(s)",
        )

    # ── 3. Solveur, plusieurs graines, on garde le meilleur ───────────

    def calculer(self) -> None:
        if self.faite("calcul") and (self.dossier / "meilleur.json").exists():
            return
        self.debut("calcul")
        from cal_iut.generation.recherche import diagnostiquer, load_sessions, score_run
        from cal_iut.ingestion.config_loader import load_groups, load_solver_scheduled_sae
        from cal_iut.ingestion.pipeline import SEMESTRE_GROUP_ANCHOR

        config = RACINE / "data" / "config"
        seances = load_sessions(self.dossier / "sessions.json")
        groupes = load_groups(config)
        sae_solveur = load_solver_scheduled_sae(config)
        fi_max_week = self.params["fi_max_week"]

        def _score(fichier: Path):
            return score_run(
                json.loads(fichier.read_text(encoding="utf-8")), seances, groupes,
                fi_max_week=fi_max_week, scheduled_sae=sae_solveur,
            )

        meilleur_fichier = self.dossier / "meilleur.json"
        essai = self.dossier / "tentative.json"
        meilleur = _score(meilleur_fichier) if meilleur_fichier.exists() else None

        budget_s = float(self.params["heures"]) * 3600
        while len(self.etat["tentatives"]) < int(self.params["tentatives"]):
            self.verifier_annulation()
            ecoule = sum(t.get("secondes", 0) for t in self.etat["tentatives"])
            if ecoule >= budget_s:
                print("    budget de temps épuisé", flush=True)
                break
            numero = len(self.etat["tentatives"]) + 1
            graine = PREMIERE_GRAINE + (numero - 1) * PAS_DE_GRAINE
            essai.unlink(missing_ok=True)
            self.etat["tentative_en_cours"] = {"numero": numero, "graine": graine, "debut": taches._maintenant()}
            self.enregistrer()
            print(f"  tentative {numero} (graine {graine})", flush=True)
            debut = time.time()
            statut = self._lancer_solveur(graine, essai)
            entree: dict = {
                "numero": numero, "graine": graine, "statut": statut,
                "secondes": round(time.time() - debut), "gardee": False,
            }
            if essai.exists():
                try:
                    score = _score(essai)
                except (json.JSONDecodeError, KeyError) as exc:
                    entree["erreur"] = f"sortie illisible : {exc}"
                else:
                    entree.update(placees=score.placed, manquantes=score.missing,
                                  ordre=score.cohort_order_violations)
                    print(f"    {entree['secondes']} s : {score.summary()}", flush=True)
                    if score.missing:
                        causes = diagnostiquer(
                            json.loads(essai.read_text(encoding="utf-8")), seances, RACINE,
                            SEMESTRE_GROUP_ANCHOR[self.groupe],
                        )
                        if causes:
                            entree["causes"] = causes[:5]
                    if score.better_than(meilleur):
                        shutil.copyfile(essai, meilleur_fichier)
                        meilleur = score
                        entree["gardee"] = True
                        self.etat["meilleur"] = {
                            "numero": numero, "placees": score.placed, "manquantes": score.missing,
                            "statut": score.status,
                        }
            else:
                entree["erreur"] = "le solveur n'a rien produit"
                print(f"    échec : {statut}", flush=True)
            self.etat["tentatives"].append(entree)
            self.etat["tentative_en_cours"] = None
            self.enregistrer()
            if (
                self.params.get("arret_si_complet")
                and meilleur is not None
                and meilleur.missing == 0
                and meilleur.cohort_order_violations == 0
                and meilleur.fi_max_week_violations == 0
            ):
                print("    résultat complet, inutile de continuer", flush=True)
                break

        essai.unlink(missing_ok=True)
        if meilleur is None:
            derniere = self.etat["tentatives"][-1] if self.etat["tentatives"] else {}
            raise RuntimeError(
                "Le solveur n'a produit aucun emploi du temps exploitable"
                + (f" (dernier statut : {derniere.get('statut')})" if derniere.get("statut") else "")
                + ". Voir le journal."
            )
        self.fin("calcul", f"{meilleur.placed} séances placées, {meilleur.missing} restantes")

    def _lancer_solveur(self, graine: int, sortie: Path) -> str:
        commande = [
            sys.executable, "-u", "-m", "cal_iut.cli", "solve", "--decomposed",
            "--sessions", str(self.dossier / "sessions.json"),
            "--semestre-group", self.groupe,
            "--spread-weight", str(self.params["spread_weight"]),
            "--random-seed", str(graine),
            # Une seule passe interne : la diversité vient de cette boucle.
            "--attempts", "1",
            "--last-resort-seconds", str(DERNIER_RECOURS_SECONDES),
            "--last-resort-seeds", str(DERNIER_RECOURS_GRAINES),
            "--num-workers", str(self.params["num_workers"]),
            "--output", str(sortie),
        ]
        if not self.params.get("referent_sae_strict"):
            commande.append("--no-sae-supervisor-hard")
        if self.params["weeks"]:
            commande += ["--weeks", str(self.params["weeks"])]
        if self.params["fi_max_week"] is not None:
            commande += ["--fi-max-week", str(self.params["fi_max_week"])]
        trace = self.dossier / "solveur.log"
        with trace.open("wb") as flux:
            processus = subprocess.Popen(
                commande, cwd=RACINE, stdout=flux, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True,
            )
            while processus.poll() is None:
                if (self.dossier / "annuler").exists():
                    taches.arreter_groupe(processus.pid)
                    try:
                        processus.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        processus.kill()
                    raise Annulee
                time.sleep(2)
        texte = trace.read_text(encoding="utf-8", errors="replace")
        for ligne in texte.splitlines():
            if ligne.startswith("Solver status:"):
                return ligne.split(":", 1)[1].strip()
        # Pas de statut : garder la fin de la sortie, c'est l'erreur.
        print("\n".join("      | " + ligne for ligne in texte.splitlines()[-15:]), flush=True)
        return f"arrêt anormal (code {processus.returncode})"

    # ── 4. Salles, puis séances restantes ─────────────────────────────

    def finir(self) -> None:
        if self.faite("finition") and (self.dossier / "planning.json").exists():
            return
        self.debut("finition")
        self.verifier_annulation()
        from cal_iut.generation.finition import finir_planning

        donnees = json.loads((self.dossier / "meilleur.json").read_text(encoding="utf-8"))
        rapport = finir_planning(donnees, self.dossier / "sessions.json", RACINE, self.groupe)
        (self.dossier / "planning.json").write_text(
            json.dumps(donnees, ensure_ascii=False), encoding="utf-8"
        )
        motifs = Counter(r["raison"] for r in rapport["non_placees"])
        self.etat["resultat"] = {
            "statut_solveur": donnees.get("status"),
            "placees": len(donnees["placements"]),
            "a_placer": rapport["a_placer"],
            "completees": rapport["completees"],
            "sans_salle": rapport["sans_salle"],
            "non_placees": rapport["non_placees"],
            "motifs": [{"raison": raison, "nombre": nombre} for raison, nombre in motifs.most_common()],
        }
        self.fin(
            "finition",
            f"{rapport['completees']} séance(s) ajoutée(s), "
            f"{len(rapport['non_placees'])} à placer à la main",
        )

    # ── 5. Brouillon en base ──────────────────────────────────────────

    def enregistrer_brouillon(self) -> None:
        if self.faite("enregistrement") and self.etat.get("run_id"):
            return
        self.debut("enregistrement")
        self.verifier_annulation()
        from cal_iut.db.repository import ETAT_BROUILLON, PlanningRepository
        from cal_iut.db.session import get_db, init_db

        donnees = json.loads((self.dossier / "planning.json").read_text(encoding="utf-8"))
        placements = donnees["placements"]
        chemin_base = taches.STATE_DIR / "cal-iut.db"
        init_db(chemin_base)
        base = get_db(chemin_base)
        try:
            run = PlanningRepository(base).save_run(
                parcours="MMI",
                semestre=self.groupe.upper(),
                status=str(donnees.get("status") or "FEASIBLE"),
                objective_value=donnees.get("objective_value"),
                gap_penalty=int(donnees.get("gap_penalty") or 0),
                weeks=max(int(p["week"]) for p in placements) + 1,
                solver_placements=placements,
                current_placements=[],
                etat=ETAT_BROUILLON,
            )
            self.etat["run_id"] = run.id
        finally:
            base.close()
        self.fin("enregistrement", f"brouillon n° {self.etat['run_id']}")


def _pid() -> int:
    import os

    return os.getpid()


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print("usage : python -m cal_iut.generation.ouvrier <dossier>", file=sys.stderr)
        return 2
    return Ouvrier(Path(arguments[0])).executer()


if __name__ == "__main__":
    sys.exit(main())
