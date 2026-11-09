import uuid
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.config import settings
from backend.models.user import User
from backend.models.wallet import Wallet
from backend.models.transaction import Transaction
from backend.models.ledger import LedgerEntry
from backend.schemas.wallet import DepositRequest, WalletResponse

def get_or_create_wallet(db: Session, user: User) -> Wallet:
    """Retrieves the user's wallet. If missing, automatically provisions one."""
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
        db.commit()
        db.refresh(wallet)
    return wallet

def format_wallet_response(wallet: Wallet) -> WalletResponse:
    """Helper to format a Wallet model into a WalletResponse schema."""
    return WalletResponse(
        id=wallet.id,
        user_id=wallet.user_id,
        balance_cents=wallet.balance,
        balance_dollars=wallet.balance_in_dollars,
        currency=wallet.currency,
        status=wallet.status,
        version=wallet.version,
        created_at=wallet.created_at,
        updated_at=wallet.updated_at,
    )

def deposit_funds(db: Session, user: User, request: DepositRequest) -> WalletResponse:
    """
    Atomically deposits funds into the user's wallet.
    Records a completed deposit Transaction and an immutable CREDIT LedgerEntry.
    """
    wallet = get_or_create_wallet(db, user)

    if wallet.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot deposit to wallet with status: {wallet.status}"
        )

    amount_cents = request.amount_in_cents
    idemp_key = request.idempotency_key or f"deposit-{wallet.id}-{uuid.uuid4().hex}"

    # Check if this deposit idempotency key was already processed
    existing_tx = db.query(Transaction).filter(Transaction.idempotency_key == idemp_key).first()
    if existing_tx:
        # Idempotent response: return current wallet without double-depositing
        return format_wallet_response(wallet)

    try:
        # Mutate wallet balance
        wallet.balance += amount_cents
        wallet.version += 1
        db.flush()

        # Record deposit transaction
        tx = Transaction(
            id=str(uuid.uuid4()),
            idempotency_key=idemp_key,
            sender_wallet_id=wallet.id,
            receiver_wallet_id=wallet.id,
            amount=amount_cents,
            currency=wallet.currency,
            status="COMPLETED",
            description=request.description or "Direct Wallet Deposit",
        )
        db.add(tx)
        db.flush()

        # Record double-entry CREDIT ledger entry
        ledger = LedgerEntry(
            transaction_id=tx.id,
            wallet_id=wallet.id,
            entry_type="CREDIT",
            amount=amount_cents,
            balance_after=wallet.balance,
        )
        db.add(ledger)

        db.commit()
        db.refresh(wallet)
        return format_wallet_response(wallet)

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process deposit: {str(e)}"
        )
