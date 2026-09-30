"""Pièces jointes IMAGE des tâches du kanban (30/09/2026, demande utilisateur :
« dans les tâches, ajoute la possibilité de mettre des images » — cas d'usage
principal : coller une capture d'écran avec Ctrl V).

Ce module ne connaît ni la base ni HTTP : il VÉRIFIE un contenu, le NETTOIE
de ses métadonnées et le RANGE sur le disque. Les routes sont dans
`api/main.py` (`/taches/{id}/images…`) et `api/v1.py` (lecture), les
métadonnées dans la table `taches_images` (`db/models.py::TacheImage`).

SÉCURITÉ
- Types acceptés : PNG, JPEG, WebP, GIF — reconnus sur les OCTETS (signature
  puis parcours complet de la structure du fichier), jamais sur l'extension
  ni sur le `Content-Type` annoncé par le navigateur. SVG refusé (c'est du
  XML qui peut porter du script), comme tout ce qui n'a pas l'une des quatre
  signatures (HTML renommé en `.png`, etc.).
- Le fichier est RÉÉCRIT à partir de sa structure : ce qui suit la fin
  d'image (données collées après `IEND`, après la fin du JPEG, après le
  `;` du GIF, hors du conteneur RIFF) disparaît, ce qui neutralise les
  fichiers « polyglottes ».
- Métadonnées retirées (localisation GPS d'une photo de téléphone, auteur,
  logiciel, commentaires) : EXIF et XMP partout, textes PNG, blocs IPTC et
  commentaires JPEG, commentaires GIF. L'orientation EXIF d'un JPEG est la
  seule information conservée (sinon une photo prise en portrait
  s'afficherait couchée) : elle est réécrite seule dans un bloc EXIF minimal.
  Fait en Python pur, sans Pillow : Pillow n'est pas une dépendance du projet
  (présent dans le venv de développement seulement), et ré-encoder aurait
  dégradé les JPEG et cassé les GIF animés. Rien n'est décodé côté serveur.
- Nom stocké sur le disque = `uuid4().hex` + extension du type RÉEL. Le nom
  d'origine n'est jamais utilisé dans un chemin ; il n'est gardé (nettoyé) que
  pour l'affichage et l'en-tête `Content-Disposition`.

STOCKAGE : `data/state/pieces_jointes/taches/<id_tache>/<uuid>.<ext>`, donc
dans le VOLUME persistant (`cal-iut-data` monté sur `/app/data/state`, cf.
`docker-compose.yml`). Jamais commité (`.gitignore`).

SAUVEGARDES : les fichiers NE SONT PAS dans les sauvegardes de l'appli —
ni l'instantané JSON (`api/sauvegardes.py`, placements seulement), ni la
copie quotidienne de la base (`api/sauvegardes_db.py`), qui contient la
table `taches_images` (les métadonnées) mais pas les octets. Une base
restaurée peut donc citer des images absentes du disque : la route de
lecture répond alors 404 et l'interface affiche une vignette « image
indisponible ». Seule une sauvegarde du volume (Dokploy) couvre les fichiers.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import struct
import threading
import unicodedata
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

logger = logging.getLogger(__name__)

STATE_DIR = Path(__file__).resolve().parents[3] / "data" / "state"

# ── Limites (documentées dans GUIDE.md, « Joindre des images ») ────────────
#
# 8 Mo par image : une capture d'écran pleine page en 4K fait 2 à 5 Mo en
# PNG, une photo de téléphone 2 à 6 Mo en JPEG. Au-delà, c'est presque
# toujours une erreur (vidéo exportée en GIF, scan non compressé).
TAILLE_MAX_IMAGE = 8 * 1024 * 1024
# Dix images et 40 Mo par tâche : une carte de kanban n'est pas un album.
MAX_IMAGES_PAR_TACHE = 10
TAILLE_MAX_TOTALE_PAR_TACHE = 40 * 1024 * 1024
# Garde-fou « bombe de décompression » : quelques Ko de PNG peuvent annoncer
# 50 000 × 50 000 pixels, que le NAVIGATEUR de chaque lecteur devrait ensuite
# décoder (≈ 10 Go de mémoire). 80 Mpx couvre toute photo de téléphone.
MAX_COTE_PX = 20_000
MAX_PIXELS = 80_000_000
# Corps de requête accepté par `POST /taches/{id}/images` : l'image plus les
# en-têtes et délimiteurs du multipart. `frontend/nginx.conf.template` règle
# `client_max_body_size` à 9m sur CETTE route seulement (1m partout ailleurs).
MARGE_MULTIPART = 64 * 1024
TAILLE_MAX_REQUETE = TAILLE_MAX_IMAGE + MARGE_MULTIPART
NOM_MAX = 120

EXTENSIONS: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}
TYPES_ACCEPTES = frozenset(EXTENSIONS)
_FICHIER_VALIDE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp|gif)$")

# Un seul processus uvicorn sert l'API (cf. Dockerfile) : ce verrou suffit à
# empêcher deux envois simultanés sur la même tâche de dépasser ensemble les
# plafonds (lecture du compte puis insertion).
verrou = threading.Lock()


class ImageRefusee(Exception):
    """Contenu refusé — `statut` est le code HTTP à renvoyer."""

    def __init__(self, message: str, statut: int = 415) -> None:
        super().__init__(message)
        self.message = message
        self.statut = statut


@dataclass(frozen=True)
class ImageAnalysee:
    type_mime: str
    extension: str
    largeur: int
    hauteur: int
    contenu: bytes  # déjà nettoyé de ses métadonnées


def libelle_taille(octets: int) -> str:
    return f"{octets / (1024 * 1024):g} Mo"


_MESSAGE_FORMAT = "Format non accepté : PNG, JPEG, WebP ou GIF uniquement (SVG refusé)."


def _abime(format_: str) -> ImageRefusee:
    return ImageRefusee(f"Fichier {format_} illisible ou tronqué.", 422)


# ── PNG ─────────────────────────────────────────────────────────────────

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Blocs de texte et de métadonnées : jamais nécessaires à l'affichage.
_PNG_RETIRES = frozenset({b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"})


def _png(data: bytes) -> tuple[int, int, bytes]:
    pos = len(_PNG_SIGNATURE)
    sortie = [_PNG_SIGNATURE]
    largeur = hauteur = None
    while True:
        if pos + 12 > len(data):
            raise _abime("PNG")
        longueur = struct.unpack(">I", data[pos : pos + 4])[0]
        type_ = data[pos + 4 : pos + 8]
        fin = pos + 12 + longueur
        if longueur > 0x7FFFFFFF or fin > len(data) or not type_.isalpha():
            raise _abime("PNG")
        crc = struct.unpack(">I", data[fin - 4 : fin])[0]
        if zlib.crc32(data[pos + 4 : fin - 4]) & 0xFFFFFFFF != crc:
            raise _abime("PNG")
        if largeur is None:
            if type_ != b"IHDR" or longueur != 13:
                raise _abime("PNG")
            largeur, hauteur = struct.unpack(">II", data[pos + 8 : pos + 16])
        if type_ not in _PNG_RETIRES:
            sortie.append(data[pos:fin])
        pos = fin
        if type_ == b"IEND":
            break
    assert hauteur is not None
    return largeur, hauteur, b"".join(sortie)


# ── JPEG ────────────────────────────────────────────────────────────────

# Marqueurs « début de trame » qui portent les dimensions (hors DHT C4,
# JPG C8, DAC CC).
_JPEG_SOF = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})


def _orientation_exif(tiff: bytes) -> int:
    """Valeur de la balise Orientation (0x0112) de l'IFD0, 1 à défaut."""
    try:
        if tiff[:2] == b"II":
            boutisme = "<"
        elif tiff[:2] == b"MM":
            boutisme = ">"
        else:
            return 1
        if struct.unpack(boutisme + "H", tiff[2:4])[0] != 42:
            return 1
        ifd = struct.unpack(boutisme + "I", tiff[4:8])[0]
        nombre = struct.unpack(boutisme + "H", tiff[ifd : ifd + 2])[0]
        for k in range(min(nombre, 512)):
            entree = ifd + 2 + 12 * k
            balise, type_, _compte = struct.unpack(boutisme + "HHI", tiff[entree : entree + 8])
            if balise == 0x0112 and type_ == 3:
                valeur = struct.unpack(boutisme + "H", tiff[entree + 8 : entree + 10])[0]
                return valeur if 1 <= valeur <= 8 else 1
    except struct.error:
        return 1
    return 1


def _app1_orientation(orientation: int) -> bytes:
    """Bloc EXIF minimal : l'orientation, rien d'autre."""
    tiff = (
        b"MM\x00\x2a\x00\x00\x00\x08"  # en-tête TIFF gros-boutiste, IFD0 à 8
        + b"\x00\x01"  # une entrée
        + struct.pack(">HHIHH", 0x0112, 3, 1, orientation, 0)
        + b"\x00\x00\x00\x00"  # pas d'IFD suivant
    )
    corps = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(corps) + 2) + corps


def _segment_jpeg_garde(marqueur: int, segment: bytes) -> bool:
    if marqueur == 0xE1:  # EXIF, XMP
        return False
    if marqueur == 0xE2:  # ICC gardé (couleurs) ; MPF = images secondaires
        return segment[4:8] != b"MPF\x00"
    if 0xE3 <= marqueur <= 0xED or marqueur == 0xEF:  # APP3…APP13 (IPTC), APP15
        return False
    return marqueur != 0xFE  # COM : commentaire libre


def _jpeg(data: bytes) -> tuple[int, int, bytes]:
    n = len(data)
    pos = 2
    sortie = [b"\xff\xd8"]
    largeur = hauteur = None
    orientation = 1
    scan_vu = False
    while True:
        if pos + 2 > n or data[pos] != 0xFF:
            raise _abime("JPEG")
        marqueur = data[pos + 1]
        if marqueur == 0xFF:  # octet de remplissage
            pos += 1
            continue
        if marqueur == 0xD9:  # fin d'image : tout ce qui suit est ignoré
            if not scan_vu or largeur is None:
                raise _abime("JPEG")
            sortie.append(b"\xff\xd9")
            break
        if marqueur == 0x01 or 0xD0 <= marqueur <= 0xD7:
            sortie.append(data[pos : pos + 2])
            pos += 2
            continue
        if pos + 4 > n:
            raise _abime("JPEG")
        longueur = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        fin = pos + 2 + longueur
        if longueur < 2 or fin > n:
            raise _abime("JPEG")
        segment = data[pos:fin]
        if marqueur in _JPEG_SOF:
            if longueur < 8:
                raise _abime("JPEG")
            hauteur, largeur = struct.unpack(">HH", data[pos + 5 : pos + 9])
        if marqueur == 0xE1 and segment[4:10] == b"Exif\x00\x00":
            orientation = _orientation_exif(segment[10:])
        if _segment_jpeg_garde(marqueur, segment):
            sortie.append(segment)
        pos = fin
        if marqueur == 0xDA:
            # Données compressées : un 0xFF y est suivi de 0x00 (échappement)
            # ou d'un RSTn ; tout autre octet ouvre le marqueur suivant (autre
            # passe d'un JPEG progressif, ou la fin d'image).
            scan_vu = True
            i = pos
            while True:
                j = data.find(b"\xff", i)
                if j < 0 or j + 1 >= n:
                    raise _abime("JPEG")
                suivant = data[j + 1]
                if suivant == 0x00 or 0xD0 <= suivant <= 0xD7:
                    i = j + 2
                    continue
                if suivant == 0xFF:
                    i = j + 1
                    continue
                sortie.append(data[pos:j])
                pos = j
                break
    if largeur is None or hauteur is None:
        raise _abime("JPEG")
    if orientation != 1:
        # Après le bloc JFIF s'il existe (il doit rester le premier).
        index = 2 if len(sortie) > 1 and sortie[1][:2] == b"\xff\xe0" else 1
        sortie.insert(index, _app1_orientation(orientation))
        if orientation >= 5:  # rotation d'un quart de tour : affichée couchée
            largeur, hauteur = hauteur, largeur
    return largeur, hauteur, b"".join(sortie)


# ── GIF ─────────────────────────────────────────────────────────────────

# Extensions d'application gardées : la boucle d'animation, rien d'autre
# (XMP et autres blocs de logiciel retirés).
_GIF_APPLICATIONS_GARDEES = frozenset({b"NETSCAPE2.0", b"ANIMEXTS1.0"})


def _gif_sous_blocs(data: bytes, pos: int) -> int:
    """Position juste après la suite de sous-blocs qui commence à `pos`."""
    while True:
        if pos >= len(data):
            raise _abime("GIF")
        taille = data[pos]
        pos += 1
        if taille == 0:
            return pos
        pos += taille


def _gif(data: bytes) -> tuple[int, int, bytes]:
    if len(data) < 13:
        raise _abime("GIF")
    largeur, hauteur, drapeaux = struct.unpack("<HHB", data[6:11])
    pos = 13
    if drapeaux & 0x80:
        pos += 3 * (2 ** ((drapeaux & 0x07) + 1))
    if pos > len(data):
        raise _abime("GIF")
    sortie = [data[:pos]]
    images = 0
    while True:
        if pos >= len(data):
            raise _abime("GIF")
        octet = data[pos]
        if octet == 0x3B:  # fin : tout ce qui suit est ignoré
            sortie.append(b"\x3b")
            break
        if octet == 0x2C:  # image
            if pos + 11 > len(data):
                raise _abime("GIF")
            local = data[pos + 9]
            fin = pos + 10
            if local & 0x80:
                fin += 3 * (2 ** ((local & 0x07) + 1))
            fin = _gif_sous_blocs(data, fin + 1)  # +1 : taille de code LZW
            sortie.append(data[pos:fin])
            images += 1
            pos = fin
        elif octet == 0x21:  # extension
            if pos + 2 > len(data):
                raise _abime("GIF")
            etiquette = data[pos + 1]
            fin = _gif_sous_blocs(data, pos + 2)
            if etiquette == 0xFE:  # commentaire
                garder = False
            elif etiquette == 0xFF:
                garder = data[pos + 2] == 11 and data[pos + 3 : pos + 14] in _GIF_APPLICATIONS_GARDEES
            else:
                garder = True
            if garder:
                sortie.append(data[pos:fin])
            pos = fin
        else:
            raise _abime("GIF")
    if images == 0:
        raise _abime("GIF")
    return largeur, hauteur, b"".join(sortie)


# ── WebP ────────────────────────────────────────────────────────────────


def _webp(data: bytes) -> tuple[int, int, bytes]:
    if len(data) < 20:
        raise _abime("WebP")
    taille_riff = struct.unpack("<I", data[4:8])[0]
    fin_riff = 8 + taille_riff
    if taille_riff < 12 or fin_riff > len(data):
        raise _abime("WebP")
    pos = 12
    blocs: list[bytearray] = []
    premier: bytes | None = None
    largeur = hauteur = None
    image_vue = False
    while pos + 8 <= fin_riff:
        fourcc = data[pos : pos + 4]
        taille = struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        fin_donnees = pos + 8 + taille
        if fin_donnees > fin_riff:
            raise _abime("WebP")
        corps = data[pos + 8 : fin_donnees]
        if premier is None:
            premier = fourcc
        if fourcc == b"VP8X":
            if taille < 10:
                raise _abime("WebP")
            largeur = 1 + int.from_bytes(corps[4:7], "little")
            hauteur = 1 + int.from_bytes(corps[7:10], "little")
        elif fourcc == b"VP8 ":
            if taille < 10 or corps[3:6] != b"\x9d\x01\x2a":
                raise _abime("WebP")
            image_vue = True
            if largeur is None:
                w, h = struct.unpack("<HH", corps[6:10])
                largeur, hauteur = w & 0x3FFF, h & 0x3FFF
        elif fourcc == b"VP8L":
            if taille < 5 or corps[0] != 0x2F:
                raise _abime("WebP")
            image_vue = True
            if largeur is None:
                bits = int.from_bytes(corps[1:5], "little")
                largeur, hauteur = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        elif fourcc == b"ANMF":
            image_vue = True
        if fourcc not in (b"EXIF", b"XMP "):
            bloc = bytearray(data[pos:fin_donnees])
            if taille & 1:
                bloc.append(0)  # bourrage : chaque bloc a une taille paire
            blocs.append(bloc)
        pos = fin_donnees + (taille & 1)
    if premier not in (b"VP8 ", b"VP8L", b"VP8X") or not image_vue or largeur is None:
        raise _abime("WebP")
    if premier == b"VP8X":
        blocs[0][8] &= ~(0x08 | 0x04) & 0xFF  # drapeaux EXIF et XMP retirés
    corps_riff = b"WEBP" + b"".join(bytes(b) for b in blocs)
    return largeur, hauteur, b"RIFF" + struct.pack("<I", len(corps_riff)) + corps_riff


# ── Point d'entrée ──────────────────────────────────────────────────────


def type_reel(contenu: bytes) -> str | None:
    """Type MIME reconnu à la signature, `None` sinon (SVG, HTML, PDF…)."""
    if contenu.startswith(_PNG_SIGNATURE):
        return "image/png"
    if contenu.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contenu[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if contenu[:4] == b"RIFF" and contenu[8:12] == b"WEBP":
        return "image/webp"
    return None


_ANALYSEURS = {"image/png": _png, "image/jpeg": _jpeg, "image/gif": _gif, "image/webp": _webp}


def analyser(contenu: bytes) -> ImageAnalysee:
    """Vérifie `contenu` et le rend nettoyé ; lève `ImageRefusee` sinon."""
    if not contenu:
        raise ImageRefusee("Fichier vide.", 422)
    if len(contenu) > TAILLE_MAX_IMAGE:
        raise ImageRefusee(f"Image trop lourde : {libelle_taille(TAILLE_MAX_IMAGE)} au maximum.", 413)
    type_mime = type_reel(contenu)
    if type_mime is None:
        raise ImageRefusee(_MESSAGE_FORMAT, 415)
    try:
        largeur, hauteur, nettoye = _ANALYSEURS[type_mime](contenu)
    except (struct.error, IndexError, ValueError) as exc:
        raise _abime(type_mime.split("/")[1].upper()) from exc
    if largeur <= 0 or hauteur <= 0:
        raise _abime(type_mime.split("/")[1].upper())
    if largeur > MAX_COTE_PX or hauteur > MAX_COTE_PX or largeur * hauteur > MAX_PIXELS:
        raise ImageRefusee(
            f"Image trop grande ({largeur} × {hauteur} pixels) : {MAX_COTE_PX} pixels de côté "
            f"et {MAX_PIXELS // 1_000_000} millions de pixels au maximum.",
            413,
        )
    return ImageAnalysee(
        type_mime=type_mime, extension=EXTENSIONS[type_mime], largeur=largeur, hauteur=hauteur, contenu=nettoye
    )


# ── Noms ────────────────────────────────────────────────────────────────


def nom_affichable(nom_client: str | None, extension: str) -> str:
    """Nom d'origine réduit à son dernier composant, sans caractère de
    contrôle ni de mise en forme (inversion bidirectionnelle, etc.), avec
    l'extension du type RÉEL. Jamais utilisé dans un chemin."""
    # Les navigateurs (norme WHATWG) écrivent `"` en `%22` dans le nom d'un
    # fichier envoyé en multipart ; `%0A`/`%0D` (sauts de ligne) sont retirés.
    nom = (nom_client or "").replace("%22", '"').replace("%0A", "").replace("%0D", "")
    nom = nom.replace("\\", "/").rsplit("/", 1)[-1]
    nom = unicodedata.normalize("NFC", nom)
    nom = "".join(c for c in nom if not unicodedata.category(c).startswith(("C", "Z")) or c == " ")
    nom = nom.strip().strip(".")
    base = nom.rsplit(".", 1)[0].strip() if "." in nom else nom
    base = base[:NOM_MAX].strip() or "image"
    return f"{base}.{extension}"


def content_disposition(nom: str) -> str:
    """`inline` + nom échappé : une version ASCII sûre, et le nom exact en
    `filename*` (RFC 6266 / 5987), encodé en pourcentages."""
    ascii_ = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode("ascii")
    ascii_ = re.sub(r"[^A-Za-z0-9._ -]", "_", ascii_).strip() or "image"
    return f"inline; filename=\"{ascii_}\"; filename*=UTF-8''{quote(nom, safe='')}"


# ── Disque ──────────────────────────────────────────────────────────────


def _racine() -> Path:
    """Point d'injection des tests (cf. `tests/conftest.py`)."""
    return STATE_DIR / "pieces_jointes" / "taches"


def dossier_tache(tache_id: int) -> Path:
    return _racine() / str(int(tache_id))


def chemin(tache_id: int, fichier: str) -> Path:
    """Chemin d'un fichier stocké — `fichier` doit être un nom généré par
    `ecrire` (uuid hexadécimal + extension connue), sinon `ValueError`."""
    if not _FICHIER_VALIDE.match(fichier or ""):
        raise ValueError(f"Nom de fichier stocké invalide : {fichier!r}")
    return dossier_tache(tache_id) / fichier


def ecrire(tache_id: int, contenu: bytes, extension: str) -> str:
    """Écrit `contenu` sous un nom neuf (écriture atomique), rend ce nom."""
    fichier = f"{uuid.uuid4().hex}.{extension}"
    cible = chemin(tache_id, fichier)
    cible.parent.mkdir(parents=True, exist_ok=True)
    temporaire = cible.with_name(cible.name + ".tmp")
    try:
        temporaire.write_bytes(contenu)
        os.replace(temporaire, cible)
    finally:
        temporaire.unlink(missing_ok=True)
    return fichier


def supprimer(tache_id: int, fichier: str) -> None:
    try:
        chemin(tache_id, fichier).unlink(missing_ok=True)
    except (OSError, ValueError):
        logger.exception("pièce jointe : fichier %s de la tâche %s non supprimé", fichier, tache_id)


def supprimer_dossier(tache_id: int) -> None:
    """Tout le dossier d'une tâche (suppression de la tâche)."""
    dossier = dossier_tache(tache_id)
    if not dossier.exists():
        return
    try:
        shutil.rmtree(dossier)
    except OSError:
        logger.exception("pièces jointes : dossier de la tâche %s non supprimé", tache_id)
