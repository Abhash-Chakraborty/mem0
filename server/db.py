import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Bound how long a single connect attempt may block. Without this psycopg waits
# indefinitely, so an unreachable or slow Postgres turns any caller into a hang
# instead of a prompt error - including the import-time admin check in main.py,
# which is wrapped in try/except that a never-returning connect never reaches.
CONNECT_TIMEOUT = int(os.environ.get("POSTGRES_CONNECT_TIMEOUT", "10"))


def _build_database_url() -> str:
    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    # Credentials are percent-encoded: an unescaped '@', ':' or '/' in the
    # password would otherwise be parsed as URL structure and misroute the connection.
    user = quote_plus(os.environ.get("POSTGRES_USER", "postgres"))
    password = quote_plus(os.environ.get("POSTGRES_PASSWORD", "postgres"))
    db = os.environ.get("APP_DB_NAME", "mem0_app")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


engine = create_engine(
    _build_database_url(),
    pool_pre_ping=True,
    connect_args={"connect_timeout": CONNECT_TIMEOUT},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a SQLAlchemy session."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
