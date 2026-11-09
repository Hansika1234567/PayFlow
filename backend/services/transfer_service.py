import uuid
import hashlib
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from backend.models.user import User
from backend.models.wallet import Wallet
from backend.models.transaction import Transaction
from backend.models.ledger import LedgerEntry
from backend.schemas.transfer import TransferRequest, TransferReceipt

def compute_payload_hash(sender_wallet_id: int, receiver_username: str, amount_cents: int) -> str:
    """Computes a SHA-256 fingerprint of the transfer parameters."""
    normalized_receiver = receiver_username.strip().lower()
    payload_str = f"{sender_wallet_id}:{normalized_receiver}:{amount_cents}"
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

def get_transaction_by_id(db: Session, tx_id: str) -> Optional[Transaction]:
    """Retrieves a transaction by its UUID primary key."""
    return db.query(Transaction).filter(Transaction.id == tx_id).first()

def execute_transfer(db: Session, sender: User, request: TransferRequest) -> TransferReceipt:
    """
    Executes an atomic transfer between two users with double-entry ledger bookkeeping,
    request-hash idempotency protection, and deterministic lock ordering to prevent deadlocks.
    """
    amount_cents = request.amount_in_cents
    idemp_key = request.idempotency_key.strip()

    # 1. Resolve Sender Wallet
    sender_wallet = sender.wallet
    if not sender_wallet:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sender does not have an active wallet."
        )

    if sender_wallet.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Sender wallet is {sender_wallet.status}. Transfers are disabled."
        )

    # 2. Compute Payload Fingerprint Hash
    current_request_hash = compute_payload_hash(
        sender_wallet_id=sender_wallet.id,
        receiver_username=request.receiver_username,
        amount_cents=amount_cents,
    )

    # 3. Check Idempotency Key & Mismatched Parameter Detection
    existing_tx = db.query(Transaction).filter(Transaction.idempotency_key == idemp_key).first()
    if existing_tx:
        # Detect payload mismatch: Same key reused with different amount, recipient, etc.
        if existing_tx.request_hash and existing_tx.request_hash != current_request_hash:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Idempotency key parameter mismatch. This key was already used for a transfer with different parameters."
            )

        if existing_tx.status == "COMPLETED":
            sender_w = db.query(Wallet).filter(Wallet.id == existing_tx.sender_wallet_id).first()
            receiver_w = db.query(Wallet).filter(Wallet.id == existing_tx.receiver_wallet_id).first()
            return TransferReceipt(
                transaction_id=existing_tx.id,
                idempotency_key=existing_tx.idempotency_key,
                sender_username=sender_w.user.username if sender_w and sender_w.user else "unknown",
                receiver_username=receiver_w.user.username if receiver_w and receiver_w.user else "unknown",
                amount_cents=existing_tx.amount,
                amount_dollars=existing_tx.amount / 100.0,
                currency=existing_tx.currency,
                status=existing_tx.status,
                description=existing_tx.description,
                created_at=existing_tx.created_at,
                sender_balance_after_dollars=sender_w.balance_in_dollars if sender_w else None,
            )
        elif existing_tx.status == "PENDING":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A transaction with this idempotency key is currently processing. Please wait."
            )

    # 4. Recipient Resolution
    recipient = db.query(User).filter(User.username == request.receiver_username).first()
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recipient user '{request.receiver_username}' does not exist."
        )

    # Prevent Self-Transfers
    if recipient.id == sender.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Self-transfers are not permitted. Recipient must be a different user."
        )

    receiver_wallet = recipient.wallet
    if not receiver_wallet or receiver_wallet.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient wallet is not active or not provisioned."
        )

    # 5. Atomic Execution Block with Deterministic Lock Ordering
    # In concurrent environments, locking wallets in arbitrary order causes DEADLOCKS:
    # (Thread A locks W1 -> W2, while Thread B locks W2 -> W1).
    # Ordering wallet locks by min(ID) -> max(ID) guarantees acyclic resource allocation!
    first_id = min(sender_wallet.id, receiver_wallet.id)
    second_id = max(sender_wallet.id, receiver_wallet.id)

    try:
        # Acquire row-level locks in deterministic order
        # with_for_update() enforces pessimistic locking on PostgreSQL
        wallet_a = db.query(Wallet).filter(Wallet.id == first_id).with_for_update().first()
        wallet_b = db.query(Wallet).filter(Wallet.id == second_id).with_for_update().first()

        # Re-map sender and receiver to locked entities
        locked_sender = wallet_a if wallet_a.id == sender_wallet.id else wallet_b
        locked_receiver = wallet_a if wallet_a.id == receiver_wallet.id else wallet_b

        # 6. Check Balance Invariant
        if locked_sender.balance < amount_cents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Insufficient funds. Required: ${amount_cents / 100:.2f}, "
                    f"Available balance: ${locked_sender.balance_in_dollars:.2f}"
                )
            )

        # 7. Mutate Balances using Conditional Atomic SQL expressions
        # The condition (balance >= amount_cents) provides kernel-level defense against race conditions
        update_result = db.execute(
            update(Wallet)
            .where(Wallet.id == locked_sender.id, Wallet.balance >= amount_cents)
            .values(balance=Wallet.balance - amount_cents, version=Wallet.version + 1)
        )
        if update_result.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Insufficient funds or concurrent modification. Required: ${amount_cents / 100:.2f}, "
                    f"Available: ${locked_sender.balance_in_dollars:.2f}"
                )
            )

        db.execute(
            update(Wallet)
            .where(Wallet.id == locked_receiver.id)
            .values(balance=Wallet.balance + amount_cents, version=Wallet.version + 1)
        )
        db.flush()
        db.refresh(locked_sender)
        db.refresh(locked_receiver)

        # 8. Record Transaction with Request Hash
        tx = Transaction(
            id=str(uuid.uuid4()),
            idempotency_key=idemp_key,
            request_hash=current_request_hash,
            sender_wallet_id=locked_sender.id,
            receiver_wallet_id=locked_receiver.id,
            amount=amount_cents,
            currency=locked_sender.currency,
            status="COMPLETED",
            description=request.description or f"Transfer to @{recipient.username}",
        )
        db.add(tx)
        db.flush()

        # 9. Record Double-Entry Bookkeeping Ledger
        # Rule of Ledger: Every credit has an equal and opposite debit.
        debit_entry = LedgerEntry(
            transaction_id=tx.id,
            wallet_id=locked_sender.id,
            entry_type="DEBIT",
            amount=amount_cents,
            balance_after=locked_sender.balance,
        )
        credit_entry = LedgerEntry(
            transaction_id=tx.id,
            wallet_id=locked_receiver.id,
            entry_type="CREDIT",
            amount=amount_cents,
            balance_after=locked_receiver.balance,
        )
        db.add(debit_entry)
        db.add(credit_entry)

        # 10. Atomic Commit
        db.commit()
        db.refresh(locked_sender)
        db.refresh(tx)

        return TransferReceipt(
            transaction_id=tx.id,
            idempotency_key=tx.idempotency_key,
            sender_username=sender.username,
            receiver_username=recipient.username,
            amount_cents=tx.amount,
            amount_dollars=tx.amount / 100.0,
            currency=tx.currency,
            status=tx.status,
            description=tx.description,
            created_at=tx.created_at,
            sender_balance_after_dollars=locked_sender.balance_in_dollars,
        )

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
                    detail="Idempotency key parameter mismatch. This key was already used for a transfer with different parameters."
                )
            if winning_tx.status == "COMPLETED":
                sender_w = db.query(Wallet).filter(Wallet.id == winning_tx.sender_wallet_id).first()
                receiver_w = db.query(Wallet).filter(Wallet.id == winning_tx.receiver_wallet_id).first()
                return TransferReceipt(
                    transaction_id=winning_tx.id,
                    idempotency_key=winning_tx.idempotency_key,
                    sender_username=sender_w.user.username if sender_w and sender_w.user else sender.username,
                    receiver_username=receiver_w.user.username if receiver_w and receiver_w.user else recipient.username,
                    amount_cents=winning_tx.amount,
                    amount_dollars=winning_tx.amount / 100.0,
                    currency=winning_tx.currency,
                    status=winning_tx.status,
                    description=winning_tx.description,
                    created_at=winning_tx.created_at,
                    sender_balance_after_dollars=sender_w.balance_in_dollars if sender_w else None,
                )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Concurrent transfer conflict on idempotency key. Please retry."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transaction processing failed: {str(e)}"
        )
