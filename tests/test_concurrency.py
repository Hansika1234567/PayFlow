import uuid
import concurrent.futures
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

def test_concurrent_transfers_and_conservation_of_money():
    """
    RACE CONDITION & CONCURRENCY STRESS TEST:
    Spawns 10 concurrent threads running bidirectional transfers simultaneously
    between User A and User B.
    Proves:
    1. Deterministic lock ordering eliminates circular wait deadlocks.
    2. Concurrency control prevents race conditions / phantom updates.
    3. Total money across both accounts is 100% conserved (no drift).
    """
    token_a, user_a = create_user_and_login("concurrent_a")
    token_b, user_b = create_user_and_login("concurrent_b")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Initial state: Each has $1,000.00 (100,000 cents). Total = $2,000.00.
    initial_total_dollars = 2000.0

    # Task definition:
    # 5 transfers: A -> B of $20.00 each (Total A->B: $100)
    # 5 transfers: B -> A of $15.00 each (Total B->A: $75)
    # Net expected: A has $975.00, B has $1,025.00. Total remains $2,000.00.
    
    tasks = []
    for i in range(5):
        tasks.append((
            headers_a,
            {
                "receiver_username": user_b,
                "amount": 20.00,
                "idempotency_key": f"concur-a-to-b-{i}-{uuid.uuid4()}",
                "description": f"Concurrent A to B #{i}"
            }
        ))
    for j in range(5):
        tasks.append((
            headers_b,
            {
                "receiver_username": user_a,
                "amount": 15.00,
                "idempotency_key": f"concur-b-to-a-{j}-{uuid.uuid4()}",
                "description": f"Concurrent B to A #{j}"
            }
        ))

    def execute_single_transfer(task_item):
        headers, payload = task_item
        # Create a fresh TestClient per thread to simulate true concurrent clients
        thread_client = TestClient(app)
        response = thread_client.post("/api/v1/transfers", json=payload, headers=headers)
        return response.status_code, response.json()

    # Execute all 10 transfers concurrently using 10 worker threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(execute_single_transfer, tasks))

    # Assert every single concurrent transfer succeeded with HTTP 201
    for status_code, body in results:
        assert status_code == 201, f"Transfer failed with code {status_code}: {body}"
        assert body["status"] == "COMPLETED"

    # Verify final balances
    wallet_a = client.get("/api/v1/wallets/me", headers=headers_a).json()
    wallet_b = client.get("/api/v1/wallets/me", headers=headers_b).json()

    expected_a = 1000.0 - (5 * 20.0) + (5 * 15.0)  # $975.00
    expected_b = 1000.0 + (5 * 20.0) - (5 * 15.0)  # $1,025.00

    assert wallet_a["balance_dollars"] == expected_a, f"Expected {expected_a}, got {wallet_a['balance_dollars']}"
    assert wallet_b["balance_dollars"] == expected_b, f"Expected {expected_b}, got {wallet_b['balance_dollars']}"

    # Conservation of Money invariant check
    final_total_dollars = wallet_a["balance_dollars"] + wallet_b["balance_dollars"]
    assert final_total_dollars == initial_total_dollars, f"Conservation violation! Expected {initial_total_dollars}, got {final_total_dollars}"
