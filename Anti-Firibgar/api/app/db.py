import logging
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

log = logging.getLogger(__name__)

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(retries: int = 30) -> None:
    """Wait for Postgres (it may still be booting in Docker), then create tables."""
    from . import models  # noqa: F401  register models

    for attempt in range(1, retries + 1):
        try:
            Base.metadata.create_all(engine)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("DB not ready (%s/%s): %s", attempt, retries, exc)
            time.sleep(2)
    raise RuntimeError("Could not connect to the database")
