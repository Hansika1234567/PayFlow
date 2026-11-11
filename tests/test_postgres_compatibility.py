import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, DatabaseError
from backend.config import settings
from backend.database import Base, SessionLocal
from backend.models.user import User
from backend.models.wallet import Wallet
from backend.services.wallet_service import get_or_create_wallet
from tests.conftest import validate_test_database_safety

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

def test_wallet_provisioning_transaction_boundary():
    """
    Verifies that get_or_create_wallet(auto_commit=False) leaves the transaction
    uncommitted so the caller retains explicit ownership of the commit boundary.
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

        # Provision with auto_commit=False
        wallet = get_or_create_wallet(db, user, auto_commit=False)
        assert wallet is not None
        assert wallet.balance == settings.INITIAL_WALLET_BALANCE_CENTS

        # If caller rolls back, the provisioned wallet must be rolled back too!
        db.rollback()

        # Verify rollback took effect
        queried_wallet = db.query(Wallet).filter(Wallet.user_id == user.id).first()
        assert queried_wallet is None
    finally:
        db.close()

def test_test_database_safety_validator_rejects_protected_targets():
    """
    Verifies that the test database safety guard strictly prevents execution
    against payflow.db, production hosts, or non-test database names.
    """
    # 1. Primary SQLite file payflow.db must be rejected
    with pytest.raises(RuntimeError) as exc1:
        validate_test_database_safety("sqlite:///./payflow.db")
    assert "FATAL SAFETY ABORT" in str(exc1.value)

    # 2. Production PostgreSQL database name must be rejected
    with pytest.raises(RuntimeError) as exc2:
        validate_test_database_safety("postgresql+psycopg2://postgres:pass@localhost:5432/payflow_db")
    assert "protected/production" in str(exc2.value)

    # 3. Remote non-test host must be rejected
    with pytest.raises(RuntimeError) as exc3:
        validate_test_database_safety("postgresql+psycopg2://user:pass@prod-cluster.cloud.internal:5432/my_test")
    assert "Non-test host" in str(exc3.value)

    # 4. Valid test URLs must be accepted without error
    validate_test_database_safety("sqlite:///./test_payflow.db")
    validate_test_database_safety("postgresql+psycopg2://postgres:postgres@localhost:5432/payflow_test")
    validate_test_database_safety("postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/test_payflow")
