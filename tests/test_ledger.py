import uuid
import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def create_user_and_login(username_prefix: str):
    """Helper to register a new user and return auth token and username."""
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
    assert res.status_code == 201
    return res.json()["access_token"], username

def test_ledger_initial_welcome_credit():
    """Verify that every new user has an initial CREDIT ledger entry of $1,000.00."""
    token, _ = create_user_and_login("ledger_init")
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/v1/ledger", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    first_entry = data["items"][0]
    assert first_entry["entry_type"] == "CREDIT"
    assert first_entry["amount_dollars"] == 1000.0

def test_ledger_debit_and_credit_filtering():
    """Verify ledger filtering by DEBIT and CREDIT after executing a transfer."""
    alice_token, alice_user = create_user_and_login("alice_ldg")
    _, bob_user = create_user_and_login("bob_ldg")

    alice_headers = {"Authorization": f"Bearer {alice_token}"}

    # Alice sends $200.00 to Bob
    client.post("/api/v1/transfers", json={
        "receiver_username": bob_user,
        "amount": 200.00,
        "idempotency_key": f"ldg-{uuid.uuid4()}",
        "description": "Ledger test payment"
    }, headers=alice_headers)

    # 1. Fetch all ledger items
    all_res = client.get("/api/v1/ledger", headers=alice_headers).json()
    assert all_res["total"] >= 2  # 1 initial credit + 1 debit

    # 2. Filter DEBIT only
    debit_res = client.get("/api/v1/ledger?entry_type=DEBIT", headers=alice_headers).json()
    assert len(debit_res["items"]) >= 1
    for item in debit_res["items"]:
        assert item["entry_type"] == "DEBIT"
    assert debit_res["items"][0]["amount_dollars"] == 200.00
    assert debit_res["items"][0]["balance_after_dollars"] == 800.00

    # 3. Filter CREDIT only
    credit_res = client.get("/api/v1/ledger?entry_type=CREDIT", headers=alice_headers).json()
    assert len(credit_res["items"]) >= 1
    for item in credit_res["items"]:
        assert item["entry_type"] == "CREDIT"

def test_ledger_pagination():
    """Verify that pagination limits and offsets slice ledger results correctly."""
    alice_token, _ = create_user_and_login("alice_page")
    alice_headers = {"Authorization": f"Bearer {alice_token}"}

    # Make 3 separate deposits of $10 each
    for i in range(3):
        client.post("/api/v1/wallets/deposit", json={"amount": 10.0 + i}, headers=alice_headers)

    # Page 1: limit 2, offset 0
    p1 = client.get("/api/v1/ledger?limit=2&offset=0", headers=alice_headers).json()
    assert len(p1["items"]) == 2
    assert p1["has_more"] is True

    # Page 2: limit 2, offset 2
    p2 = client.get("/api/v1/ledger?limit=2&offset=2", headers=alice_headers).json()
    assert len(p2["items"]) >= 1
    # Items on p1 and p2 must not overlap
    p1_ids = {item["id"] for item in p1["items"]}
    p2_ids = {item["id"] for item in p2["items"]}
    assert len(p1_ids.intersection(p2_ids)) == 0

def test_transactions_history_endpoint():
    """Verify high-level transaction history endpoint returns SENT and RECEIVED items."""
    alice_token, alice_user = create_user_and_login("tx_alice")
    bob_token, bob_user = create_user_and_login("tx_bob")

    alice_headers = {"Authorization": f"Bearer {alice_token}"}
    bob_headers = {"Authorization": f"Bearer {bob_token}"}

    # Alice sends $50.00 to Bob
    client.post("/api/v1/transfers", json={
        "receiver_username": bob_user,
        "amount": 50.00,
        "idempotency_key": f"hist-{uuid.uuid4()}",
        "description": "Movie tickets"
    }, headers=alice_headers)

    # Check Alice history (should see SENT)
    alice_hist = client.get("/api/v1/transactions", headers=alice_headers).json()
    sent_items = [t for t in alice_hist["items"] if t["type"] == "SENT"]
    assert len(sent_items) >= 1
    assert sent_items[0]["counterparty_username"] == bob_user
    assert sent_items[0]["amount_dollars"] == 50.00

    # Check Bob history (should see RECEIVED)
    bob_hist = client.get("/api/v1/transactions", headers=bob_headers).json()
    received_items = [t for t in bob_hist["items"] if t["type"] == "RECEIVED"]
    assert len(received_items) >= 1
    assert received_items[0]["counterparty_username"] == alice_user
    assert received_items[0]["amount_dollars"] == 50.00

def test_ledger_database_level_immutability():
    """
    Priority 4 Test:
    Verifies that the database engine itself enforces ledger append-only immutability.
    Direct SQL UPDATE and DELETE statements on ledger_entries must be aborted by database triggers.
    """
    from backend.database import SessionLocal
    from sqlalchemy import text
    from sqlalchemy.exc import DatabaseError

    db = SessionLocal()
    try:
        # Get any existing ledger entry
        first_entry = db.execute(text("SELECT id, amount FROM ledger_entries LIMIT 1;")).fetchone()
        assert first_entry is not None, "At least one ledger entry must exist for immutability testing"
        entry_id = first_entry[0]
        original_amount = first_entry[1]

        # 1. Attempt an UPDATE mutation on ledger_entries -> Must be aborted by trigger
        with pytest.raises(DatabaseError) as exc_info:
            db.execute(text(f"UPDATE ledger_entries SET amount = {original_amount + 5000} WHERE id = {entry_id};"))
            db.commit()
        db.rollback()
        assert "immutable" in str(exc_info.value).lower()

        # 2. Attempt a DELETE mutation on ledger_entries -> Must be aborted by trigger
        with pytest.raises(DatabaseError) as exc_info_del:
            db.execute(text(f"DELETE FROM ledger_entries WHERE id = {entry_id};"))
            db.commit()
        db.rollback()
        assert "cannot be deleted" in str(exc_info_del.value).lower()

        # 3. Confirm entry was not modified or deleted
        verified = db.execute(text(f"SELECT amount FROM ledger_entries WHERE id = {entry_id};")).fetchone()
        assert verified[0] == original_amount
    finally:
        db.close()

def test_ledger_mathematical_reconciliation():
    """
    Priority 4 Test:
    Mathematical Ledger Reconciliation:
    Proves that for any account, Current Balance == Sum(CREDIT) - Sum(DEBIT).
    Also proves that every transfer generates exactly 1 DEBIT and 1 CREDIT with matching amounts.
    """
    alice_token, alice_user = create_user_and_login("recon_alice")
    bob_token, bob_user = create_user_and_login("recon_bob")

    alice_headers = {"Authorization": f"Bearer {alice_token}"}
    bob_headers = {"Authorization": f"Bearer {bob_token}"}

    # Alice deposits $300.50
    dep_res = client.post("/api/v1/wallets/deposit", json={"amount": 300.50}, headers=alice_headers)
    assert dep_res.status_code == 200

    # Alice sends $125.25 to Bob
    tx1_res = client.post("/api/v1/transfers", json={
        "receiver_username": bob_user,
        "amount": 125.25,
        "idempotency_key": f"recon-tx1-{uuid.uuid4()}",
        "description": "Reconciliation transfer 1"
    }, headers=alice_headers)
    assert tx1_res.status_code == 201

    # Bob sends $40.10 back to Alice
    tx2_res = client.post("/api/v1/transfers", json={
        "receiver_username": alice_user,
        "amount": 40.10,
        "idempotency_key": f"recon-tx2-{uuid.uuid4()}",
        "description": "Reconciliation transfer 2"
    }, headers=bob_headers)
    assert tx2_res.status_code == 201

    # Fetch Alice's full ledger
    alice_ldg = client.get("/api/v1/ledger?limit=100", headers=alice_headers).json()["items"]
    # Fetch Bob's full ledger
    bob_ldg = client.get("/api/v1/ledger?limit=100", headers=bob_headers).json()["items"]

    # Calculate mathematical reconciliation for Alice:
    alice_credits = sum(item["amount_cents"] for item in alice_ldg if item["entry_type"] == "CREDIT")
    alice_debits = sum(item["amount_cents"] for item in alice_ldg if item["entry_type"] == "DEBIT")
    alice_reconciled_cents = alice_credits - alice_debits

    alice_wallet = client.get("/api/v1/wallets/me", headers=alice_headers).json()
    assert alice_wallet["balance_cents"] == alice_reconciled_cents, (
        f"Reconciliation error for Alice! Wallet: {alice_wallet['balance_cents']} vs Ledger: {alice_reconciled_cents}"
    )

    # Calculate mathematical reconciliation for Bob:
    bob_credits = sum(item["amount_cents"] for item in bob_ldg if item["entry_type"] == "CREDIT")
    bob_debits = sum(item["amount_cents"] for item in bob_ldg if item["entry_type"] == "DEBIT")
    bob_reconciled_cents = bob_credits - bob_debits

    bob_wallet = client.get("/api/v1/wallets/me", headers=bob_headers).json()
    assert bob_wallet["balance_cents"] == bob_reconciled_cents, (
        f"Reconciliation error for Bob! Wallet: {bob_wallet['balance_cents']} vs Ledger: {bob_reconciled_cents}"
    )

    # Double-Entry Pairing Check for tx1:
    from backend.database import SessionLocal
    from backend.models.ledger import LedgerEntry
    db = SessionLocal()
    try:
        tx1_id = tx1_res.json()["transaction_id"]
        tx1_entries = db.query(LedgerEntry).filter(LedgerEntry.transaction_id == tx1_id).all()
        assert len(tx1_entries) == 2, f"Expected exactly 2 ledger entries for tx1, found {len(tx1_entries)}"

        entry_types = {e.entry_type for e in tx1_entries}
        assert entry_types == {"DEBIT", "CREDIT"}

        debit = next(e for e in tx1_entries if e.entry_type == "DEBIT")
        credit = next(e for e in tx1_entries if e.entry_type == "CREDIT")
        assert debit.amount == credit.amount == 12525
        assert debit.amount == tx1_res.json()["amount_cents"]
    finally:
        db.close()

