from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.user import User
from backend.dependencies.auth import get_current_user
from backend.schemas.transfer import TransferRequest, TransferReceipt
from backend.services.transfer_service import execute_transfer, get_transaction_by_id

router = APIRouter(prefix="/transfers", tags=["Transfers & Payments"])

@router.post("", response_model=TransferReceipt, status_code=status.HTTP_201_CREATED)
def transfer_money(
    request: TransferRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Execute an atomic transfer from the authenticated user to a recipient.
    Guarantees:
    - Double-entry ledger audit records
    - Deadlock prevention via deterministic lock ordering
    - Idempotency key protection to prevent duplicate transfers
    - Immediate atomic rollback on failure
    """
    return execute_transfer(db, current_user, request)

@router.get("/{tx_id}", response_model=TransferReceipt, status_code=status.HTTP_200_OK)
def get_transfer(
    tx_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retrieve the transaction receipt and status by transaction UUID.
    """
    tx = get_transaction_by_id(db, tx_id)
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found."
        )

    # Security check: User must be either the sender or receiver
    sender_wallet = tx.sender_wallet
    receiver_wallet = tx.receiver_wallet

    if (sender_wallet.user_id != current_user.id) and (receiver_wallet.user_id != current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to view this transaction."
        )

    return TransferReceipt(
        transaction_id=tx.id,
        idempotency_key=tx.idempotency_key,
        sender_username=sender_wallet.user.username,
        receiver_username=receiver_wallet.user.username,
        amount_cents=tx.amount,
        amount_dollars=tx.amount / 100.0,
        currency=tx.currency,
        status=tx.status,
        description=tx.description,
        created_at=tx.created_at,
        sender_balance_after_dollars=None,
    )
