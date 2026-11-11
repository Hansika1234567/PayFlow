# PayFlow – Digital Wallet & Transaction Management System

A simulated digital wallet and financial ledger system built with **Python (FastAPI)**, **SQLAlchemy ORM**, and **React**. Designed specifically to demonstrate core backend systems engineering and transactional integrity concepts evaluated in FinTech software engineering (e.g. double-entry accounting, atomic balance updates, deterministic locking, and idempotency).

---

## 1. Project Overview & Architecture

Unlike toy wallet applications that simply execute `balance -= amount`, PayFlow enforces:
1. **Double-Entry Bookkeeping**: Every transfer of `$X` generates two immutable, synchronized ledger entries: a `DEBIT` on the sender and a `CREDIT` on the receiver.
2. **Pessimistic Concurrency Control**: Deterministic lock ordering (`min(wallet_a, wallet_b)` then `max(...)`) prevents circular wait deadlocks during concurrent bidirectional transfers.
3. **Atomic SQL Mutations**: Balance updates execute directly on the database engine (`UPDATE wallets SET balance = balance - :amount`) to prevent in-memory read-modify-write lost updates.
4. **Idempotency Protection**: Client-provided UUID idempotency keys prevent duplicate deductions on network drop retries.
5. **Exact Integer-Cents Arithmetic**: Monetary amounts are stored in integer cents (`BigInteger`) to eliminate IEEE-754 floating-point drift.

### System Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                   CLIENT LAYER (React 19 + Tailwind CSS)               │
│  - Wallet Balance & Status                                             │
│  - Send Money Modal with Idempotency Replay Demonstrator               │
│  - Double-Entry Ledger Feed (Debit / Credit Filter & Snapshots)        │
│  - Live Concurrency Stress Test Demonstrator (10 Parallel Transfers)  │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ HTTP REST (/api/v1/*)
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  REVERSE PROXY & GATEWAY (Port 3000)                   │
│  - Proxies `/api/*`, `/docs`, and `/openapi.json` to FastAPI (Port 8005)│
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     FASTAPI APPLICATION BACKEND                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Routers: /auth, /wallets, /transfers, /ledger                    │  │
│  ├──────────────────────────────────────────────────────────────────┤  │
│  │ Security: Bcrypt Password Hashing + JWT HMAC-SHA256 Bearer Token │  │
│  ├──────────────────────────────────────────────────────────────────┤  │
│  │ Services:                                                        │  │
│  │   - transfer_service.py: Atomic transfers & lock ordering        │  │
│  │   - ledger_service.py: Double-entry audit queries & pagination   │  │
│  │   - wallet_service.py: Deposit ingestion & balance queries       │  │
│  │   - user_service.py: Auth & auto-wallet provisioning ($1,000)    │  │
│  └─────────────────────────────────┬────────────────────────────────┘  │
└────────────────────────────────────┼───────────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│              PERSISTENCE LAYER (SQLAlchemy 2.0 ORM)                    │
│  - SQLite (WAL mode, busy_timeout=15000, BEGIN IMMEDIATE hook)         │
│  - PostgreSQL compatibility implemented (live integration testing pending) │
│  - Tables: users, wallets, transactions, ledger_entries                │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Database Schema & Double-Entry Ledger

```
users (1) ────────── (1) wallets (1) ────────── (*) ledger_entries (*) ────────── (1) transactions
```

### Table Definitions

- **`users`**:
  - `id`: Integer PK
  - `email`: VARCHAR(255) UNIQUE INDEX
  - `username`: VARCHAR(50) UNIQUE INDEX
  - `hashed_password`: VARCHAR(255) (Bcrypt salted hash)
  - `full_name`: VARCHAR(100)
  - `is_active`: BOOLEAN

- **`wallets`**:
  - `id`: Integer PK
  - `user_id`: Integer FK -> `users.id` (UNIQUE)
  - `balance`: BIGINT (Stored in integer cents: `$100.50` = `10050`)
  - `currency`: VARCHAR(3) (`USD`)
  - `status`: VARCHAR(20) (`ACTIVE`, `FROZEN`)
  - `version`: Integer (Optimistic locking tag)

- **`transactions`**:
  - `id`: VARCHAR(36) UUID PK
  - `idempotency_key`: VARCHAR(64) UNIQUE INDEX
  - `sender_wallet_id`: Integer FK -> `wallets.id`
  - `receiver_wallet_id`: Integer FK -> `wallets.id`
  - `amount`: BIGINT (cents)
  - `status`: VARCHAR(20) (`COMPLETED`, `PENDING`, `FAILED`)
  - `description`: VARCHAR(255)

- **`ledger_entries`**:
  - `id`: Integer PK
  - `transaction_id`: VARCHAR(36) FK -> `transactions.id`
  - `wallet_id`: Integer FK -> `wallets.id`
  - `entry_type`: VARCHAR(10) (`DEBIT` or `CREDIT`)
  - `amount`: BIGINT (cents, strictly positive)
  - `balance_after`: BIGINT (balance snapshot immediately after entry)

---

## 3. Five Critical Engineering Decisions (Interview Defense)

### 1. Why Integer Cents Instead of Floats?
Binary floating point representations (IEEE-754) cannot accurately represent decimal fractions like `0.1` or `0.01` in base-2 (e.g. `0.1 + 0.2 = 0.30000000000000004`). In a system processing thousands of transactions, accumulated rounding error leads to catastrophic financial drift. PayFlow enforces integer cents throughout the ORM, services, and arithmetic.

### 2. How Deterministic Lock Ordering Prevents Transfer Deadlocks
A deadlock requires **Circular Wait**. If Alice sends to Bob while Bob sends to Alice simultaneously:
- Thread 1 locks Alice and waits for Bob.
- Thread 2 locks Bob and waits for Alice.
- Both threads freeze waiting on each other.

**PayFlow Solution**:
```python
first_id = min(sender_wallet.id, receiver_wallet.id)
second_id = max(sender_wallet.id, receiver_wallet.id)

wallet_a = db.query(Wallet).filter(Wallet.id == first_id).with_for_update().first()
wallet_b = db.query(Wallet).filter(Wallet.id == second_id).with_for_update().first()
```
Because both concurrent threads acquire the lower ID first, Thread 2 waits before locking any resource needed by Thread 1. This deterministic acquisition ordering eliminates circular wait conditions for two-wallet transfer pairs, significantly reducing deadlock risks (although broader multi-table locks, cascade triggers, or concurrent schema operations can still require deadlock handling in full production systems).

### 3. Atomic SQL Mutations vs. In-Memory Subtraction
In standard Python code:
```python
# VULNERABLE TO LOST UPDATES
wallet.balance -= amount
db.commit()
```
If two requests read `1000` simultaneously, both calculate `980`, and both write `980`, dropping one $20 debit.
PayFlow executes atomic SQL expressions:
```python
db.execute(
    update(Wallet)
    .where(Wallet.id == locked_sender.id)
    .values(balance=Wallet.balance - amount_cents, version=Wallet.version + 1)
)
```
The arithmetic is performed directly by the database engine inside the row lock.

### 4. Client Idempotency Keys (The Stripe / PayPal Pattern)
When a mobile app or browser sends a transfer request, network timeouts can cause the client to drop connection before receiving the response. Without idempotency, retrying charges the customer twice.
In PayFlow:
- Client generates an `idempotency_key` (UUIDv4).
- If the server has already processed this key with status `COMPLETED`, it immediately returns the stored transaction receipt without re-executing any mutations.

### 5. Double-Entry Bookkeeping
A simple mutable balance column destroys auditability. If an audit is required, PayFlow can verify the integrity of any wallet at any time:
$$\text{Wallet Balance} = \sum \text{CREDIT} - \sum \text{DEBIT}$$
Every balance mutation has a permanent, tamper-evident counterpart in `ledger_entries`.

---

## 4. API Endpoints

### Authentication
- `POST /api/v1/auth/register`: Create user and auto-provision wallet with $1,000.00 test credit.
- `POST /api/v1/auth/login`: Authenticate and receive signed JWT.
- `GET /api/v1/auth/me`: Fetch authenticated profile and wallet summary.

### Wallets
- `GET /api/v1/wallets/me`: Get current balance and status.
- `POST /api/v1/wallets/deposit`: Deposit test funds (generates `CREDIT` ledger entry).

### Transfers
- `POST /api/v1/transfers`: Execute atomic transfer with idempotency key.
- `GET /api/v1/transfers/{id}`: Get transfer receipt.

### Ledger & History
- `GET /api/v1/ledger`: Query double-entry ledger with `entry_type` filter (`DEBIT`/`CREDIT`) and pagination.
- `GET /api/v1/transactions`: Query transaction history (`SENT` / `RECEIVED`).

---

---

## 5. Automated Testing Suite

PayFlow includes **37 automated Pytest tests** (passing with 2 deprecation warnings from upstream dependencies) covering unit, integration, multi-threaded concurrency, deposit idempotency, mathematical reconciliation, and safety scenarios:

```bash
# Run all tests
python3 -m pytest tests/ -v
```

### Verified Test Breakdown (37/37 Passing, 2 Warnings):
- `tests/test_health.py` (2 tests): Database ping and OpenAPI schema generation.
- `tests/test_auth.py` (7 tests): Registration, duplicate prevention, password hashing, JWT bearer enforcement, production secret key validation rejection, and dynamic CORS headers.
- `tests/test_transfers.py` (9 tests): Atomic transfers, double-entry balance conservation, idempotency replay protection, insufficient balance rejection, self-transfer rejection, nonexistent user handling, strict 2-decimal scale validation, idempotency parameter mismatch rejection (HTTP 400), and concurrent duplicate key collision resolution.
- `tests/test_deposits.py` (5 tests): Concurrent deposits with distinct keys, deposit idempotency payload mismatch rejection (HTTP 400), concurrent identical deposit replay deduplication, deposit/transfer idempotency namespace isolation, and atomic rollback on deposit failure.
- `tests/test_ledger.py` (6 tests): Welcome credit recording, DEBIT/CREDIT filtering, pagination slicing, high-level transaction feed, database-level trigger immutability enforcement, and complete mathematical balance reconciliation ($\text{Balance} == \sum \text{Credits} - \sum \text{Debits}$).
- `tests/test_concurrency.py` (1 test): **10-thread parallel executor stress test** running simultaneous bidirectional transfers to verify race condition resilience and 100% money conservation.
- `tests/test_postgres_compatibility.py` (7 tests): Engine pool configuration, integer-only money formatting (`divmod`), BIGINT check constraints, helper transaction ownership (`auto_commit=False`), read-only `GET /wallets/me`, strict test database safety validator, and Alembic PostgreSQL trigger definitions. *(Note: PostgreSQL schema and code compatibility are implemented and verified in the test suite; real integration testing against an external PostgreSQL database is pending).*

---

## 6. Critical Reliability Improvements (Audited & Verified)

1. **Exact Monetary Precision**: Input amounts are validated using Pydantic v2 and Python's `Decimal` module. Amounts with $>2$ decimal places (e.g. `10.005`), non-positive amounts, or amounts $> \$1,000,000.00$ are rejected with HTTP 422. Validated amounts are converted to exact integer cents (`amount_cents = int(amount * 100)`).
2. **Idempotency Fingerprinting & Collision Recovery**: Transfer parameters (`sender_wallet_id`, `receiver_username`, `amount_cents`) are hashed using SHA-256 and stored with the transaction. Reusing an idempotency key with different parameters returns HTTP 400 Bad Request. Concurrent requests sharing the same key are caught on database `IntegrityError`, safely rolled back, and the winning receipt is returned without duplicate deduction.
3. **Database Concurrency & Kernel-Level Invariant**: SQLite operates with `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=15000`, and an engine listener issuing `BEGIN IMMEDIATE` to prevent read-to-write lock escalation deadlocks. Balances are mutated using conditional atomic updates (`UPDATE wallets SET balance = balance - :amount WHERE id = :id AND balance >= :amount`) preventing negative balances under all race conditions.
4. **Ledger Immutability & Mathematical Reconciliation**: Zero API routes exist to mutate or delete ledger entries. In addition, database triggers (`prevent_ledger_update` and `prevent_ledger_delete`) abort any raw SQL update or delete operations. An automated reconciliation test verifies that $\text{Balance} == \sum \text{Credit} - \sum \text{Debit}$ for all accounts.
5. **Security Hardening**: The settings configuration enforces that if `ENVIRONMENT == "production"`, insecure fallback secrets are rejected at startup with a `ValidationError`. Allowed CORS origins are dynamically configured from environment variables.

---

## 7. Top 10 FinTech Interview Questions & Answers

1. **Q: What are the ACID properties in this wallet system?**
   - **Atomicity**: The sender debit, receiver credit, transaction record, and two ledger entries all commit or all rollback together.
   - **Consistency**: Invariant $\sum \text{All Balances} = \text{Constant}$ holds across all transfers.
   - **Isolation**: Row locking and atomic SQL expressions prevent dirty reads and lost updates.
   - **Durability**: Committed transactions are permanently written to disk with WAL journaling.

2. **Q: What is the difference between optimistic and pessimistic concurrency control?**
   - *Pessimistic Locking* (`SELECT ... FOR UPDATE`): Locks the database row before reading or modifying, preventing any other transaction from touching it until commit. Ideal for high-conflict financial accounts where updates frequently collide.
   - *Optimistic Locking* (`version` column): Reads without locking and only checks if the version has changed at commit time (`WHERE version = :old_version`). Better for low-conflict workloads, but causes high retry overhead under high concurrency.

3. **Q: What would happen if the database server crashed mid-transfer?**
   - Because the balance updates and ledger writes occur within a single database transaction context (`try ... db.commit() except ... db.rollback()`), an uncommitted transaction will be cleanly rolled back by the database crash-recovery engine using the Write-Ahead Log (WAL). No partial balances can exist.

4. **Q: How does SQLite WAL mode work?**
   - Write-Ahead Logging writes all changes sequentially to a separate `-wal` file while readers continue accessing the main database file without blocking. Periodically, a "checkpoint" merges `-wal` data into the main database.

5. **Q: How does the system prevent idempotency collisions under high concurrency?**
   - The database table enforces a `UNIQUE(idempotency_key)` constraint. When two concurrent requests share the same new key, the first commits successfully, while the second triggers an `IntegrityError`. The second thread rolls back and queries the winning transaction to return its receipt safely without double deductions.

6. **Q: How would this architecture scale to millions of users?**
   - Horizontally scale the stateless FastAPI backend behind a load balancer.
   - Shard the wallet database by `user_id` or `wallet_id` (consistent hashing).
   - For cross-shard transfers, use a **Two-Phase Commit (2PC)** or a Saga Orchestration pattern with an outbox message queue (e.g. Apache Kafka) and compensating transactions.

---

## 8. Tech Stack

- **Backend**: Python 3.10+, FastAPI, SQLAlchemy 2.0, Pydantic v2, Uvicorn
- **Database**: SQLite (WAL Mode, BEGIN IMMEDIATE) / PostgreSQL
- **Security**: Passlib (Bcrypt), Python-Jose (JWT HS256)
- **Frontend**: React 19, TypeScript, Tailwind CSS, Lucide Icons, Vite
- **Testing**: Pytest, HTTPX, ThreadPoolExecutor
