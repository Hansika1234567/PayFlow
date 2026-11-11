import uuid
import hashlib
from sqlalchemy.orm import Session
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError
from fastapi import HTTPException, status

from backend.config import settings
from backend.models.user import User
from backend.models.wallet import Wallet
from backend.models.transaction import Transaction
from backend.models.ledger import LedgerEntry
from backend.schemas.wallet import DepositRequest, WalletResponse

def compute_deposit_hash(wallet_id: int, amount_cents: int) -> str:
    """Computes a SHA-256 fingerprint of the deposit parameters."""
    payload_str = f"DEPOSIT:{wallet_id}:{amount_cents}"
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

def format_deposit_idempotency_key(raw_key: str) -> str:
    """
    Namespaces deposit idempotency keys with 'dep:' prefix to eliminate
    cross-operation collision with transfer idempotency keys.
    """
    cleaned = raw_key.strip()
    if cleaned.startswith("dep:"):
        return cleaned[:64]
    prefixed = f"dep:{cleaned}"
    if len(prefixed) <= 64:
        return prefixed
    return f"dep:{hashlib.sha256(cleaned.encode()).hexdigest()[:60]}"

def get_or_create_wallet(db: Session, user: User, auto_commit: bool = False) -> Wallet:
    """
    Retrieves the user's wallet. If missing, automatically provisions one with welcome ledger entry.
    Defaults to auto_commit=False so callers explicitly own their transaction boundaries.
    """
    wallet = db.query(Wallet).filter(Wallet.user_id == user.id).first()
    if not wallet:
        wallet = Wallet(
            user_id=user.id,
            balance=settings.INITIAL_WALLET_BALANCE_CENTS,
            currency=settings.DEFAULT_CURRENCY,
            status="ACTIVE",
            version=1,
        )
        db.add(wallet)
        db.flush()

        welcome_tx = Transaction(
            id=str(uuid.uuid4()),
            idempotency_key=f"welcome-bonus-{user.id}-{uuid.uuid4().hex[:8]}",
            sender_wallet_id=wallet.id,
            receiver_wallet_id=wallet.id,
            amount=settings.INITIAL_WALLET_BALANCE_CENTS,
            currency=settings.DEFAULT_CURRENCY,
            status="COMPLETED",
            description="Welcome Account Initialization Bonus",
        )
        db.add(welcome_tx)
        db.flush()

        ledger_entry = LedgerEntry(
            transaction_id=welcome_tx.id,
            wallet_id=wallet.id,
            entry_type="CREDIT",
            amount=settings.INITIAL_WALLET_BALANCE_CENTS,
            balance_after=wallet.balance,
        )
        db.add(ledger_entry)
        if auto_commit:
            db.commit()
            db.refresh(wallet)
        else:
            db.flush()
    return wallet

def format_wallet_response(wallet: Wallet) -> WalletResponse:
    """Helper to format a Wallet model into a WalletResponse schema with exact 2-decimal dollar representation."""
    return WalletResponse(
        id=wallet.id,
        user_id=wallet.user_id,
        balance_cents=wallet.balance,
        balance_dollars=round(wallet.balance / 100.0, 2),
        currency=wallet.currency,
        status=wallet.status,
        version=wallet.version,
        created_at=wallet.created_at,
        updated_at=wallet.updated_at,
    )

def deposit_funds(db: Session, user: User, request: DepositRequest) -> WalletResponse:
    """
    Atomically deposits funds into the user's wallet with SQL-level atomic updates,
    pessimistic row locking, SHA-256 idempotency fingerprinting, and concurrency collision safety.
    """
    # Use auto_commit=False so wallet provisioning and deposit execute within a single atomic transaction
    wallet = get_or_create_wallet(db, user, auto_commit=False)

    if wallet.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot deposit to wallet with status: {wallet.status}"
        )

    amount_cents = request.amount_in_cents

    # 1. Namespace idempotency key to prevent collision with transfer keys
    if request.idempotency_key:
        idemp_key = format_deposit_idempotency_key(request.idempotency_key)
    else:
        idemp_key = f"dep:{wallet.id}:{uuid.uuid4().hex}"

    # 2. Compute SHA-256 fingerprint of the deposit parameters
    current_request_hash = compute_deposit_hash(wallet_id=wallet.id, amount_cents=amount_cents)

    # 3. Check Idempotency Key & Mismatched Parameter Detection
    existing_tx = db.query(Transaction).filter(Transaction.idempotency_key == idemp_key).first()
    if existing_tx:
        # Detect payload mismatch: Same key reused with different deposit amount
        if existing_tx.request_hash and existing_tx.request_hash != current_request_hash:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Idempotency key parameter mismatch. This key was already used for a deposit with a different amount."
            )

        if existing_tx.status == "COMPLETED":
            db.refresh(wallet)
            return format_wallet_response(wallet)
        elif existing_tx.status == "PENDING":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A deposit with this idempotency key is currently processing. Please wait."
            )

    try:
        # 4. Acquire pessimistic lock on the target wallet
        # with_for_update() enforces row-level locking on PostgreSQL
        locked_wallet = db.query(Wallet).filter(Wallet.id == wallet.id).with_for_update().first()
        if not locked_wallet or locked_wallet.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Wallet is not active or not provisioned."
            )

        # Money Precision Invariant: Prevent wallet balance from exceeding JavaScript Number.MAX_SAFE_INTEGER
        if locked_wallet.balance + amount_cents > settings.MAX_SAFE_BALANCE_CENTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Deposit exceeds maximum permitted wallet balance capacity."
            )

        # 5. Atomic SQL Balance Increment & Atomic Version Bump
        # This pushes arithmetic evaluation directly to the database engine,
        # completely preventing lost updates across concurrent deposit transactions.
        db.execute(
            update(Wallet)
            .where(Wallet.id == locked_wallet.id)
            .values(balance=Wallet.balance + amount_cents, version=Wallet.version + 1)
        )
        db.flush()
        db.refresh(locked_wallet)

        # 6. Record deposit Transaction with SHA-256 Fingerprint
        tx = Transaction(
            id=str(uuid.uuid4()),
            idempotency_key=idemp_key,
            request_hash=current_request_hash,
            sender_wallet_id=locked_wallet.id,
            receiver_wallet_id=locked_wallet.id,
            amount=amount_cents,
            currency=locked_wallet.currency,
            status="COMPLETED",
            description=request.description or "Direct Wallet Deposit",
        )
        db.add(tx)
        db.flush()

        # 7. Record double-entry CREDIT ledger entry with exact committed balance_after
        ledger = LedgerEntry(
            transaction_id=tx.id,
            wallet_id=locked_wallet.id,
            entry_type="CREDIT",
            amount=amount_cents,
            balance_after=locked_wallet.balance,
        )
        db.add(ledger)

        # 8. Atomic Commit
        db.commit()
        db.refresh(locked_wallet)
        return format_wallet_response(locked_wallet)

    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        # Concurrent collision on unique idempotency_key
        db.rollback()
        winning_tx = db.query(Transaction).filter(Transaction.idempotency_key == idemp_key).first()
        if winning_tx:
            if winning_tx.request_hash and winning_tx.request_hash != current_request_hash:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Idempotency key parameter mismatch. This key was already used for a deposit with a different amount."
                )
            if winning_tx.status == "COMPLETED":
                refreshed_wallet = db.query(Wallet).filter(Wallet.id == wallet.id).first()
                return format_wallet_response(refreshed_wallet)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Concurrent deposit conflict on idempotency key. Please retry."
        )
    except OperationalError:
        # SQLite busy timeout under high concurrent contention
        db.rollback()
        committed_tx = db.query(Transaction).filter(Transaction.idempotency_key == idemp_key).first()
        if committed_tx:
            refreshed_wallet = db.query(Wallet).filter(Wallet.id == wallet.id).first()
            return format_wallet_response(refreshed_wallet)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database busy or locked under concurrent load. Please retry your deposit."
        )
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred while processing the deposit."
        )
