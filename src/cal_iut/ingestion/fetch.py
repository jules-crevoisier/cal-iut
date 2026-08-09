"""Téléchargement des exports JSON officiels."""

from pathlib import Path

import httpx

MAQUETTE_URL = "https://mmi23x02.mmi-troyes.fr/export/maquette"
PROGRESSION_URL = "https://mmi23x02.mmi-troyes.fr/export/progression"


async def fetch_export(url: str) -> list[dict[str, object]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"Expected list from {url}, got {type(payload)}")
        return payload


def fetch_export_sync(url: str) -> list[dict[str, object]]:
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"Expected list from {url}, got {type(payload)}")
        return payload


async def fetch_all_exports() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    maquette = await fetch_export(MAQUETTE_URL)
    progression = await fetch_export(PROGRESSION_URL)
    return maquette, progression


def load_local_exports(
    *candidates: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]]] | None:
    """Charge maquette/progression depuis le disque si les fichiers sont valides."""
    import json

    for base in candidates:
        maquette_path = base / "maquette.json" if base.is_dir() else base
        if base.is_dir():
            m_path, p_path = base / "maquette.json", base / "progression.json"
        else:
            continue
        if not m_path.exists() or not p_path.exists():
            continue
        if m_path.stat().st_size < 100 or p_path.stat().st_size < 100:
            continue
        maquette = json.loads(m_path.read_text(encoding="utf-8"))
        progression = json.loads(p_path.read_text(encoding="utf-8"))
        if isinstance(maquette, list) and isinstance(progression, list):
            return maquette, progression
    return None


def fetch_all_exports_sync(
    prefer_local: bool = True,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if prefer_local:
        root = Path(__file__).resolve().parents[3]
        local = load_local_exports(root, root / "data" / "exports")
        if local:
            return local
    return fetch_export_sync(MAQUETTE_URL), fetch_export_sync(PROGRESSION_URL)


def save_exports(
    output_dir: Path,
    maquette: list[dict[str, object]],
    progression: list[dict[str, object]],
) -> None:
    import json

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "maquette.json").write_text(
        json.dumps(maquette, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "progression.json").write_text(
        json.dumps(progression, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
