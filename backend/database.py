from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from typing import Generator
from backend.config import settings

# Determine if running SQLite or PostgreSQL
is_sqlite = settings.DATABASE_URL.startswith("sqlite")

# Normalize legacy postgres:// scheme to postgresql:// for SQLAlchemy 2.0+ compatibility
db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

if is_sqlite:
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        echo=False,
        pool_pre_ping=True,
    )

    # Enable Foreign Key enforcement, WAL mode, and busy timeout for SQLite only
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=15000;")
        cursor.close()

    @event.listens_for(engine, "begin")
    def do_begin(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")
else:
    # Production-ready PostgreSQL connection pool with explicit READ COMMITTED isolation
    engine = create_engine(
        db_url,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
        isolation_level="READ COMMITTED",
        echo=False,
    )

# SessionLocal is the factory for creating new DB sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for all SQLAlchemy declarative models
Base = declarative_base()

def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a transactional database session per request.
    Yields the session to the route handler, and guarantees the session is closed
    when the request finishes, preventing database connection leaks.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
