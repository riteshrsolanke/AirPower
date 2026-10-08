"""
SQLAlchemy database connection and session management.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from backend.app.core.config import settings

# SQLite pragmas for better security and performance
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    echo=settings.DEBUG,
)

# Enable WAL mode and foreign keys for SQLite
if "sqlite" in settings.DATABASE_URL:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_schema_columns():
    """Ensure optional/new synthetic columns exist in SQLite database without losing existing data."""
    if "sqlite" not in settings.DATABASE_URL:
        return
    try:
        with engine.begin() as conn:
            # Check aircraft table columns
            res = conn.exec_driver_sql("PRAGMA table_info(aircraft)").fetchall()
            col_names = [r[1] for r in res]
            if "range_km" not in col_names:
                conn.exec_driver_sql("ALTER TABLE aircraft ADD COLUMN range_km FLOAT DEFAULT 2000.0")
            if "fuel_capacity" not in col_names:
                conn.exec_driver_sql("ALTER TABLE aircraft ADD COLUMN fuel_capacity FLOAT DEFAULT 5000.0")
            if "payload_capacity" not in col_names:
                conn.exec_driver_sql("ALTER TABLE aircraft ADD COLUMN payload_capacity FLOAT DEFAULT 4000.0")

            # Check missions table columns
            res = conn.exec_driver_sql("PRAGMA table_info(missions)").fetchall()
            m_col_names = [r[1] for r in res]
            if "distance_km" not in m_col_names:
                conn.exec_driver_sql("ALTER TABLE missions ADD COLUMN distance_km FLOAT DEFAULT 500.0")
            if "required_payload" not in m_col_names:
                conn.exec_driver_sql("ALTER TABLE missions ADD COLUMN required_payload FLOAT DEFAULT 1500.0")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("ensure_schema_columns notice: %s", e)


ensure_schema_columns()


def get_db():
    """Dependency for FastAPI to provide database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
