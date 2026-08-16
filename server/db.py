from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

import settings


def _build_database_url() -> str:
    # Credentials are percent-encoded: an unescaped '@', ':' or '/' in the
    # password would otherwise be parsed as URL structure and misroute the connection.
    user = quote_plus(settings.POSTGRES_USER)
    password = quote_plus(settings.POSTGRES_PASSWORD)
    return (
        f"postgresql+psycopg://{user}:{password}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.APP_DB_NAME}"
    )


engine = create_engine(
    _build_database_url(),
    pool_pre_ping=True,
    connect_args={"connect_timeout": settings.POSTGRES_CONNECT_TIMEOUT},
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
