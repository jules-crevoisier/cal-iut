"""Pilotage du navigateur pour saisir les séances dans Celcat.

SEUL module du projet qui a besoin de Celcat, d'identifiants et d'un
navigateur — tout le reste (`mapping.py`, `sync.py`) se teste hors ligne.
C'est volontaire : la partie fragile est isolée derrière une interface
étroite (`PiloteCelcat`), le reste ne dépend jamais de la forme du site.

ÉTAT AU 01/09/2026. `PilotePlaywright` est branché sur les primitives
vérifiées de `navigateur.py` : connexion (base, rôle), ouverture d'un groupe
par son nom Celcat, choix de la semaine CONFIRMÉ par son infobulle, icônes
de la barre du panneau, et remplissage du formulaire par glisser-déposer —
cette dernière technique venant de l'ancien autoclicker nut-js
(`clickclick/robot01.js`), seul endroit où elle était consignée.

Ce qui manque encore est nommé, pas caché : les LIBELLÉS des champs du
formulaire de création, jamais ouvert à ce jour. Ils ne sont pas devinés
dans le code — ils vivent dans `data/config/celcat_formulaire.yaml`, et le
pilote refuse d'écrire tant qu'ils y manquent. `relever_formulaire` les
obtient en une session supervisée sur la base d'entraînement.

Trois garde-fous structurels :
- `PiloteSimule` rejoue tout le déroulé sans navigateur : c'est lui qui
  tourne tant que Playwright n'est pas installé/configuré, et il sert de
  mode « répétition » même après.
- `SaisieCelcat.executer` refuse de démarrer si des séances sont bloquées
  ou si le pilote n'est pas prêt, plutôt que d'ouvrir un navigateur pour
  s'arrêter au milieu d'un formulaire.
- `PilotePlaywright` écrit par défaut dans la base d'ENTRAÎNEMENT
  (`URCA_FORMATION`) : toucher la base annuelle réelle doit être un choix
  explicite, pas un oubli de paramètre.
"""

from __future__ import annotations

import datetime as dt
import os
import random
import time
from dataclasses import dataclass, field
from typing import Protocol

from cal_iut.celcat import navigateur as nav
from cal_iut.celcat.formulaire import CarteFormulaire, FormulaireNonReleve, charger_carte
from cal_iut.celcat.mapping import EntreeCelcat


class PiloteCelcat(Protocol):
    """Ce que la saisie attend d'un pilote — volontairement minimal, pour
    qu'un pilote simulé soit strictement équivalent à un vrai."""

    def ouvrir_session(self, identifiant: str, mot_de_passe: str) -> None: ...
    # `groupe` est le nom CELCAT du groupe (« BUT MMI S2 TD AB »), pas notre
    # libellé : le pilote doit recevoir ce qu'il aura à retrouver là-bas.
    # `lundi` (ISO) est indispensable — le sélecteur de semaines de Celcat
    # s'identifie par ses dates, jamais par un index.
    def choisir_groupe(self, groupe: str, semaine: int, *, lundi: str = "") -> None: ...
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

    def choisir_groupe(self, groupe: str, semaine: int, *, lundi: str = "") -> None:
        # La DATE, pas « S{semaine + 1} » : cet index+1 était trompeur, c'est
        # précisément la confusion que docs/MCP.md met en garde contre, et une
        # répétition qui affiche une semaine fausse ne sert à rien.
        self.actions.append(f"groupe({groupe}, {lundi or f'index {semaine}'})")

    def creer_seance(self, entree: EntreeCelcat) -> None:
        self.actions.append(f"creer({entree.session_id} {entree.heure_debut} {entree.salle})")

    def modifier_seance(self, entree: EntreeCelcat) -> None:
        self.actions.append(f"modifier({entree.session_id} {entree.heure_debut} {entree.salle})")

    def supprimer_seance(self, session_id: str) -> None:
        self.actions.append(f"supprimer({session_id})")

    def fermer(self) -> None:
        self.actions.append("fermeture")


class PilotePlaywright:
    """Vrai pilote, bâti sur les primitives de `navigateur.py`.

    CE QUI EST ACQUIS et implémenté ici : la connexion (base, rôle),
    l'ouverture d'un groupe par son nom Celcat, le choix de la semaine
    confirmé par son infobulle, les icônes de la barre du panneau, et le
    remplissage du formulaire par GLISSER-DÉPOSER depuis la liste de
    ressources — cette dernière étant l'apport de l'ancien autoclicker
    (`clickclick/robot01.js`), seul endroit où elle était consignée.

    CE QUI RESTE INCONNU : les LIBELLÉS des champs du formulaire. Il n'a
    jamais été ouvert (l'exploration du 01/09/2026 s'est arrêtée au clic sur
    `new`, qui crée déjà un événement). Ces libellés ne sont donc pas écrits
    en dur ici : ils vivent dans `data/config/celcat_formulaire.yaml`, et
    `creer_seance` REFUSE de cliquer tant qu'ils manquent. `relever_formulaire`
    est là pour les obtenir en une session supervisée.

    Rien n'est ancré sur des pixels. L'ancien autoclicker l'était, et c'est
    ce qui l'a rendu inutilisable dès le changement de machine : ses 23
    étapes ne valaient qu'en 2560×1440 à 75 % de zoom, sous macOS.
    """

    # Celcat de l'URCA (fourni le 31/08/2026). Surchargeable par `CELCAT_URL`
    # plutôt que figé : l'adresse d'un intranet change sans prévenir, et on ne
    # veut pas redéployer pour ça.
    URL_CONNEXION = os.environ.get("CELCAT_URL", "https://celcat-lv.univ-reims.fr/")

    # Celcat retrouve mal un enseignant par son PRÉNOM (constaté par
    # l'utilisateur le 31/08/2026 : « pour trouver un enseignant il faut
    # chercher par son nom d'abord »). La recherche se fait donc sur le NOM,
    # le prénom ne servant qu'à départager deux homonymes. Ne concerne que
    # les enseignants dont le code Celcat vaut « 0 » dans `celcat.yaml` :
    # pour les 80 autres, le code numérique évite toute recherche.
    CHERCHER_ENSEIGNANT_PAR = "nom"

    def __init__(
        self,
        rythme: Rythme,
        *,
        visible: bool = True,
        base: str | None = None,
        role: str | None = None,
        page=None,
        carte=None,
        config_dir=None,
        departement: str = "T_MMI",
    ) -> None:
        self.rythme = rythme
        # `visible=True` par défaut : sur un outil qui alimente la paie, on
        # veut pouvoir REGARDER ce qui se passe et reprendre la main.
        self.visible = visible
        # Base d'ENTRAÎNEMENT par défaut (`URCA_FORMATION`). Écrire pour la
        # première fois dans la base annuelle réelle doit être un choix
        # explicite, pas ce qui arrive quand on oublie un paramètre.
        self.base = base or nav.BASE_ENTRAINEMENT
        self.role = role or nav.ROLE_ECRITURE
        # Département Celcat des groupes MMI, cf. `celcat.yaml::groupes`.
        self.departement = departement
        if carte is not None:
            self.carte = carte
        elif config_dir is not None:
            self.carte = charger_carte(config_dir)
        else:
            self.carte = CarteFormulaire()
        # Page injectable : c'est le seul moyen de verrouiller la séquence du
        # formulaire par des tests. Celcat vit derrière un VPN et alimente la
        # paie, il ne sert pas de banc d'essai.
        self._page = page
        self._page_fournie = page is not None
        self._navigateur = None
        self._playwright = None
        # Trace lisible de ce qui a été fait. JAMAIS le mot de passe.
        self.actions: list[str] = []

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
            return False, "URL de connexion Celcat non renseignée (CELCAT_URL)."
        return True, ""

    # --- Session ---------------------------------------------------------

    def ouvrir_session(self, identifiant: str, mot_de_passe: str) -> None:
        if self._page is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._navigateur = self._playwright.chromium.launch(headless=not self.visible)
            # Le sélecteur de semaines vit vers y=855–1065 (relevé 1920×1080).
            # Le viewport Playwright par défaut (1280×720) le coupe : la
            # saisie lèverait « sélecteur introuvable » avant d'avoir rien
            # écrit — constaté le 01/09/2026 en headless Docker.
            self._page = self._navigateur.new_page(viewport={"width": 1920, "height": 1080})
        nav.connexion(
            self._page,
            base=self.base,
            role=self.role,
            identifiant=identifiant,
            mot_de_passe=mot_de_passe,
        )
        self.actions.append(f"connexion({identifiant}, {self.base}, {self.role})")

    def fermer(self) -> None:
        """Rendre la session AVANT de fermer le navigateur.

        Celcat garde les sessions ouvertes ; en enchaîner sans les rendre
        finit par saturer le serveur, qui cesse alors d'afficher la liste des
        bases (constaté le 31/08/2026). Ce n'est pas une politesse, c'est une
        condition pour que la saisie suivante démarre.
        """
        if self._page is not None:
            try:
                nav.deconnexion(self._page)
            except Exception:  # noqa: BLE001 — ne jamais masquer la vraie erreur
                self.actions.append("déconnexion impossible")
        if self._navigateur:
            self._navigateur.close()
        if self._playwright:
            self._playwright.stop()
        self.actions.append("fermeture")

    # --- Navigation ------------------------------------------------------

    def choisir_groupe(self, groupe: str, semaine: int, *, lundi: str = "") -> None:
        """Ouvre l'emploi du temps du groupe, sur la bonne semaine.

        `lundi` (ISO) est EXIGÉ : le sélecteur de semaines de Celcat
        s'identifie par ses dates, et l'index solveur n'y correspond pas — y
        envoyer `semaine + 1` est le piège classique (cf. docs/MCP.md).
        """
        if not lundi:
            raise ValueError(
                f"semaine {semaine} sans date de lundi : impossible de repérer la semaine "
                "dans Celcat sans risquer de saisir sur les mauvaises dates."
            )
        # `groupe` arrive déjà sous sa forme Celcat (« BUT MMI S2 TD AB »),
        # sans le suffixe d'année : une recherche sans lui retrouve le groupe
        # (vérifié le 31/08/2026), ce qui évite de deviner la cohorte.
        nom = groupe
        nav.ouvrir_ressource(self._page, nav.TYPE_GROUPES)
        nav.filtrer(self._page, nom)
        nav.double_cliquer_texte(self._page, nom)
        nav.attendre_texte(self._page, "Semaines de l'emploi du temps", delai=40)
        choisie = nav.choisir_semaine(self._page, dt.date.fromisoformat(lundi))
        self.actions.append(f"groupe({nom}, semaine du {lundi} -> {choisie['infobulle']})")

    # --- Formulaire ------------------------------------------------------

    def _champ(self, libelle: str) -> tuple[int, int]:
        """Position du champ désigné par ce libellé : juste EN DESSOUS.

        Relevé le 01/09/2026 sur l'inspecteur d'événement : « Jour: » en
        (952, 737) et sa valeur en (956, 770), « Heure: » en (1090, 737) et
        sa valeur en (1136, 770). Le champ est sous son libellé, à x presque
        inchangé.
        """
        cible = nav.trouver(self._page, libelle)
        if cible is None:
            raise LookupError(f"libellé « {libelle} » absent du formulaire à l'écran.")
        return cible["x"], cible["y"] + self.carte.decalage_champ_y

    def _remplacer_champ(self, libelle: str, valeur: str) -> None:
        """Vide un champ puis y écrit. Home + Maj-Fin sélectionne l'existant :
        un champ d'heure arrive prérempli, et taper par-dessus sans
        sélectionner donnerait « 08:0008:00 »."""
        x, y = self._champ(libelle)
        self._page.mouse.click(x, y)
        self._page.wait_for_timeout(200)
        self._page.keyboard.press("Home")
        self._page.keyboard.press("Shift+End")
        self._page.keyboard.type(valeur, delay=35)
        self._page.wait_for_timeout(200)

    def _choisir_jour(self, jour_celcat: int) -> None:
        """Déroulant trié lundi -> dimanche : Début, puis Bas, puis Entrée.

        Repris de l'ancien autoclicker, qui naviguait au clavier plutôt que
        de cliquer une ligne du déroulant — la position des lignes dépend de
        l'endroit où le déroulant s'ouvre, le clavier non.
        """
        x, y = self._champ(self.carte.jour)
        self._page.mouse.click(x, y)
        self._page.wait_for_timeout(300)
        self._page.keyboard.press("Home")
        for _ in range(max(0, jour_celcat - 1)):
            self._page.wait_for_timeout(80)
            self._page.keyboard.press("ArrowDown")
        self._page.wait_for_timeout(80)
        self._page.keyboard.press("Enter")
        self._page.wait_for_timeout(400)

    def _deposer(self, nom_champ: str, valeur: str) -> None:
        """Remplit un champ de ressource par glisser-déposer.

        C'est ainsi que ce formulaire se remplit — on ne tape pas dedans, on
        y dépose une ligne prise dans la liste de gauche. Le savoir vient de
        l'ancien autoclicker, qui procède ainsi pour les cinq champs.
        """
        nav.ouvrir_ressource(self._page, self.carte.ressource_du_champ(nom_champ))
        nav.filtrer(self._page, valeur)
        ligne = nav.premiere_ligne(self._page, valeur)
        arrivee = self._champ(self.carte.libelle_champ(nom_champ))
        nav.glisser_deposer(self._page, (ligne["x"], ligne["y"]), arrivee)
        self.rythme.apres_action()

    def creer_seance(self, entree: EntreeCelcat) -> None:
        # Contrôles AVANT tout clic. Un formulaire ouvert puis abandonné à
        # moitié rempli laisse un événement fantôme dans Celcat — c'est
        # exactement l'incident du 01/09/2026.
        if not entree.prete:
            raise ValueError(
                f"séance {entree.session_id} bloquée ({'; '.join(entree.bloquants)}) : "
                "rien n'a été écrit dans Celcat."
            )
        self.carte.exiger_complete()
        libelle_categorie = self.carte.categorie(entree.type_seance_nom)

        # Un inspecteur déjà ouvert (double-clic sur 1933212) n'est PAS une
        # création : on le ferme avant de sélectionner une case vide et `new`.
        if nav.trouver(self._page, "Evénement (ID"):
            nav.cliquer_icone_barre(self._page, "annuler")
            self.actions.append("fermer-inspecteur-existant")

        case = nav.cliquer_case_vide(self._page)
        self.actions.append(f"case_vide({case['jour']} {case['heure']} @{case['x']},{case['y']})")
        nav.cliquer_icone_barre(
            self._page, "creer", infobulle="Créer un nouvel événement",
        )
        try:
            # Conflits à gauche n'est PAS un échec : `new` coche 54 semaines
            # et Celcat signale des chevauchements. L'inspecteur (Détails)
            # reste le formulaire à remplir — l'ancien clicker n'attend pas
            # que Conflits disparaisse. En 1920×1080, Conflits remplace le
            # panneau de gauche et l'inspecteur n'apparaît qu'après : on
            # referme Conflits d'abord, puis on resélectionne l'événement.
            self._page.wait_for_timeout(1500)
            nav.fermer_panneau_conflits(self._page)
            if nav.trouver(self._page, self.carte.onglet_details, exact=True) is None:
                nav.cliquer_case_vide(self._page)
            nav.attendre_texte(self._page, self.carte.onglet_details, delai=20)
            nav.onglet(self._page, self.carte.onglet_details)
            self._choisir_jour(entree.jour)
            nav.saisir_horaire(
                self._page, entree.heure_debut, entree.heure_fin,
                champ_heure=self.carte.heure, dy=self.carte.decalage_champ_y,
            )
            if self.carte.validation_horaire:
                nav.cliquer_texte(self._page, self.carte.validation_horaire, exact=True)
            self._deposer("categorie", libelle_categorie)
            self._deposer("departement", self.departement)

            nav.onglet(self._page, self.carte.onglet_ressources)
            self._deposer("enseignant", entree.code_enseignant or "")
            self._deposer("salle", entree.salle or "")
            self._deposer("matiere", entree.code_module or "")

            # `new` coche les 54 semaines par défaut (incident du 01/09/2026).
            # On restreint à la semaine du lundi visé, puis on n'enregistre
            # que si le formulaire n'en porte qu'UNE.
            if entree.lundi:
                nav.restreindre_semaines_formulaire(
                    self._page, dt.date.fromisoformat(entree.lundi),
                )
            n_semaines = nav.nombre_semaines_formulaire(self._page)
            if n_semaines != 1:
                detail = "un nombre inconnu" if n_semaines is None else str(n_semaines)
                raise SemainesNonRestreintes(
                    f"le formulaire porte {detail} semaine(s) : enregistrer "
                    "recopierait la séance sur l'année (incident du 01/09/2026). "
                    "Rien n'a été enregistré."
                )

            nav.cliquer_icone_barre(self._page, "enregistrer")
        except Exception:
            try:
                vus = [f["texte"] for f in nav.feuilles(self._page) if f.get("texte")][:60]
                self.actions.append("ecran(" + ", ".join(vus) + ")")
            except Exception:  # noqa: BLE001
                pass
            try:
                os.makedirs("data/releves", exist_ok=True)
                if hasattr(self._page, "screenshot"):
                    self._page.screenshot(
                        path="data/releves/echec-saisie.png", full_page=True,
                    )
            except Exception:  # noqa: BLE001
                pass
            try:
                if nav.trouver(self._page, "Sélectionner les heures") or nav.trouver(
                    self._page, "Heure de début"
                ):
                    nav.cliquer_texte(self._page, "Annuler", exact=True)
            except Exception:  # noqa: BLE001
                pass
            try:
                nav.cliquer_icone_barre(self._page, "annuler")
                self.actions.append(f"annuler({entree.session_id})")
            except Exception:  # noqa: BLE001 — l'erreur utile est celle du remplissage
                self.actions.append(f"annulation impossible({entree.session_id})")
            raise
        self.actions.append(
            f"creer({entree.session_id} {entree.heure_debut} {entree.salle} {libelle_categorie})"
        )

    def modifier_seance(self, entree: EntreeCelcat) -> None:
        """Non disponible, et c'est délibéré.

        Modifier suppose de RETROUVER l'événement existant dans la grille.
        Notre journal ne retient que notre `session_id`, pas l'`event_id`
        Celcat, et rien de ce qui a été relevé ne permet de désigner un
        événement à coup sûr — plusieurs peuvent se superposer sur la même
        case (« Événement 1 de 2 », constaté le 01/09/2026 par-dessus un jour
        férié protégé).

        `SaisieCelcat` enregistre cet échec pour la séance concernée et
        continue les suivantes : la saisie n'est pas bloquée, la séance est
        simplement à reprendre à la main, et on le sait.
        """
        raise FormulaireNonReleve(
            f"modification de {entree.session_id} impossible : retrouver un événement "
            "existant dans Celcat n'est pas encore établi (aucun event_id dans notre "
            "journal, et des événements peuvent se superposer sur une même case). "
            "À corriger à la main dans Celcat. Rien n'a été écrit."
        )

    def supprimer_seance(self, session_id: str) -> None:
        """Non disponible, même raison que `modifier_seance` — avec un risque
        supplémentaire : la case visée peut porter un jour férié PROTÉGÉ
        par-dessus lequel notre événement s'est glissé (01/09/2026). Une
        suppression au mauvais endroit détruirait une donnée qui n'est pas à
        nous."""
        raise FormulaireNonReleve(
            f"suppression de {session_id} impossible : désigner l'événement à supprimer "
            "n'est pas encore établi, et un jour férié protégé peut occuper la même "
            "case. À faire à la main dans Celcat. Rien n'a été supprimé."
        )

    # --- Relevé ----------------------------------------------------------

    def relever_formulaire(self) -> dict:
        """Vide à l'écran tout ce qui permet de compléter la carte.

        C'est le remplacement de la devinette : au lieu d'écrire des libellés
        au jugé dans le code, on ouvre le formulaire UNE fois, en base
        d'entraînement, et on lit ce qu'il contient réellement.

        À appeler après avoir ouvert un groupe et cliqué l'icône `creer`.
        Ne clique rien, n'écrit rien : pure lecture.
        """
        releve = {
            "textes": nav.feuilles(self._page),
            "champs": nav.champs_saisie(self._page),
            "icones": {nom: nav.icones_barre(self._page, nom) for nom in nav.IMAGES_BARRE},
        }
        self.actions.append(
            f"relevé({len(releve['textes'])} textes, {len(releve['champs'])} champs)"
        )
        return releve


class AccesPerdu(RuntimeError):
    """Celcat est devenu injoignable — typiquement le VPN qui tombe.

    Distinct d'un échec de séance : celui-ci est isolé et n'arrête rien,
    celui-là invalide tout ce qui suivrait.
    """


class SemainesNonRestreintes(ValueError):
    """Le formulaire d'événement n'est pas calé sur une seule semaine.

    Enregistrer dans cet état recopierait la séance sur l'année (54 Y,
    incident du 01/09/2026). Toute la saisie s'arrête : les suivantes
    auraient le même défaut.
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

    def executer(
        self, plan, identifiant: str, mot_de_passe: str, *,
        doit_continuer=None, ignorer_bloquees: bool = False,
    ) -> ResultatSaisie:
        """`doit_continuer` : fonction sans argument rendant False pour
        arrêter proprement (bouton « stop » de l'interface). Vérifiée entre
        chaque séance — jamais au milieu d'un formulaire à moitié rempli.

        `ignorer_bloquees` : les séances sans code Celcat (enseignant « 0 »,
        module manquant…) restent hors du lot, mais n'empêchent plus les
        autres de partir. Décision utilisateur du 01/09/2026.
        """
        resultat = ResultatSaisie()
        if plan.bloquees and not ignorer_bloquees:
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
                # Le pilote reçoit le nom CELCAT du groupe et la DATE du
                # lundi, pas notre libellé ni l'index solveur : les entrées
                # d'un même lot partagent semestre et semaine par
                # construction, la première fait donc référence.
                self.pilote.choisir_groupe(groupe, semaine, lundi=entrees[0].lundi)
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
                    except SemainesNonRestreintes as exc:
                        resultat.echecs.append((entree.session_id, str(exc)))
                        resultat.interrompu = True
                        return resultat
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
    """Regroupe par nom Celcat du groupe + semaine.

    « TD AB » tout court fusionnerait S1 et S5 sur le même onglet — les
    séances S5 partiraient sur l'emploi du temps S1. La clé est donc
    `nom_groupe_celcat` (« BUT MMI S1 TD AB »).
    """
    par_cle: dict[tuple[str, int], list[EntreeCelcat]] = {}
    for e in entrees:
        par_cle.setdefault((e.nom_groupe_celcat, e.semaine), []).append(e)
    for cle in sorted(par_cle):
        yield cle, sorted(par_cle[cle], key=lambda e: (e.jour, e.heure_debut))
