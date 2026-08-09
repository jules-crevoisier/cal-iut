"""Session SQLite."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cal_iut.db.models import Base

DEFAULT_DB = Path(__file__).resolve().parents[3] / "data" / "cal-iut.db"

_engine = None
_SessionLocal = None


def get_engine(db_path: Path | None = None):
    global _engine, _SessionLocal
    path = db_path or DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{path}"
    _engine = create_engine(url, connect_args={"check_same_thread": False})
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def init_db(db_path: Path | None = None) -> None:
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)


def get_db(db_path: Path | None = None) -> Session:
    if _SessionLocal is None:
        get_engine(db_path)
    assert _SessionLocal is not None
    return _SessionLocal()
