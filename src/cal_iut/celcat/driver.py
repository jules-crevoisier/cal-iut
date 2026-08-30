"""Pilotage du navigateur pour saisir les séances dans Celcat.

SEUL module du projet qui a besoin de Celcat, d'identifiants et d'un
navigateur — tout le reste (`mapping.py`, `sync.py`) se teste hors ligne.
C'est volontaire : la partie fragile est isolée derrière une interface
étroite (`PiloteCelcat`), le reste ne dépend jamais de la forme du site.

ÉTAT AU 29/08/2026 : les sélecteurs ne sont PAS renseignés. L'utilisateur
n'avait pas encore ses identifiants (« je les aurai demain, je voudrais que
tu fasses une base qu'on ait juste à adapter »), donc personne n'a pu voir
le vrai formulaire. Les remplir au jugé aurait produit du code qui a l'air
fini mais ne peut pas marcher — pire qu'un squelette assumé, dans un outil
qui sert aussi à PAYER les enseignants. Chaque endroit à compléter est
marqué `À ADAPTER`.

Deux garde-fous structurels en attendant :
- `PiloteSimule` rejoue tout le déroulé sans navigateur : c'est lui qui
  tourne tant que Playwright n'est pas installé/configuré, et il sert de
  mode « répétition » même après.
- `SaisieCelcat.executer` refuse de démarrer si des séances sont bloquées
  ou si le pilote n'est pas prêt, plutôt que d'ouvrir un navigateur pour
  s'arrêter au milieu d'un formulaire.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Protocol

from cal_iut.celcat.mapping import EntreeCelcat


class PiloteCelcat(Protocol):
    """Ce que la saisie attend d'un pilote — volontairement minimal, pour
    qu'un pilote simulé soit strictement équivalent à un vrai."""

    def ouvrir_session(self, identifiant: str, mot_de_passe: str) -> None: ...
    def choisir_groupe(self, groupe: str, semaine: int) -> None: ...
    def creer_seance(self, entree: EntreeCelcat) -> None: ...
    def modifier_seance(self, entree: EntreeCelcat) -> None: ...
    def supprimer_seance(self, session_id: str) -> None: ...
    def fermer(self) -> None: ...


@dataclass
class Rythme:
    """Pauses entre actions — retour utilisateur : « il faut que le clicker
    ne soit pas trop rapide pour pas qu'il soit détecté comme un bot ».

    Des pauses ALÉATOIRES et non une constante : une cadence parfaitement
    régulière est justement ce qui distingue un script d'un humain. Les
    valeurs par défaut sont volontairement prudentes (une séance toutes
    ~3 s) ; saisir une semaine complète prend donc quelques minutes, ce qui
    reste sans commune mesure avec le temps d'une saisie à la main.
    """

    entre_actions: tuple[float, float] = (0.4, 1.1)
    entre_seances: tuple[float, float] = (1.8, 4.2)
    entre_groupes: tuple[float, float] = (3.0, 6.5)
    # Pause plus longue de loin en loin, comme une personne qui souffle.
    pause_longue_toutes_les: int = 25
    pause_longue: tuple[float, float] = (12.0, 25.0)

    def _dormir(self, plage: tuple[float, float]) -> None:
        time.sleep(random.uniform(*plage))

    def apres_action(self) -> None:
        self._dormir(self.entre_actions)

    def apres_seance(self, n_faites: int) -> None:
        if self.pause_longue_toutes_les and n_faites and n_faites % self.pause_longue_toutes_les == 0:
            self._dormir(self.pause_longue)
        else:
            self._dormir(self.entre_seances)

    def apres_groupe(self) -> None:
        self._dormir(self.entre_groupes)


@dataclass
class PiloteSimule:
    """Rejoue le déroulé complet sans navigateur : sert de mode répétition
    et de pilote par défaut tant que Celcat n'est pas configuré. Enregistre
    tout ce qu'un vrai pilote ferait, dans l'ordre."""

    rythme: Rythme | None = None  # None = aucune pause (répétition instantanée)
    actions: list[str] = field(default_factory=list)

    def ouvrir_session(self, identifiant: str, mot_de_passe: str) -> None:
        # Le mot de passe n'est JAMAIS journalisé, même en simulation.
        self.actions.append(f"connexion({identifiant})")

    def choisir_groupe(self, groupe: str, semaine: int) -> None:
        self.actions.append(f"groupe({groupe}, S{semaine + 1})")

    def creer_seance(self, entree: EntreeCelcat) -> None:
        self.actions.append(f"creer({entree.session_id} {entree.heure_debut} {entree.salle})")

    def modifier_seance(self, entree: EntreeCelcat) -> None:
        self.actions.append(f"modifier({entree.session_id} {entree.heure_debut} {entree.salle})")

    def supprimer_seance(self, session_id: str) -> None:
        self.actions.append(f"supprimer({session_id})")

    def fermer(self) -> None:
        self.actions.append("fermeture")


class PilotePlaywright:
    """Vrai pilote. NON FONCTIONNEL en l'état : voir l'avertissement en tête
    de module. Chaque `À ADAPTER` correspond à un élément du formulaire
    Celcat qu'il faut voir une fois pour le renseigner."""

    URL_CONNEXION = ""  # À ADAPTER : URL de connexion Celcat de l'URCA

    def __init__(self, rythme: Rythme, *, visible: bool = True) -> None:
        self.rythme = rythme
        # `visible=True` par défaut : sur un outil qui alimente la paie, on
        # veut pouvoir REGARDER ce qui se passe et reprendre la main.
        self.visible = visible
        self._page = None
        self._navigateur = None
        self._playwright = None

    @staticmethod
    def disponible() -> tuple[bool, str]:
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False, (
                "Playwright n'est pas installé. `pip install playwright` puis "
                "`playwright install chromium`."
            )
        if not PilotePlaywright.URL_CONNEXION:
            return False, "URL de connexion Celcat non renseignée (cf. celcat/driver.py)."
        return True, ""

    def ouvrir_session(self, identifiant: str, mot_de_passe: str) -> None:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._navigateur = self._playwright.chromium.launch(headless=not self.visible)
        self._page = self._navigateur.new_page()
        self._page.goto(self.URL_CONNEXION)
        raise NotImplementedError(
            "Formulaire de connexion Celcat à renseigner (cf. `À ADAPTER` dans driver.py)."
        )

    def choisir_groupe(self, groupe: str, semaine: int) -> None:
        raise NotImplementedError("Sélection du groupe/semaine à renseigner.")

    def creer_seance(self, entree: EntreeCelcat) -> None:
        raise NotImplementedError("Formulaire de création de séance à renseigner.")

    def modifier_seance(self, entree: EntreeCelcat) -> None:
        raise NotImplementedError("Formulaire de modification à renseigner.")

    def supprimer_seance(self, session_id: str) -> None:
        raise NotImplementedError("Suppression de séance à renseigner.")

    def fermer(self) -> None:
        if self._navigateur:
            self._navigateur.close()
        if self._playwright:
            self._playwright.stop()


class AccesPerdu(RuntimeError):
    """Celcat est devenu injoignable — typiquement le VPN qui tombe.

    Distinct d'un échec de séance : celui-ci est isolé et n'arrête rien,
    celui-là invalide tout ce qui suivrait.
    """


@dataclass
class ResultatSaisie:
    creees: list[str] = field(default_factory=list)
    modifiees: list[str] = field(default_factory=list)
    supprimees: list[str] = field(default_factory=list)
    # Une séance qui échoue n'interrompt PAS les suivantes : sur une saisie
    # de plusieurs centaines de lignes, tout arrêter à la première erreur
    # laisserait un Celcat à moitié rempli sans savoir où ça s'est arrêté.
    echecs: list[tuple[str, str]] = field(default_factory=list)
    interrompu: bool = False
    # Interrompu PARCE QUE Celcat est devenu injoignable — à distinguer
    # d'un arrêt demandé par l'utilisateur : ici, il reste du travail.
    acces_perdu: bool = False

    def resume(self) -> str:
        base = (
            f"{len(self.creees)} créée(s), {len(self.modifiees)} modifiée(s), "
            f"{len(self.supprimees)} supprimée(s)"
        )
        if self.echecs:
            base += f", {len(self.echecs)} en échec"
        if self.interrompu:
            base += (
                " — INTERROMPU : Celcat est devenu injoignable (VPN ?)"
                if self.acces_perdu
                else " — INTERROMPU avant la fin"
            )
        return base + "."


class SaisieCelcat:
    """Applique un `PlanSync` via un pilote, au rythme donné.

    Ne décide RIEN : le plan (quoi créer/modifier/supprimer) vient de
    `sync.construire_plan`, la traduction de `mapping`. Ce module ne fait
    qu'exécuter, dans un ordre stable et à une cadence crédible.
    """

    def __init__(self, pilote, rythme: Rythme, *, journaliser=None, verifier_acces=None) -> None:
        self.pilote = pilote
        self.rythme = rythme
        # Appelé après CHAQUE saisie réussie : c'est ce qui permet de
        # reprendre là où on s'est arrêté si la session est coupée en
        # cours de route, plutôt que de tout re-saisir.
        self.journaliser = journaliser
        # Rend True tant que Celcat est joignable (cf. `celcat/reseau.py`).
        # Celcat vit derrière le VPN de l'URCA, et une coupure ne se voit
        # pas : les pages cessent simplement de répondre. Sans ce contrôle,
        # le pilote continuerait à cliquer dans le vide et accumulerait des
        # échecs — inacceptable sur un outil qui alimente la paie. Absent
        # (tests, pilote simulé), rien ne change.
        self.verifier_acces = verifier_acces

    def executer(self, plan, identifiant: str, mot_de_passe: str, *, doit_continuer=None) -> ResultatSaisie:
        """`doit_continuer` : fonction sans argument rendant False pour
        arrêter proprement (bouton « stop » de l'interface). Vérifiée entre
        chaque séance — jamais au milieu d'un formulaire à moitié rempli."""
        resultat = ResultatSaisie()
        if plan.bloquees:
            raise ValueError(
                f"{len(plan.bloquees)} séance(s) non saisissable(s) : corrigez-les avant "
                "de lancer la saisie (rien n'a été envoyé à Celcat)."
            )

        # Contrôle AVANT d'ouvrir la session : rien de pire que d'échouer à
        # la trentième séance sur un VPN qui n'était pas monté au départ.
        if self.verifier_acces and not self.verifier_acces():
            raise AccesPerdu(
                "Celcat n'est pas joignable : montez le VPN URCA avant de lancer la saisie "
                "(rien n'a été envoyé)."
            )

        self.pilote.ouvrir_session(identifiant, mot_de_passe)
        self.rythme.apres_action()
        faites = 0
        try:
            # Groupées par (groupe, semaine) : Celcat impose de se placer
            # sur un groupe et une semaine avant de saisir. Regrouper évite
            # de re-naviguer à chaque séance — c'est aussi ce que faisait
            # l'ancien autoclicker (`call groupe ... / call fingroupe`).
            for (groupe, semaine), entrees in _par_groupe_semaine(plan.a_creer + plan.a_modifier):
                if doit_continuer and not doit_continuer():
                    resultat.interrompu = True
                    return resultat
                if self.verifier_acces and not self.verifier_acces():
                    resultat.interrompu = True
                    resultat.acces_perdu = True
                    return resultat
                self.pilote.choisir_groupe(groupe, semaine)
                self.rythme.apres_action()
                a_modifier = {e.session_id for e in plan.a_modifier}
                for entree in entrees:
                    if doit_continuer and not doit_continuer():
                        resultat.interrompu = True
                        return resultat
                    try:
                        if entree.session_id in a_modifier:
                            self.pilote.modifier_seance(entree)
                            resultat.modifiees.append(entree.session_id)
                        else:
                            self.pilote.creer_seance(entree)
                            resultat.creees.append(entree.session_id)
                        if self.journaliser:
                            self.journaliser(entree)
                    except Exception as exc:  # noqa: BLE001 — un échec isolé ne doit pas tout arrêter
                        resultat.echecs.append((entree.session_id, str(exc)))
                        # ...sauf si c'est le réseau qui a lâché : les
                        # suivantes échoueraient toutes, et chaque tentative
                        # sur une page morte risque de cliquer à côté. On
                        # s'arrête là, en laissant `echecs` et le journal
                        # dire exactement où reprendre.
                        if self.verifier_acces and not self.verifier_acces():
                            resultat.interrompu = True
                            resultat.acces_perdu = True
                            return resultat
                    faites += 1
                    self.rythme.apres_seance(faites)
                self.rythme.apres_groupe()

            for session_id in plan.a_supprimer:
                if doit_continuer and not doit_continuer():
                    resultat.interrompu = True
                    return resultat
                try:
                    self.pilote.supprimer_seance(session_id)
                    resultat.supprimees.append(session_id)
                except Exception as exc:  # noqa: BLE001
                    resultat.echecs.append((session_id, str(exc)))
                faites += 1
                self.rythme.apres_seance(faites)
        finally:
            self.pilote.fermer()
        return resultat


def _par_groupe_semaine(entrees: list[EntreeCelcat]):
    """Regroupe en conservant un ordre STABLE (groupe, semaine, jour,
    heure) : deux exécutions successives saisissent dans le même ordre, ce
    qui rend une reprise après interruption prévisible."""
    par_cle: dict[tuple[str, int], list[EntreeCelcat]] = {}
    for e in entrees:
        par_cle.setdefault((e.groupe, e.semaine), []).append(e)
    for cle in sorted(par_cle):
        yield cle, sorted(par_cle[cle], key=lambda e: (e.jour, e.heure_debut))
