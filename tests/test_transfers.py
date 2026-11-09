import uuid
import pytest
from fastapi.testclient import TestClient
from backend.main import app

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
    assert res.status_code == 201
    token = res.json()["access_token"]
    return token, username

def test_wallet_deposit():
    """Test simulating a deposit into the user's wallet."""
    token, _ = create_user_and_login("depo_user")
    headers = {"Authorization": f"Bearer {token}"}

    # Initial balance is $1000.00 (100,000 cents)
    me_res = client.get("/api/v1/wallets/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["balance_dollars"] == 1000.0

    # Deposit $250.50
    deposit_res = client.post("/api/v1/wallets/deposit", json={"amount": 250.50}, headers=headers)
    assert deposit_res.status_code == 200
    assert deposit_res.json()["balance_dollars"] == 1250.50
    assert deposit_res.json()["balance_cents"] == 125050

def test_successful_transfer_and_double_entry_balance_conservation():
    """
    Test transferring money from User A to User B.
    Validates atomic balance conservation and double-entry bookkeeping.
    """
    alice_token, alice_user = create_user_and_login("alice_transfer")
    bob_token, bob_user = create_user_and_login("bob_transfer")

    alice_headers = {"Authorization": f"Bearer {alice_token}"}
    bob_headers = {"Authorization": f"Bearer {bob_token}"}

    # Transfer $150.00 from Alice to Bob
    idemp_key = f"tx-{uuid.uuid4()}"
    transfer_payload = {
        "receiver_username": bob_user,
        "amount": 150.00,
        "idempotency_key": idemp_key,
        "description": "Lunch payment split"
    }

    tx_res = client.post("/api/v1/transfers", json=transfer_payload, headers=alice_headers)
    assert tx_res.status_code == 201
    receipt = tx_res.json()

    assert receipt["sender_username"] == alice_user
    assert receipt["receiver_username"] == bob_user
    assert receipt["amount_dollars"] == 150.00
    assert receipt["amount_cents"] == 15000
    assert receipt["status"] == "COMPLETED"
    assert receipt["sender_balance_after_dollars"] == 850.00

    # Verify Alice's balance decreased to $850.00
    alice_wallet = client.get("/api/v1/wallets/me", headers=alice_headers).json()
    assert alice_wallet["balance_dollars"] == 850.00

    # Verify Bob's balance increased to $1150.00
    bob_wallet = client.get("/api/v1/wallets/me", headers=bob_headers).json()
    assert bob_wallet["balance_dollars"] == 1150.00

def test_idempotency_prevents_duplicate_charge():
    """
    Test that resending a transfer with the exact same idempotency key
    returns the original transaction receipt without double-charging!
    """
    alice_token, alice_user = create_user_and_login("alice_idemp")
    _, bob_user = create_user_and_login("bob_idemp")
    alice_headers = {"Authorization": f"Bearer {alice_token}"}

    fixed_idemp_key = f"fixed-idemp-{uuid.uuid4()}"
    payload = {
        "receiver_username": bob_user,
        "amount": 50.00,
        "idempotency_key": fixed_idemp_key,
        "description": "Idempotent payment"
    }

    # First attempt: 201 Created
    res1 = client.post("/api/v1/transfers", json=payload, headers=alice_headers)
    assert res1.status_code == 201
    tx_id_1 = res1.json()["transaction_id"]

    # Second attempt with IDENTICAL key (e.g. client network retry):
    res2 = client.post("/api/v1/transfers", json=payload, headers=alice_headers)
    assert res2.status_code == 201
    tx_id_2 = res2.json()["transaction_id"]

    # Must return identical transaction ID
    assert tx_id_1 == tx_id_2

    # Verify Alice was only charged ONCE ($1000 - $50 = $950, NOT $900!)
    alice_wallet = client.get("/api/v1/wallets/me", headers=alice_headers).json()
    assert alice_wallet["balance_dollars"] == 950.00

def test_insufficient_funds_rejection():
    """Test that attempting to transfer more than available balance returns 400 and preserves balance."""
    alice_token, alice_user = create_user_and_login("alice_broke")
    _, bob_user = create_user_and_login("bob_target")
    alice_headers = {"Authorization": f"Bearer {alice_token}"}

    payload = {
        "receiver_username": bob_user,
        "amount": 50000.00,  # $50k > $1k initial balance
        "idempotency_key": f"fail-{uuid.uuid4()}",
    }

    res = client.post("/api/v1/transfers", json=payload, headers=alice_headers)
    assert res.status_code == 400
    assert "Insufficient funds" in res.json()["detail"]

    # Verify Alice balance is intact
    alice_wallet = client.get("/api/v1/wallets/me", headers=alice_headers).json()
    assert alice_wallet["balance_dollars"] == 1000.00

def test_self_transfer_rejection():
    """Test that users cannot transfer money to themselves."""
    alice_token, alice_user = create_user_and_login("alice_self")
    alice_headers = {"Authorization": f"Bearer {alice_token}"}

    payload = {
        "receiver_username": alice_user,
        "amount": 25.00,
        "idempotency_key": f"self-{uuid.uuid4()}",
    }

    res = client.post("/api/v1/transfers", json=payload, headers=alice_headers)
    assert res.status_code == 400
    assert "Self-transfers are not permitted" in res.json()["detail"]

def test_transfer_to_nonexistent_user():
    """Test transferring to a user that doesn't exist returns 404."""
    alice_token, _ = create_user_and_login("alice_ghost")
    alice_headers = {"Authorization": f"Bearer {alice_token}"}

    payload = {
        "receiver_username": "non_existent_ghost_99999",
        "amount": 10.00,
        "idempotency_key": f"ghost-{uuid.uuid4()}",
    }

    res = client.post("/api/v1/transfers", json=payload, headers=alice_headers)
    assert res.status_code == 404
    assert "does not exist" in res.json()["detail"]

def test_money_precision_validation():
    """
    Priority 1 Precision Test:
    Verifies that fractional cents (e.g. 10.005, 10.999), zero, negative amounts,
    and amounts exceeding $1,000,000 are rejected with 422, while exact 2-decimal amounts
    (10.50) are accepted and computed with exact integer cents.
    """
    alice_token, _ = create_user_and_login("prec_alice")
    _, bob_user = create_user_and_login("prec_bob")
    alice_headers = {"Authorization": f"Bearer {alice_token}"}

    def try_transfer(amount_val):
        return client.post("/api/v1/transfers", json={
            "receiver_username": bob_user,
            "amount": amount_val,
            "idempotency_key": f"prec-{uuid.uuid4()}",
        }, headers=alice_headers)

    # 1. Reject 10.005 (3 decimal places) -> 422
    res_005 = try_transfer(10.005)
    assert res_005.status_code == 422
    assert "more than 2 decimal places" in str(res_005.json())

    # 2. Reject 10.999 (3 decimal places) -> 422
    res_999 = try_transfer(10.999)
    assert res_999.status_code == 422
    assert "more than 2 decimal places" in str(res_999.json())

    # 3. Accept 10.50 (exact 2 decimals) -> 201 Created
    res_50 = try_transfer(10.50)
    assert res_50.status_code == 201
    assert res_50.json()["amount_cents"] == 1050
    assert res_50.json()["amount_dollars"] == 10.50

    # 4. Reject zero amount (0 and 0.00) -> 422
    res_zero = try_transfer(0)
    assert res_zero.status_code == 422

    res_zero_dec = try_transfer(0.00)
    assert res_zero_dec.status_code == 422

    # 5. Reject negative amount (-5.00) -> 422
    res_neg = try_transfer(-5.00)
    assert res_neg.status_code == 422

    # 6. Reject amount exceeding $1,000,000.00 -> 422
    res_excess = try_transfer(1000000.01)
    assert res_excess.status_code == 422
    assert "exceeds maximum" in str(res_excess.json())

def test_idempotency_payload_mismatch_rejection():
    """
    Priority 2 Test:
    Verifies that reusing the same idempotency key with different parameters
    (different amount or different recipient) returns HTTP 400 Bad Request.
    """
    alice_token, alice_user = create_user_and_login("mismatch_alice")
    _, bob_user = create_user_and_login("mismatch_bob")
    _, charlie_user = create_user_and_login("mismatch_charlie")
    alice_headers = {"Authorization": f"Bearer {alice_token}"}

    reused_key = f"key-reuse-{uuid.uuid4()}"

    # 1. First transfer succeeds: $40.00 to Bob
    first_res = client.post("/api/v1/transfers", json={
        "receiver_username": bob_user,
        "amount": 40.00,
        "idempotency_key": reused_key,
        "description": "Original payment"
    }, headers=alice_headers)
    assert first_res.status_code == 201

    # 2. Reuse SAME key with DIFFERENT AMOUNT ($80.00 instead of $40.00)
    diff_amount_res = client.post("/api/v1/transfers", json={
        "receiver_username": bob_user,
        "amount": 80.00,
        "idempotency_key": reused_key,
        "description": "Tampered payment with same key"
    }, headers=alice_headers)
    assert diff_amount_res.status_code == 400
    assert "parameter mismatch" in diff_amount_res.json()["detail"]

    # 3. Reuse SAME key with DIFFERENT RECIPIENT (Charlie instead of Bob)
    diff_recipient_res = client.post("/api/v1/transfers", json={
        "receiver_username": charlie_user,
        "amount": 40.00,
        "idempotency_key": reused_key,
        "description": "Redirected payment with same key"
    }, headers=alice_headers)
    assert diff_recipient_res.status_code == 400
    assert "parameter mismatch" in diff_recipient_res.json()["detail"]

    # 4. Verify Alice was only charged ONCE ($1000 - $40 = $960)
    alice_wallet = client.get("/api/v1/wallets/me", headers=alice_headers).json()
    assert alice_wallet["balance_dollars"] == 960.00

def test_concurrent_requests_sharing_same_idempotency_key():
    """
    Priority 2 Test:
    Verifies that simultaneous concurrent requests sharing the exact same idempotency key
    safely resolve without unhandled IntegrityError or double deduction.
    Both concurrent requests must return HTTP 201 with identical transaction IDs.
    """
    import concurrent.futures

    alice_token, _ = create_user_and_login("race_key_alice")
    _, bob_user = create_user_and_login("race_key_bob")
    alice_headers = {"Authorization": f"Bearer {alice_token}"}

    shared_key = f"shared-race-key-{uuid.uuid4()}"
    payload = {
        "receiver_username": bob_user,
        "amount": 35.00,
        "idempotency_key": shared_key,
        "description": "Concurrent duplicate key test"
    }

    def fire_request(_):
        thread_client = TestClient(app)
        return thread_client.post("/api/v1/transfers", json=payload, headers=alice_headers)

    # Fire 3 concurrent threads simultaneously with identical payload & idempotency key
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        responses = list(executor.map(fire_request, range(3)))

    # All should return 201 Created (or at least 200/201 success)
    tx_ids = set()
    for r in responses:
        assert r.status_code in [200, 201], f"Unexpected status {r.status_code}: {r.json()}"
        tx_ids.add(r.json()["transaction_id"])

    # All successful responses must point to the EXACT same transaction
    assert len(tx_ids) == 1, f"Expected 1 unique transaction ID, got: {tx_ids}"

    # Verify Alice was charged exactly ONCE ($1000 - $35 = $965)
    alice_wallet = client.get("/api/v1/wallets/me", headers=alice_headers).json()
    assert alice_wallet["balance_dollars"] == 965.00


