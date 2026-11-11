import os
import pytest
from urllib.parse import urlparse

# 1. Determine test database URL.
# By default, safely defaults to an isolated SQLite file (test_payflow.db).
# Optional PostgreSQL testing is enabled ONLY if TEST_DATABASE_URL is explicitly set.
TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "sqlite:///./test_payflow.db").strip()

def validate_test_database_safety(url: str, is_destructive_cleanup: bool = False):
    """
    Enforces strict, multi-layered safety invariants ensuring destructive test operations
    (create_all, drop_all, file removal) NEVER touch payflow.db, payflow_db,
    or any development or production database.
    """
    if not url:
        raise RuntimeError("FATAL SAFETY ERROR: Empty test database URL provided.")

    if url.startswith("sqlite"):
        clean_path = url.replace("sqlite:///./", "").replace("sqlite:///", "").strip()
        # Invariant 1: Must never target payflow.db directly or without 'test_' prefix
        if clean_path == "payflow.db" or ("payflow.db" in clean_path and not clean_path.startswith("test_")):
            raise RuntimeError(f"FATAL SAFETY ABORT: Attempted to run tests against primary database: '{url}'")
        if not (clean_path.startswith("test_") or clean_path.endswith("_test.db")):
            raise RuntimeError(f"FATAL SAFETY ABORT: SQLite test database file must start with 'test_' or end with '_test.db': '{clean_path}'")
        return

    # PostgreSQL Safety Invariants:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("postgresql", "postgresql+psycopg2", "postgres"):
        raise RuntimeError(f"FATAL SAFETY ABORT: Unsupported database scheme for tests: '{scheme}'")

    # Invariant A: Strict Host Allowlisting (no broad substring checks)
    hostname = (parsed.hostname or "").lower()
    approved_test_hosts = {"localhost", "127.0.0.1", "::1", "test-db", "postgres-test"}
    is_approved_host = (
        hostname in approved_test_hosts
        or hostname.endswith(".test")
        or hostname.startswith("test-")
    )
    if not is_approved_host:
        raise RuntimeError(
            f"FATAL SAFETY ABORT: Non-test host detected in TEST_DATABASE_URL: '{hostname}'. "
            f"Testing is strictly restricted to allowlisted test hosts ({approved_test_hosts}) or '*.test' domains."
        )

    # Invariant B: Strict Database Naming (anchored prefix or suffix only, no broad substring matches)
    db_name = parsed.path.lstrip("/").strip().lower()
    if not db_name:
        raise RuntimeError("FATAL SAFETY ABORT: No database name specified in PostgreSQL test URL.")

    # Invariant C: Protected Name Blacklist
    blacklisted_names = {
        "payflow", "payflow_db", "payflow_dev", "payflow_prod",
        "production", "prod", "master", "main", "postgres", "default"
    }
    if db_name in blacklisted_names:
        raise RuntimeError(f"FATAL SAFETY ABORT: Test database matches protected/production name: '{db_name}'.")

    # Must explicitly start with 'test_' or end with '_test' (e.g. 'payflow_test' or 'test_payflow')
    is_safe_dbname = db_name.startswith("test_") or db_name.endswith("_test") or db_name == "test"
    if not is_safe_dbname:
        raise RuntimeError(
            f"FATAL SAFETY ABORT: PostgreSQL test database name must strictly start with 'test_' or end with '_test' (e.g. 'payflow_test'). "
            f"Got: '{db_name}'"
        )

    # Invariant D: Dedicated Test Credentials & Reject Privileged Superuser Roles
    username = (parsed.username or "").lower()
    privileged_roles = {"root", "admin", "administrator", "superuser", "master", "prod", "production"}
    if username in privileged_roles:
        raise RuntimeError(
            f"FATAL SAFETY ABORT: Privileged superuser role ('{username}') is forbidden for tests. "
            f"Please use a dedicated non-privileged test role (e.g. 'test_user' or 'payflow_test')."
        )

    # Invariant E: Explicit Opt-In required for destructive PostgreSQL cleanup (drop_all)
    if is_destructive_cleanup:
        opt_in = os.getenv("ALLOW_POSTGRES_TEST_CLEANUP", "false").lower()
        if opt_in not in ("true", "1", "yes"):
            raise RuntimeError(
                "FATAL SAFETY ABORT: Destructive PostgreSQL test cleanup (drop_all) requires explicit opt-in "
                "via ALLOW_POSTGRES_TEST_CLEANUP=true environment variable."
            )

# Validate safety BEFORE setting environment variables or importing application modules
validate_test_database_safety(TEST_DB_URL, is_destructive_cleanup=False)

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
    validate_test_database_safety(TEST_DB_URL, is_destructive_cleanup=False)
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
        # PostgreSQL cleanup: re-validate safety guard and explicit opt-in before drop_all
        validate_test_database_safety(TEST_DB_URL, is_destructive_cleanup=True)
        Base.metadata.drop_all(bind=engine)
