from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config.settings import get_settings

settings = get_settings()

# pool_size/max_overflow are Queue-pool-only options; SQLite (used by the
# test suite via DATABASE_URL=sqlite:///:memory:) uses SingletonThreadPool
# and rejects them outright. Everything else about engine creation is
# unchanged - this only branches the two pool-sizing kwargs.
#
# NOTE: deliberately NOT passing echo=... here. SQLAlchemy's echo kwarg, the
# first time it's set True, auto-attaches its own default-formatted
# StreamHandler directly to the "sqlalchemy.engine.Engine" logger if none
# exists yet at that moment. Since this module is imported (and the engine
# created) before main.py's logging.basicConfig() runs, that auto-handler
# gets added first - then basicConfig adds a second one on the root logger,
# and every query logs twice, once per handler, in two different formats.
# Setting the logger's level directly (see main.py) achieves the same
# "show me SQL in dev" outcome without that side effect.
_engine_kwargs = dict(
    pool_pre_ping=True,
    pool_recycle=1800,
)
if not settings.database_url.startswith("sqlite"):
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20

engine = create_engine(settings.database_url, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()