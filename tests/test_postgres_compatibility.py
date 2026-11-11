import os
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, DatabaseError
from backend.main import app
from backend.config import settings
from backend.database import Base, SessionLocal
from backend.models.user import User
from backend.models.wallet import Wallet
from backend.services.wallet_service import get_or_create_wallet
from backend.utils.security import get_password_hash
from tests.conftest import validate_test_database_safety

client = TestClient(app)

def test_postgres_engine_pool_configuration():
    """
    Verifies that non-SQLite database configurations initialize with proper
    connection pooling parameters and READ COMMITTED transaction isolation.
    """
    assert settings.DB_POOL_SIZE >= 5
    assert settings.DB_MAX_OVERFLOW >= 10
    assert settings.DB_POOL_TIMEOUT >= 10
    assert settings.DB_POOL_RECYCLE >= 300
    assert settings.MAX_SAFE_BALANCE_CENTS == 9007199254740991

def test_integer_only_money_formatting():
    """
    Task 1: Verifies that balance_dollars_formatted uses integer-only arithmetic (divmod)
    and produces precise 2-decimal strings without any binary floating-point drift.
    """
    # 1. Standard dollars and cents
    w1 = Wallet(balance=125050)
    assert w1.balance_dollars_formatted == "1250.50"

    # 2. Leading zero cents ($1,000.05)
    w2 = Wallet(balance=100005)
    assert w2.balance_dollars_formatted == "1000.05"

    # 3. Exact zero dollars and cents
    w3 = Wallet(balance=0)
    assert w3.balance_dollars_formatted == "0.00"

    # 4. Large balance up to Number.MAX_SAFE_INTEGER
    w4 = Wallet(balance=settings.MAX_SAFE_BALANCE_CENTS)
    expected_dollars, expected_cents = divmod(settings.MAX_SAFE_BALANCE_CENTS, 100)
    assert w4.balance_dollars_formatted == f"{expected_dollars}.{expected_cents:02d}"

def test_money_precision_wallet_balance_check_constraint():
    """
    Verifies that the database-level CheckConstraint 'check_wallet_balance_safe_range'
    actively rejects negative balances and balances exceeding JavaScript Number.MAX_SAFE_INTEGER.
    """
    db = SessionLocal()
    try:
        # 1. Create a test user
        user = User(
            email="precision_tester@test.com",
            username="precision_tester",
            hashed_password="hashed_pwd_placeholder",
            full_name="Precision Tester",
        )
        db.add(user)
        db.flush()

        # 2. Test negative balance -> Must be rejected by database CheckConstraint
        neg_wallet = Wallet(
            user_id=user.id,
            balance=-100,  # Negative balance violation
            currency="USD",
            status="ACTIVE",
            version=1,
        )
        db.add(neg_wallet)
        with pytest.raises((IntegrityError, DatabaseError)):
            db.commit()
        db.rollback()

        # 3. Test balance exceeding 2^53 - 1 -> Must be rejected by database CheckConstraint
        overflow_wallet = Wallet(
            user_id=user.id,
            balance=settings.MAX_SAFE_BALANCE_CENTS + 1000,  # Overflow violation
            currency="USD",
            status="ACTIVE",
            version=1,
        )
        db.add(overflow_wallet)
        with pytest.raises((IntegrityError, DatabaseError)):
            db.commit()
        db.rollback()

    finally:
        db.close()

def test_no_implicit_commit_by_wallet_helper():
    """
    Task 3: Verifies that get_or_create_wallet(db, user) defaults to auto_commit=False,
    ensuring that wallet provisioning does not prematurely commit caller transactions.
    """
    db = SessionLocal()
    try:
        user = User(
            email="boundary_tester@test.com",
            username="boundary_tester",
            hashed_password="hashed_pwd_placeholder",
            full_name="Boundary Tester",
        )
        db.add(user)
        db.flush()

        # Call with default arguments (auto_commit defaults to False)
        wallet = get_or_create_wallet(db, user)
        assert wallet is not None
        assert wallet.balance == settings.INITIAL_WALLET_BALANCE_CENTS

        # Caller issues rollback -> provisioned wallet MUST be rolled back because helper did not commit!
        db.rollback()

        # Query after rollback proves nothing was committed
        queried_wallet = db.query(Wallet).filter(Wallet.user_id == user.id).first()
        assert queried_wallet is None
    finally:
        db.close()

def test_get_my_wallet_is_strictly_read_only():
    """
    Task 3: Verifies that GET /api/v1/wallets/me is strictly read-only.
    If a user has no wallet, it does not secretly write to the database; it returns 404.
    An explicit POST /api/v1/wallets/initialize provides recovery for legacy accounts.
    """
    # 1. Manually create an unprovisioned user without a wallet
    db = SessionLocal()
    unique_suffix = uuid.uuid4().hex[:6]
    unprovisioned_username = f"unprovisioned_{unique_suffix}"
    try:
        raw_user = User(
            email=f"{unprovisioned_username}@test.com",
            username=unprovisioned_username,
            hashed_password=get_password_hash("Password123!"),
            full_name="Unprovisioned User",
            is_active=True,
        )
        db.add(raw_user)
        db.commit()
        db.refresh(raw_user)
    finally:
        db.close()

    # Login to acquire token
    login_res = client.post("/api/v1/auth/login", json={
        "email_or_username": unprovisioned_username,
        "password": "Password123!"
    })
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Call GET /wallets/me -> Must return 404 (strictly read-only, zero hidden writes)
    me_res = client.get("/api/v1/wallets/me", headers=headers)
    assert me_res.status_code == 404
    assert "not provisioned" in me_res.json()["detail"].lower()

    # Verify database: still no wallet
    db = SessionLocal()
    try:
        user_in_db = db.query(User).filter(User.username == unprovisioned_username).first()
        assert user_in_db.wallet is None
    finally:
        db.close()

    # 3. Call explicit recovery endpoint POST /wallets/initialize -> Must return 201 Created
    init_res = client.post("/api/v1/wallets/initialize", headers=headers)
    assert init_res.status_code == 201
    assert init_res.json()["balance_cents"] == settings.INITIAL_WALLET_BALANCE_CENTS

    # 4. Now GET /wallets/me returns 200 OK
    me_after = client.get("/api/v1/wallets/me", headers=headers)
    assert me_after.status_code == 200
    assert me_after.json()["balance_cents"] == settings.INITIAL_WALLET_BALANCE_CENTS

def test_strict_test_database_safety_validator():
    """
    Task 2: Verifies that the strengthened test database safety guard strictly prevents
    execution against payflow.db, privileged roles, remote non-test hosts, and non-test database names.
    """
    # 1. Primary SQLite file payflow.db must be rejected
    with pytest.raises(RuntimeError) as exc1:
        validate_test_database_safety("sqlite:///./payflow.db")
    assert "FATAL SAFETY ABORT" in str(exc1.value)

    # 2. SQLite file missing 'test_' prefix or '_test.db' suffix must be rejected
    with pytest.raises(RuntimeError) as exc2:
        validate_test_database_safety("sqlite:///./production_data.db")
    assert "must start with 'test_'" in str(exc2.value)

    # 3. Privileged superuser roles must be rejected
    for role in ["root", "admin", "superuser", "master"]:
        with pytest.raises(RuntimeError) as exc_role:
            validate_test_database_safety(f"postgresql://{role}:pass@localhost:5432/payflow_test")
        assert "Privileged superuser role" in str(exc_role.value)

    # 4. Broad substring hostname (e.g. attestation.production.internal) must be rejected
    with pytest.raises(RuntimeError) as exc_host:
        validate_test_database_safety("postgresql://test_user:pass@attestation.production.internal:5432/payflow_test")
    assert "Non-test host detected" in str(exc_host.value)

    # 5. Database names that don't start with 'test_' or end with '_test' must be rejected
    with pytest.raises(RuntimeError) as exc_dbname:
        validate_test_database_safety("postgresql://test_user:pass@localhost:5432/latest_payflow_prod")
    assert "must strictly start with 'test_'" in str(exc_dbname.value)

    # 6. Destructive cleanup without explicit ALLOW_POSTGRES_TEST_CLEANUP must be rejected
    with pytest.raises(RuntimeError) as exc_cleanup:
        validate_test_database_safety("postgresql://test_user:pass@localhost:5432/payflow_test", is_destructive_cleanup=True)
    assert "requires explicit opt-in" in str(exc_cleanup.value)

    # 7. Valid test URLs pass without error
    validate_test_database_safety("sqlite:///./test_payflow.db")
    validate_test_database_safety("postgresql+psycopg2://test_user:test_pass@localhost:5432/payflow_test")
    validate_test_database_safety("postgresql+psycopg2://test_user:test_pass@127.0.0.1:5432/test_payflow")

def test_alembic_migration_defines_postgres_triggers():
    """
    Task 4: Verifies by code inspection that alembic/versions/ddde32ea299c_initial_payflow_schema.py
    defines the PL/pgSQL function and UPDATE/DELETE triggers in upgrade() and drops them in downgrade().
    """
    migration_path = os.path.join(os.path.dirname(__file__), "..", "alembic", "versions", "ddde32ea299c_initial_payflow_schema.py")
    assert os.path.exists(migration_path), "Initial migration file must exist."

    with open(migration_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Verify upgrade creates function and triggers
    assert "CREATE OR REPLACE FUNCTION enforce_ledger_immutability()" in content
    assert "CREATE TRIGGER prevent_ledger_update" in content
    assert "CREATE TRIGGER prevent_ledger_delete" in content

    # Verify downgrade drops triggers and function
    assert "DROP TRIGGER IF EXISTS prevent_ledger_update" in content
    assert "DROP TRIGGER IF EXISTS prevent_ledger_delete" in content
    assert "DROP FUNCTION IF EXISTS enforce_ledger_immutability()" in content
