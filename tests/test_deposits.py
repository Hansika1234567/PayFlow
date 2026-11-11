import uuid
import concurrent.futures
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models.user import User
from backend.models.wallet import Wallet
from backend.models.transaction import Transaction
from backend.models.ledger import LedgerEntry

client = TestClient(app)

def create_user_and_login(username_prefix: str):
    """Helper to register a new user and return their auth token and username."""
    unique_id = uuid.uuid4().hex[:6]
    username = f"{username_prefix}_{unique_id}"
    email = f"{username}@test.com"
    payload = {
        "email": email,
        "username": username,
        "password": "Password123!",
        "full_name": f"{username_prefix.capitalize()} Tester"
    }
    res = client.post("/api/v1/auth/register", json=payload)
    assert res.status_code == 201, f"User registration failed: {res.text}"
    token = res.json()["access_token"]
    return token, username

def test_concurrent_deposits_distinct_keys():
    """
    Test 1: 10 concurrent deposits with distinct idempotency keys.
    Validates that atomic SQL increments (balance = balance + amount) and version bumps
    completely eliminate lost updates under concurrent writer contention.
    """
    token, _ = create_user_and_login("concurrent_dep")
    headers = {"Authorization": f"Bearer {token}"}

    # Fetch initial state ($1,000.00 / 100,000 cents, version=1)
    me_res = client.get("/api/v1/wallets/me", headers=headers)
    assert me_res.status_code == 200
    initial_balance_cents = me_res.json()["balance_cents"]
    initial_version = me_res.json()["version"]

    deposit_amount_dollars = 20.00
    deposit_amount_cents = 2000
    num_threads = 10

    def make_deposit(index: int):
        unique_key = f"concurrent-dep-{index}-{uuid.uuid4().hex}"
        payload = {
            "amount": deposit_amount_dollars,
            "idempotency_key": unique_key,
            "description": f"Concurrent deposit #{index}"
        }
        res = client.post("/api/v1/wallets/deposit", json=payload, headers=headers)
        return res.status_code, res.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(make_deposit, i) for i in range(num_threads)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    # Assert every concurrent deposit succeeded
    for status_code, body in results:
        assert status_code == 200, f"Expected 200 OK, got {status_code}: {body}"

    # Verify final wallet balance reflects exactly 10 * $20.00 = $200.00 increase
    final_res = client.get("/api/v1/wallets/me", headers=headers)
    assert final_res.status_code == 200
    expected_cents = initial_balance_cents + (num_threads * deposit_amount_cents)
    assert final_res.json()["balance_cents"] == expected_cents
    assert final_res.json()["balance_dollars"] == round(expected_cents / 100.0, 2)
    assert final_res.json()["version"] == initial_version + num_threads

    # Verify ledger entries in the database
    db = SessionLocal()
    try:
        user_wallet = db.query(Wallet).filter(Wallet.id == final_res.json()["id"]).first()
        credit_entries = db.query(LedgerEntry).filter(
            LedgerEntry.wallet_id == user_wallet.id,
            LedgerEntry.entry_type == "CREDIT",
            LedgerEntry.amount == deposit_amount_cents
        ).all()
        assert len(credit_entries) == num_threads
    finally:
        db.close()

def test_deposit_idempotency_payload_mismatch():
    """
    Test 2: Reusing the same idempotency key with a different payload/amount
    is rejected with HTTP 400 Bad Request, preventing parameter tampering.
    """
    token, _ = create_user_and_login("dep_mismatch")
    headers = {"Authorization": f"Bearer {token}"}

    shared_key = f"key-mismatch-{uuid.uuid4().hex}"

    # First deposit: $50.00
    res1 = client.post(
        "/api/v1/wallets/deposit",
        json={"amount": 50.00, "idempotency_key": shared_key, "description": "First legitimate deposit"},
        headers=headers
    )
    assert res1.status_code == 200
    assert res1.json()["balance_cents"] == 105000

    # Second deposit with identical key but DIFFERENT amount ($150.00)
    res2 = client.post(
        "/api/v1/wallets/deposit",
        json={"amount": 150.00, "idempotency_key": shared_key, "description": "Tampered amount deposit"},
        headers=headers
    )
    assert res2.status_code == 400
    assert "parameter mismatch" in res2.json()["detail"].lower()

    # Verify wallet balance remained $1,050.00 and was not credited again
    wallet_check = client.get("/api/v1/wallets/me", headers=headers)
    assert wallet_check.status_code == 200
    assert wallet_check.json()["balance_cents"] == 105000

def test_concurrent_identical_deposit_requests():
    """
    Test 3: 3 concurrent requests with the exact same key and payload credit only once.
    All callers receive HTTP 200 with the original transaction result, without 500 errors.
    """
    token, _ = create_user_and_login("identical_reqs")
    headers = {"Authorization": f"Bearer {token}"}

    shared_key = f"replay-key-{uuid.uuid4().hex}"
    deposit_amount = 75.00
    deposit_cents = 7500

    # Fetch initial balance
    initial_res = client.get("/api/v1/wallets/me", headers=headers)
    initial_balance_cents = initial_res.json()["balance_cents"]

    def submit_identical():
        payload = {
            "amount": deposit_amount,
            "idempotency_key": shared_key,
            "description": "Idempotent payment test"
        }
        res = client.post("/api/v1/wallets/deposit", json=payload, headers=headers)
        return res.status_code, res.json()

    # Send 3 concurrent requests simultaneously with identical key and payload
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(submit_identical) for _ in range(3)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    # All three requests must succeed with 200 OK
    for status_code, body in results:
        assert status_code == 200, f"Expected 200, got {status_code}: {body}"
        assert body["balance_cents"] == initial_balance_cents + deposit_cents

    # Wallet balance must be credited exactly once
    final_res = client.get("/api/v1/wallets/me", headers=headers)
    assert final_res.json()["balance_cents"] == initial_balance_cents + deposit_cents

    # Check database: exactly 1 transaction and 1 ledger entry exist for this idempotency key
    db = SessionLocal()
    try:
        namespaced_key = f"dep:{shared_key}"
        tx_count = db.query(Transaction).filter(Transaction.idempotency_key == namespaced_key).count()
        assert tx_count == 1
    finally:
        db.close()

def test_same_raw_idempotency_key_used_for_deposit_and_transfer_without_collision():
    """
    Test 4: Same raw idempotency key used for both a deposit and a transfer.
    Operation namespacing ('dep:' prefix for deposits) ensures zero collision
    between deposit and transfer transactions in the global unique index.
    """
    alice_token, alice_user = create_user_and_login("alice_cross_op")
    bob_token, bob_user = create_user_and_login("bob_cross_op")

    alice_headers = {"Authorization": f"Bearer {alice_token}"}

    shared_raw_key = f"shared-idemp-{uuid.uuid4().hex}"

    # Alice deposits $40.00 using shared_raw_key
    dep_res = client.post(
        "/api/v1/wallets/deposit",
        json={"amount": 40.00, "idempotency_key": shared_raw_key, "description": "Alice deposit"},
        headers=alice_headers
    )
    assert dep_res.status_code == 200
    assert dep_res.json()["balance_cents"] == 104000

    # Alice transfers $15.00 to Bob using the EXACT SAME raw idempotency key
    transfer_payload = {
        "receiver_username": bob_user,
        "amount": 15.00,
        "idempotency_key": shared_raw_key,
        "description": "Lunch reimbursement"
    }
    tx_res = client.post("/api/v1/transfers", json=transfer_payload, headers=alice_headers)
    assert tx_res.status_code == 201, f"Transfer failed with cross-op collision: {tx_res.text}"

    # Verify Alice's balance: $1,000 + $40 - $15 = $1,025.00
    alice_wallet = client.get("/api/v1/wallets/me", headers=alice_headers).json()
    assert alice_wallet["balance_cents"] == 102500

    # Verify both transactions coexist in the database with their respective keys
    db = SessionLocal()
    try:
        dep_tx = db.query(Transaction).filter(Transaction.idempotency_key == f"dep:{shared_raw_key}").first()
        transfer_tx = db.query(Transaction).filter(Transaction.idempotency_key == shared_raw_key).first()
        assert dep_tx is not None
        assert transfer_tx is not None
        assert dep_tx.amount == 4000
        assert transfer_tx.amount == 1500
    finally:
        db.close()

def test_deposit_rollback_on_failure():
    """
    Test 5: Failed deposit rolls back all related records.
    If a deposit fails (e.g. suspended wallet or invalid state),
    no orphan Transaction or LedgerEntry records are left behind,
    and wallet balance remains untouched.
    """
    token, username = create_user_and_login("suspended_user")
    headers = {"Authorization": f"Bearer {token}"}

    # Provision wallet and then freeze it in the database
    db = SessionLocal()
    try:
        user_record = db.query(User).filter(User.username == username).first()
        user_id = user_record.id
        wallet_record = db.query(Wallet).filter(Wallet.user_id == user_id).first()
        if not wallet_record:
            # Trigger lazy provisioning
            client.get("/api/v1/wallets/me", headers=headers)
            wallet_record = db.query(Wallet).filter(Wallet.user_id == user_id).first()

        balance_before = wallet_record.balance
        wallet_id = wallet_record.id
        wallet_record.status = "FROZEN"
        db.commit()
    finally:
        db.close()

    failed_key = f"failed-dep-{uuid.uuid4().hex}"
    res = client.post(
        "/api/v1/wallets/deposit",
        json={"amount": 100.00, "idempotency_key": failed_key, "description": "Deposit to frozen wallet"},
        headers=headers
    )
    assert res.status_code == 400
    assert "status: frozen" in res.json()["detail"].lower()

    # Verify complete rollback: no orphan Transaction, no orphan LedgerEntry, balance intact
    db = SessionLocal()
    try:
        orphaned_tx = db.query(Transaction).filter(Transaction.idempotency_key == f"dep:{failed_key}").first()
        assert orphaned_tx is None

        refreshed_wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
        assert refreshed_wallet.balance == balance_before

        orphaned_ledger = db.query(LedgerEntry).filter(
            LedgerEntry.wallet_id == wallet_id,
            LedgerEntry.amount == 10000
        ).first()
        assert orphaned_ledger is None
    finally:
        db.close()
