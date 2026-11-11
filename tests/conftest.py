import os
import pytest
from urllib.parse import urlparse

# 1. Determine test database URL.
# By default, safely defaults to an isolated SQLite file (test_payflow.db).
# Optional PostgreSQL testing is enabled ONLY if TEST_DATABASE_URL is explicitly set.
TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "sqlite:///./test_payflow.db").strip()

def validate_test_database_safety(url: str):
    """
    Enforces strict safety invariants ensuring destructive test operations
    (create_all, drop_all, file removal) NEVER touch payflow.db, payflow_db,
    or any development or production database.
    """
    if not url:
        raise RuntimeError("FATAL SAFETY ERROR: Empty test database URL provided.")

    if url.startswith("sqlite"):
        clean_path = url.replace("sqlite:///./", "").replace("sqlite:///", "")
        if clean_path == "payflow.db" or ("payflow.db" in clean_path and "test" not in clean_path):
            raise RuntimeError(f"FATAL SAFETY ABORT: Attempted to run tests against primary database: '{url}'")
        if "test" not in clean_path.lower():
            raise RuntimeError(f"FATAL SAFETY ABORT: SQLite test database file must contain 'test' in its name: '{clean_path}'")
        return

    # PostgreSQL Safety Invariants:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if not ("postgres" in scheme or "postgresql" in scheme):
        raise RuntimeError(f"FATAL SAFETY ABORT: Unsupported database scheme for tests: '{scheme}'")

    # Invariant A: Host validation (must be local loopback or dedicated test host)
    hostname = (parsed.hostname or "").lower()
    safe_hosts = ["localhost", "127.0.0.1", "::1", "test-db", "postgres-test"]
    if not any(hostname == h or hostname.endswith(".test") or "test" in hostname for h in safe_hosts):
        raise RuntimeError(
            f"FATAL SAFETY ABORT: Non-test host detected in TEST_DATABASE_URL: '{hostname}'. "
            f"Destructive test operations are only permitted on loopback or test hosts."
        )

    # Invariant B: Database name validation
    db_name = parsed.path.lstrip("/").strip().lower()
    if not db_name:
        raise RuntimeError("FATAL SAFETY ABORT: No database name specified in PostgreSQL test URL.")

    # Invariant C: Protected name blacklist
    blacklisted_names = [
        "payflow", "payflow_db", "payflow_dev", "payflow_prod",
        "production", "prod", "master", "main", "postgres"
    ]
    if db_name in blacklisted_names:
        raise RuntimeError(f"FATAL SAFETY ABORT: Test database matches protected/production name: '{db_name}'.")

    # Invariant D: Required test marker in database name
    if not ("test" in db_name):
        raise RuntimeError(
            f"FATAL SAFETY ABORT: PostgreSQL test database name must explicitly contain 'test' (e.g. 'payflow_test'). "
            f"Got: '{db_name}'"
        )

# Validate safety BEFORE setting environment variables or importing application modules
validate_test_database_safety(TEST_DB_URL)

os.environ["ENVIRONMENT"] = "testing"
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["SECRET_KEY"] = "payflow-test-isolated-secret-key-32-chars-entropy!!"

from backend.database import Base, engine

@pytest.fixture(scope="session", autouse=True)
def setup_and_teardown_test_database():
    """
    Session-scoped fixture to manage isolated test database lifecycle.
    Ensures all tables are provisioned on the validated test database and safely cleaned up.
    """
    # Double-check safety guard at start of test execution
    validate_test_database_safety(TEST_DB_URL)
    Base.metadata.create_all(bind=engine)

    yield

    # Teardown test database connections safely
    engine.dispose()
    if TEST_DB_URL.startswith("sqlite"):
        test_file = TEST_DB_URL.replace("sqlite:///./", "").replace("sqlite:///", "")
        for f in [test_file, f"{test_file}-wal", f"{test_file}-shm"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
    else:
        # PostgreSQL cleanup: re-validate safety guard before drop_all
        validate_test_database_safety(TEST_DB_URL)
        Base.metadata.drop_all(bind=engine)
