"""Images jointes aux tâches du kanban (30/09/2026, demande utilisateur :
« dans les tâches, ajoute la possibilité de mettre des images »).

Couvre `api/pieces_jointes.py` (types reconnus sur les octets, nettoyage des
métadonnées, limites, noms) et les routes `/taches/{id}/images…` d'`api/
main.py` et `/api/v1/taches/{id}/images/{image_id}` d'`api/v1.py` : droits
(ceux des tâches), en-têtes de réponse, nettoyage du disque, anti-aspiration.

Fichiers de test JPEG / WebP / GIF générés une fois avec Pillow (non requis
pour lancer ces tests) : 4 × 3 pixels, avec EXIF (orientation, fabricant,
coordonnées GPS), XMP et commentaires marqués « SECRET- », qui ne doivent
jamais ressortir du serveur.
"""

from __future__ import annotations

import base64
import struct
import uuid
import zlib

import pytest
from conftest import creer_compte_actif_et_connecter
from fastapi.testclient import TestClient

from cal_iut.api import accounts, pieces_jointes
from cal_iut.api.main import app

MDP = "Motdepasse123"

_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/4QCyRXhpZgAATU0AKgAAAAgAAwEPAAIAAAARAAAAMgESAAMAAAABAAYAAIglAAQAAAAB"
    "AAAARAAAAABTRUNSRVQtRkFCUklDQU5UAAAABAABAAIAAAACTgAAAAACAAUAAAADAAAAegADAAIAAAACRQAAAAAEAAUAAAAD"
    "AAAAkgAAAAAAAAAwAAAAAQAAABEAAAABAAAAHgAAAAEAAAAEAAAAAQAAAAQAAAABAAAAAAAAAAH//gAUU0VDUkVULUNPTU1F"
    "TlRBSVJF/9sAQwAQCwwODAoQDg0OEhEQExgoGhgWFhgxIyUdKDozPTw5Mzg3QEhcTkBEV0U3OFBtUVdfYmdoZz5NcXlwZHhc"
    "ZWdj/9sAQwEREhIYFRgvGhovY0I4QmNjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2Nj"
    "/8AAEQgAAwAEAwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAAB"
    "fQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldY"
    "WVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh"
    "4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAEC"
    "dwABAgMRBAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNUVVZX"
    "WFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ"
    "2uLj5OXm5+jp6vLz9PX29/j5+v/aAAwDAQACEQMRAD8Ax6KKK4T6g//Z"
)
_WEBP_B64 = (
    "UklGRhgBAABXRUJQVlA4WAoAAAAMAAAAAwAAAgAAVlA4IC4AAACwAQCdASoEAAMAAUAmJaACdLoABDAAAP7x3I/4DdfFtMv/"
    "vYL/3YL/3YL/WwAARVhJRqoAAABNTQAqAAAACAADAQ8AAgAAABEAAAAyARIAAwAAAAEAAQAAiCUABAAAAAEAAABEAAAAAFNF"
    "Q1JFVC1GQUJSSUNBTlQAAAAEAAEAAgAAAAJOAAAAAAIABQAAAAMAAAB6AAMAAgAAAAJFAAAAAAQABQAAAAMAAACSAAAAAAAA"
    "ADAAAAABAAAAEQAAAAEAAAAeAAAAAQAAAAQAAAABAAAABAAAAAEAAAAAAAAAAVhNUCARAAAAPHg+U0VDUkVULVhNUDwveD4A"
)
_GIF_B64 = (
    "R0lGODlhAgACAIAAAAAAAAAAACH/C05FVFNDQVBFMi4wAwEAAAAh/gpTRUNSRVQtR0lGACwAAAAAAgACAAAIBgABCAQQEAA7"
)

JPEG = base64.b64decode("".join(_JPEG_B64))
WEBP = base64.b64decode("".join(_WEBP_B64))
GIF = base64.b64decode("".join(_GIF_B64))


def _bloc_png(type_: bytes, corps: bytes) -> bytes:
    return struct.pack(">I", len(corps)) + type_ + corps + struct.pack(">I", zlib.crc32(type_ + corps) & 0xFFFFFFFF)


def png(largeur: int = 3, hauteur: int = 2, *, texte: bytes | None = b"Author\x00SECRET-AUTEUR") -> bytes:
    lignes = b"".join(b"\x00" + b"\xff\x00\x00" * largeur for _ in range(min(hauteur, 4)))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _bloc_png(b"IHDR", struct.pack(">IIBBBBB", largeur, hauteur, 8, 2, 0, 0, 0))
        + (_bloc_png(b"tEXt", texte) if texte else b"")
        + _bloc_png(b"IDAT", zlib.compress(lignes))
        + _bloc_png(b"IEND", b"")
    )


SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(document.cookie)</script></svg>'
HTML = b"<!doctype html><html><body><script>alert(document.cookie)</script></body></html>"


# ── Outils ──────────────────────────────────────────────────────────────


def _client(role: str = "edit") -> TestClient:
    client = TestClient(app, raise_server_exceptions=False)
    creer_compte_actif_et_connecter(client, role=role)
    return client


def _tache(client: TestClient, titre: str = "Salle B012 sans vidéoprojecteur") -> int:
    r = client.post("/taches", json={"titre": titre})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _envoyer(client: TestClient, tache_id: int, contenu: bytes, nom: str = "capture.png", type_: str = "image/png", **kw):
    return client.post(f"/taches/{tache_id}/images", files={"fichier": (nom, contenu, type_)}, **kw)


def _fichiers_sur_disque(tache_id: int | None = None) -> list:
    racine = pieces_jointes._racine()
    base = racine / str(tache_id) if tache_id is not None else racine
    return sorted(p for p in base.rglob("*") if p.is_file()) if base.exists() else []


def _compte(role: str) -> tuple[int, str]:
    from cal_iut.api.state import get_state
    from cal_iut.db.models import User
    from cal_iut.db.session import get_db, init_db

    etat = get_state()
    init_db(etat.db_path)
    email = f"test-{role}-{uuid.uuid4().hex[:10]}@example.test"
    db = get_db(etat.db_path)
    try:
        user = User(email=email, password_hash=accounts.hash_password(MDP), role=role, status="active")
        db.add(user)
        db.commit()
        return user.id, email
    finally:
        db.close()


def _connecter(email: str, ip: str = "testclient") -> TestClient:
    client = TestClient(app, client=(ip, 50000), raise_server_exceptions=False)
    r = client.post("/auth/login", json={"email": email, "password": MDP})
    assert r.status_code == 200, r.text
    return client


# ── Envoi accepté : les quatre formats ──────────────────────────────────


@pytest.mark.parametrize(
    ("contenu", "nom", "type_attendu", "dimensions"),
    [
        (png(), "capture.png", "image/png", (3, 2)),
        # Orientation EXIF 6 (quart de tour) : 4 × 3 stocké, 3 × 4 affiché.
        (JPEG, "photo.jpeg", "image/jpeg", (3, 4)),
        (WEBP, "image.webp", "image/webp", (4, 3)),
        (GIF, "anim.gif", "image/gif", (2, 2)),
    ],
)
def test_les_quatre_formats_sont_acceptes_et_relus(db_isole, contenu, nom, type_attendu, dimensions) -> None:
    client = _client()
    tache_id = _tache(client)
    r = _envoyer(client, tache_id, contenu, nom=nom, type_="application/octet-stream")
    assert r.status_code == 200, r.text
    images = r.json()["images"]
    assert len(images) == 1
    image = images[0]
    assert image["type"] == type_attendu
    assert (image["largeur"], image["hauteur"]) == dimensions
    assert image["url"] == f"/taches/{tache_id}/images/{image['id']}"
    assert image["cree_par"].startswith("test-edit-")
    # Rangée sous un nom GÉNÉRÉ, dans le dossier de la tâche.
    [fichier] = _fichiers_sur_disque(tache_id)
    assert pieces_jointes._FICHIER_VALIDE.match(fichier.name)
    assert nom.rsplit(".", 1)[0] not in fichier.name

    lu = client.get(image["url"])
    assert lu.status_code == 200
    assert lu.headers["content-type"] == type_attendu
    assert lu.content == fichier.read_bytes()
    assert image["taille"] == len(lu.content)
    # Métadonnées retirées (GPS, fabricant, XMP, commentaires, textes PNG).
    assert b"SECRET" not in lu.content
    # Et listée avec la tâche.
    [carte] = client.get("/taches").json()
    assert [i["id"] for i in carte["images"]] == [image["id"]]


def test_l_orientation_d_une_photo_est_la_seule_metadonnee_gardee(db_isole) -> None:
    analyse = pieces_jointes.analyser(JPEG)
    assert b"Exif\x00\x00" in analyse.contenu
    debut = analyse.contenu.index(b"Exif\x00\x00") + 6
    assert pieces_jointes._orientation_exif(analyse.contenu[debut:]) == 6
    assert b"GPS" not in analyse.contenu and b"SECRET" not in analyse.contenu


def test_les_en_tetes_de_lecture(db_isole) -> None:
    client = _client()
    tache_id = _tache(client)
    image = _envoyer(client, tache_id, png(), nom='Capture d\'écran "2026".png').json()["images"][0]
    r = client.get(image["url"])
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"].startswith("private")
    disposition = r.headers["content-disposition"]
    assert disposition.startswith("inline;")
    assert 'filename="Capture d_ecran _2026_.png"' in disposition
    assert "filename*=UTF-8''Capture%20d%27%C3%A9cran%20%222026%22.png" in disposition
    assert "sandbox" in r.headers["content-security-policy"]


# ── Refus : type, taille, nombre ────────────────────────────────────────


@pytest.mark.parametrize(
    ("contenu", "nom", "type_annonce"),
    [
        (SVG, "logo.svg", "image/svg+xml"),
        (SVG, "logo.png", "image/png"),  # SVG déguisé
        (HTML, "capture.png", "image/png"),  # HTML déguisé
        (b"%PDF-1.7\n", "doc.png", "image/png"),
        (b"BM" + b"\x00" * 60, "image.bmp", "image/bmp"),  # BMP : non accepté
    ],
)
def test_un_contenu_qui_n_est_pas_une_image_acceptee_est_refuse(db_isole, contenu, nom, type_annonce) -> None:
    client = _client()
    tache_id = _tache(client)
    r = _envoyer(client, tache_id, contenu, nom=nom, type_=type_annonce)
    assert r.status_code == 415, r.text
    assert "SVG refusé" in r.json()["detail"]
    assert _fichiers_sur_disque() == []
    assert client.get("/taches").json()[0]["images"] == []


@pytest.mark.parametrize(
    "contenu",
    [
        png()[:40],  # tronqué
        png() + b"",
        b"\x89PNG\r\n\x1a\n" + b"<html><script>alert(1)</script></html>",
        b"GIF89a<script>alert(1)</script>",
        JPEG[:200],
    ],
    ids=["png-tronque", "png-ok", "png-signature-seule", "gif-signature-seule", "jpeg-tronque"],
)
def test_une_signature_seule_ne_suffit_pas(db_isole, contenu) -> None:
    client = _client()
    tache_id = _tache(client)
    r = _envoyer(client, tache_id, contenu)
    if contenu == png():
        assert r.status_code == 200
        return
    assert r.status_code == 422, r.text
    assert _fichiers_sur_disque() == []


def test_ce_qui_suit_la_fin_de_l_image_est_retire(db_isole) -> None:
    """Fichier « polyglotte » : une image valide suivie de HTML."""
    for contenu in (png(), JPEG, WEBP, GIF):
        nettoye = pieces_jointes.analyser(contenu + HTML).contenu
        assert b"<script>" not in nettoye


def test_image_trop_lourde(db_isole) -> None:
    client = _client()
    tache_id = _tache(client)
    # Un octet de trop : la taille annoncée passe (marge du multipart), la
    # lecture s'arrête.
    lourd = png() + b"\x00" * (pieces_jointes.TAILLE_MAX_IMAGE + 1 - len(png()))
    r = _envoyer(client, tache_id, lourd)
    assert r.status_code == 413, r.text
    assert "8 Mo" in r.json()["detail"]
    # Bien au-delà : refusé sur la taille annoncée, avant lecture.
    r = _envoyer(client, tache_id, lourd + b"\x00" * (200 * 1024))
    assert r.status_code == 413
    assert _fichiers_sur_disque() == []


def test_image_aux_dimensions_demesurees(db_isole) -> None:
    """Quelques octets de PNG qui annoncent 30 000 × 30 000 pixels."""
    client = _client()
    tache_id = _tache(client)
    r = _envoyer(client, tache_id, png(30_000, 30_000, texte=None))
    assert r.status_code == 413, r.text
    assert "pixels" in r.json()["detail"]


def test_dix_images_au_plus_par_tache(db_isole) -> None:
    client = _client()
    tache_id = _tache(client)
    for _ in range(pieces_jointes.MAX_IMAGES_PAR_TACHE):
        assert _envoyer(client, tache_id, png()).status_code == 200
    r = _envoyer(client, tache_id, png())
    assert r.status_code == 409
    assert "10 images" in r.json()["detail"]
    assert len(_fichiers_sur_disque(tache_id)) == pieces_jointes.MAX_IMAGES_PAR_TACHE
    # Une autre tâche n'est pas concernée.
    assert _envoyer(client, _tache(client, "Autre"), png()).status_code == 200


def test_taille_totale_par_tache(db_isole, monkeypatch) -> None:
    client = _client()
    tache_id = _tache(client)
    monkeypatch.setattr(pieces_jointes, "TAILLE_MAX_TOTALE_PAR_TACHE", len(png(texte=None)) + 10)
    assert _envoyer(client, tache_id, png()).status_code == 200
    r = _envoyer(client, tache_id, png())
    assert r.status_code == 413
    assert "au total" in r.json()["detail"]


def test_envoi_mal_forme(db_isole) -> None:
    client = _client()
    tache_id = _tache(client)
    assert client.post(f"/taches/{tache_id}/images", json={"fichier": "x"}).status_code == 415
    r = client.post(f"/taches/{tache_id}/images", files={"autre": ("a.png", png(), "image/png")})
    assert r.status_code == 422
    assert _envoyer(client, 999_999, png()).status_code == 404


# ── Noms ────────────────────────────────────────────────────────────────


def test_le_nom_d_origine_n_entre_jamais_dans_un_chemin(db_isole) -> None:
    client = _client()
    tache_id = _tache(client)
    nom = "../../../etc/\u202epasswd.svg"
    r = _envoyer(client, tache_id, png(), nom=nom)
    assert r.status_code == 200, r.text
    assert r.json()["images"][0]["nom"] == "passwd.png"
    [fichier] = _fichiers_sur_disque(tache_id)
    assert fichier.parent == pieces_jointes.dossier_tache(tache_id)


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        (None, "image.png"),
        ("", "image.png"),
        ("image.png", "image.png"),
        ("C:\\Users\\moi\\Bureau\\capture.PNG", "capture.png"),
        ("photo.jpeg", "photo.png"),  # extension du type RÉEL
        ("...", "image.png"),
        ("a" * 300 + ".png", "a" * pieces_jointes.NOM_MAX + ".png"),
        ("Réunion\r\nSet-Cookie: x.png", "RéunionSet-Cookie: x.png"),
        ("pass\x00wd\u202e.png", "passwd.png"),
        ('Capture d%27%C3%A9cran %222026%22.png', 'Capture d%27%C3%A9cran "2026".png'),
    ],
)
def test_nom_affichable(brut, attendu) -> None:
    assert pieces_jointes.nom_affichable(brut, "png") == attendu


def test_chemin_refuse_un_nom_non_genere() -> None:
    for mauvais in ("../x.png", "abc.png", "0" * 32 + ".svg", "0" * 32 + ".png/../x"):
        with pytest.raises(ValueError):
            pieces_jointes.chemin(1, mauvais)


# ── Suppression ─────────────────────────────────────────────────────────


def test_supprimer_une_image_retire_la_ligne_et_le_fichier(db_isole) -> None:
    client = _client()
    tache_id = _tache(client)
    _envoyer(client, tache_id, png())
    images = _envoyer(client, tache_id, JPEG, nom="b.jpg").json()["images"]
    premiere, seconde = images
    r = client.delete(premiere["url"])
    assert r.status_code == 200
    assert [i["id"] for i in r.json()["images"]] == [seconde["id"]]
    assert len(_fichiers_sur_disque(tache_id)) == 1
    assert client.get(premiere["url"]).status_code == 404
    assert client.delete(premiere["url"]).status_code == 404
    assert client.get(seconde["url"]).status_code == 200


def test_supprimer_la_tache_retire_ses_images(db_isole) -> None:
    from cal_iut.api.state import get_repo
    from cal_iut.db.models import TacheImage

    client = _client()
    tache_id = _tache(client)
    autre = _tache(client, "Autre")
    url = _envoyer(client, tache_id, png()).json()["images"][0]["url"]
    _envoyer(client, tache_id, GIF, nom="a.gif")
    _envoyer(client, autre, png())
    assert client.delete(f"/taches/{tache_id}").status_code == 200
    assert not pieces_jointes.dossier_tache(tache_id).exists()
    assert len(_fichiers_sur_disque(autre)) == 1
    assert client.get(url).status_code == 404
    assert get_repo().db.query(TacheImage).filter(TacheImage.tache_id == tache_id).count() == 0


def test_un_identifiant_d_image_n_est_jamais_reattribue(db_isole) -> None:
    client = _client()
    tache_id = _tache(client)
    image = _envoyer(client, tache_id, png()).json()["images"][0]
    client.delete(image["url"])
    nouvelle = _envoyer(client, tache_id, png()).json()["images"][0]
    assert nouvelle["id"] > image["id"]


def test_fichier_absent_du_disque_rend_404(db_isole) -> None:
    """Base restaurée sans le volume : la ligne existe, le fichier non."""
    client = _client()
    tache_id = _tache(client)
    image = _envoyer(client, tache_id, png()).json()["images"][0]
    for f in _fichiers_sur_disque(tache_id):
        f.unlink()
    r = client.get(image["url"])
    assert r.status_code == 404
    assert "introuvable" in r.json()["detail"]


def test_une_image_d_une_autre_tache_n_est_pas_servie(db_isole) -> None:
    client = _client()
    a, b = _tache(client, "A"), _tache(client, "B")
    image = _envoyer(client, a, png()).json()["images"][0]
    assert client.get(f"/taches/{b}/images/{image['id']}").status_code == 404
    assert client.delete(f"/taches/{b}/images/{image['id']}").status_code == 404


# ── Droits ──────────────────────────────────────────────────────────────


def test_un_lecteur_voit_les_images_sans_pouvoir_en_ajouter_ni_en_retirer(db_isole) -> None:
    editeur = _client("edit")
    tache_id = _tache(editeur)
    image = _envoyer(editeur, tache_id, png()).json()["images"][0]

    lecteur = _client("read_only")
    assert lecteur.get("/taches").json()[0]["images"][0]["id"] == image["id"]
    assert lecteur.get(image["url"]).status_code == 200
    assert _envoyer(lecteur, tache_id, png()).status_code == 403
    assert lecteur.delete(image["url"]).status_code == 403
    assert len(_fichiers_sur_disque(tache_id)) == 1


def test_un_admin_peut_ajouter_et_retirer(db_isole) -> None:
    admin = _client("admin")
    tache_id = _tache(admin)
    image = _envoyer(admin, tache_id, png()).json()["images"][0]
    assert admin.delete(image["url"]).status_code == 200


def test_sans_compte_ni_lien_public(db_isole) -> None:
    editeur = _client("edit")
    tache_id = _tache(editeur)
    url = _envoyer(editeur, tache_id, png()).json()["images"][0]["url"]
    anonyme = TestClient(app, raise_server_exceptions=False)
    assert anonyme.get(url).status_code == 401
    assert anonyme.get(url, params={"t": "KBR"}).status_code == 401
    assert anonyme.get(f"/api/v1{url}", params={"t": "KBR"}).status_code == 401
    assert _envoyer(anonyme, tache_id, png(), params={"t": "KBR"}).status_code == 401
    assert anonyme.delete(url, params={"t": "KBR"}).status_code == 401


def test_compte_acces_api(db_isole) -> None:
    """Cookie `api` : rien. Clé `api` : la lecture v1 seulement."""
    editeur = _client("edit")
    tache_id = _tache(editeur)
    image = _envoyer(editeur, tache_id, png()).json()["images"][0]

    _, email = _compte("api")
    cookie_api = _connecter(email)
    assert cookie_api.get(image["url"]).status_code == 403
    assert cookie_api.get(f"/api/v1{image['url']}").status_code == 403
    assert _envoyer(cookie_api, tache_id, png()).status_code == 403
    assert cookie_api.delete(image["url"]).status_code == 403

    token = cookie_api.post("/auth/mcp-keys", json={"nom": "script"}).json()["token"]
    cle = TestClient(app, raise_server_exceptions=False, headers={"Authorization": f"Bearer {token}"})
    assert cle.get(image["url"]).status_code == 403
    assert _envoyer(cle, tache_id, png()).status_code == 403
    [carte] = cle.get("/api/v1/taches").json()
    [v1] = carte["images"]
    assert v1 == {
        "id": image["id"], "nom": "capture.png", "type": "image/png", "taille": image["taille"],
        "largeur": 3, "hauteur": 2, "cree_le": image["cree_le"],
        "url": f"/api/v1/taches/{tache_id}/images/{image['id']}",
    }
    assert "cree_par" not in v1  # adresse de compte, jamais exposée par v1
    lu = cle.get(v1["url"])
    assert lu.status_code == 200
    assert lu.headers["content-type"] == "image/png"
    assert lu.headers["x-content-type-options"] == "nosniff"
    assert lu.content == editeur.get(image["url"]).content


def test_l_export_v1_porte_les_images(db_isole) -> None:
    from cal_iut.api import v1

    editeur = _client("edit")
    tache_id = _tache(editeur)
    _envoyer(editeur, tache_id, png())
    [carte] = v1._taches()
    assert carte.images[0].url.startswith(f"/api/v1/taches/{tache_id}/images/")


# ── Anti-aspiration ─────────────────────────────────────────────────────


def test_des_envois_refuses_ne_bannissent_jamais_un_compte(db_isole) -> None:
    """Refus 4xx en série depuis une même IP, par un compte connecté : ni les
    415 (format), ni les 403 (lecteur qui tente d'ajouter) ne le bannissent —
    seules les IP ANONYMES peuvent l'être (`api/anti_aspiration.py`)."""
    from cal_iut.api import anti_aspiration as aa

    assert aa.bannissement_refus_actif()
    _, email_edit = _compte("edit")
    editeur = _connecter(email_edit, ip="203.0.113.50")
    tache_id = _tache(editeur)
    for _ in range(40):
        assert _envoyer(editeur, tache_id, SVG, nom="x.svg").status_code == 415
    _, email_lecteur = _compte("read_only")
    lecteur = _connecter(email_lecteur, ip="203.0.113.51")
    for _ in range(40):
        assert _envoyer(lecteur, tache_id, png()).status_code == 403
    assert not [b for b in aa.blocages.lister() if b.valeur in ("203.0.113.50", "203.0.113.51")]
    assert _envoyer(editeur, tache_id, png()).status_code == 200
    assert lecteur.get("/taches").status_code == 200


# ── Base ────────────────────────────────────────────────────────────────


def test_la_table_est_creee_sur_une_base_existante(tmp_path) -> None:
    import sqlalchemy as sa

    from cal_iut.db import session as db_session
    from cal_iut.db.session import init_db

    chemin = tmp_path / "ancienne.db"
    init_db(chemin)
    moteur = db_session.get_engine(chemin)
    with moteur.begin() as connexion:
        connexion.execute(sa.text("DROP TABLE taches_images"))
    assert "taches_images" not in sa.inspect(moteur).get_table_names()
    init_db(chemin)
    assert "taches_images" in sa.inspect(moteur).get_table_names()
    moteur.dispose()
    db_session._engine = None
    db_session._SessionLocal = None
