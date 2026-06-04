"""
Database connection pool manager.
Single engine instance shared across the application.
All database access goes through get_db() context manager.
"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from config.settings import DATABASE_URL, DATABASE_POOL_SIZE, DATABASE_MAX_OVERFLOW
from utils.logger import get_logger

logger = get_logger('db.connection')

engine = create_engine(
    DATABASE_URL,
    pool_size=DATABASE_POOL_SIZE,
    max_overflow=DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,       # Test connection health before checkout
    pool_recycle=3600,        # Recycle connections after 1 hour
    echo=False,               # Set True temporarily for SQL debugging only
    connect_args={
        'connect_timeout': 10,
        'options': '-c timezone=UTC',   # Always store as UTC
    }
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.
    Commits on clean exit, rolls back on any exception, always closes.

    Usage:
        with get_db() as db:
            db.execute(text("SELECT 1"))
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error — transaction rolled back: {e}")
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error — transaction rolled back: {e}")
        raise
    finally:
        db.close()


def health_check() -> bool:
    """Verify the database connection is live and accepting queries."""
    try:
        with get_db() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


def get_table_count() -> int:
    """Return the number of tables in the public schema. Used for schema verification."""
    try:
        with get_db() as db:
            result = db.execute(text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            ))
            return result.scalar()
    except Exception as e:
        logger.error(f"Failed to count tables: {e}")
        return 0