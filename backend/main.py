from datetime import datetime
from fastapi import FastAPI, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.config import settings
from backend.database import engine, Base, get_db
import backend.models  # Ensures all models are imported before creating tables
from backend.routers import auth, wallets, transfers, ledger

# Initialize database schema tables on startup
Base.metadata.create_all(bind=engine)

def init_ledger_immutability_triggers(target_engine, is_sqlite_db: bool):
    """
    Installs database-level engine triggers preventing UPDATE and DELETE on ledger_entries.
    Ensures that whether running on SQLite or PostgreSQL, historical audit entries are strictly immutable.
    """
    try:
        with target_engine.connect() as conn:
            if is_sqlite_db:
                conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS prevent_ledger_update
                BEFORE UPDATE ON ledger_entries
                BEGIN
                    SELECT RAISE(ABORT, 'Ledger entries are strictly immutable and cannot be updated.');
                END;
                """))
                conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS prevent_ledger_delete
                BEFORE DELETE ON ledger_entries
                BEGIN
                    SELECT RAISE(ABORT, 'Historical ledger audit records cannot be deleted.');
                END;
                """))
            else:
                # PostgreSQL PL/pgSQL function and triggers
                conn.execute(text("""
                CREATE OR REPLACE FUNCTION enforce_ledger_immutability()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'Ledger entries are strictly immutable and cannot be updated or deleted.';
                END;
                $$ LANGUAGE plpgsql;
                """))
                conn.execute(text("""
                DROP TRIGGER IF EXISTS prevent_ledger_update ON ledger_entries;
                CREATE TRIGGER prevent_ledger_update
                BEFORE UPDATE ON ledger_entries
                FOR EACH ROW EXECUTE FUNCTION enforce_ledger_immutability();
                """))
                conn.execute(text("""
                DROP TRIGGER IF EXISTS prevent_ledger_delete ON ledger_entries;
                CREATE TRIGGER prevent_ledger_delete
                BEFORE DELETE ON ledger_entries
                FOR EACH ROW EXECUTE FUNCTION enforce_ledger_immutability();
                """))
            conn.commit()
    except Exception as e:
        print(f"[Triggers] Notice: {e}")

# Initialize database-level immutability protection for Ledger
init_ledger_immutability_triggers(engine, settings.DATABASE_URL.startswith("sqlite"))

def seed_demo_accounts():
    """Ensure alice_demo and bob_demo exist with initial wallets for instant UI evaluation."""
    from backend.database import SessionLocal
    from backend.models.user import User
    from backend.schemas.auth import UserRegisterRequest
    from backend.services.user_service import register_user

    db = SessionLocal()
    try:
        demo_users = [
            ("alice_demo", "alice@paypal-demo.internal", "Alice Developer"),
            ("bob_demo", "bob@paypal-demo.internal", "Bob Engineer"),
        ]
        for uname, uemail, ufullname in demo_users:
            existing = db.query(User).filter(User.username == uname).first()
            if not existing:
                req = UserRegisterRequest(
                    email=uemail,
                    username=uname,
                    password="Password123!",
                    full_name=ufullname,
                )
                register_user(db, req)
    except Exception as e:
        print(f"[Seed] Info: {e}")
    finally:
        db.close()

seed_demo_accounts()

app = FastAPI(
    title="PayFlow API",
    description=(
        "Production-grade Digital Wallet & Transaction Management API demonstrating "
        "double-entry ledger bookkeeping, deterministic concurrency locking, "
        "idempotency key protection, and atomic transactions."
    ),
    version=settings.VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS Middleware using dynamic environment allowed origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(wallets.router, prefix=settings.API_V1_STR)
app.include_router(transfers.router, prefix=settings.API_V1_STR)
app.include_router(ledger.router, prefix=settings.API_V1_STR)

@app.get(f"{settings.API_V1_STR}/health", tags=["System Health"], status_code=status.HTTP_200_OK)
def health_check(db: Session = Depends(get_db)):
    """
    System Health Check endpoint.
    Verifies that the API server is responsive and executes a test query
    against the database connection pool.
    """
    try:
        # Run a lightweight DB ping
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"unreachable: {str(e)}"

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "database": db_status,
        "timestamp": datetime.utcnow().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8005, reload=True)
