from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc

from backend.models.user import User
from backend.models.wallet import Wallet
from backend.models.transaction import Transaction
from backend.models.ledger import LedgerEntry
from backend.schemas.ledger import (
    LedgerEntryResponse,
    PaginatedLedgerResponse,
    TransactionHistoryItem,
    PaginatedTransactionsResponse
)

def get_user_ledger_entries(
    db: Session,
    user: User,
    entry_type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0
) -> PaginatedLedgerResponse:
    """
    Fetches the authenticated user's double-entry ledger records with optional filtering
    by entry_type (DEBIT or CREDIT) and pagination.
    """
    wallet = user.wallet
    if not wallet:
        return PaginatedLedgerResponse(items=[], total=0, limit=limit, offset=offset, has_more=False)

    query = db.query(LedgerEntry).filter(LedgerEntry.wallet_id == wallet.id)

    if entry_type:
        clean_type = entry_type.strip().upper()
        if clean_type in ["DEBIT", "CREDIT"]:
            query = query.filter(LedgerEntry.entry_type == clean_type)

    total_count = query.count()

    entries = (
        query.order_by(desc(LedgerEntry.created_at), desc(LedgerEntry.id))
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = []
    for entry in entries:
        tx = entry.transaction
        counterparty = None
        if tx:
            if entry.entry_type == "DEBIT" and tx.receiver_wallet and tx.receiver_wallet.user:
                counterparty = tx.receiver_wallet.user.username
            elif entry.entry_type == "CREDIT" and tx.sender_wallet and tx.sender_wallet.user:
                counterparty = tx.sender_wallet.user.username

        items.append(
            LedgerEntryResponse(
                id=entry.id,
                transaction_id=entry.transaction_id,
                entry_type=entry.entry_type,
                amount_cents=entry.amount,
                amount_dollars=entry.amount / 100.0,
                balance_after_dollars=entry.balance_after / 100.0,
                description=tx.description if tx else None,
                counterparty_username=counterparty,
                created_at=entry.created_at,
            )
        )

    has_more = (offset + limit) < total_count
    return PaginatedLedgerResponse(
        items=items,
        total=total_count,
        limit=limit,
        offset=offset,
        has_more=has_more
    )

def get_user_transaction_history(
    db: Session,
    user: User,
    filter_type: Optional[str] = None,  # "ALL", "SENT", "RECEIVED"
    limit: int = 20,
    offset: int = 0
) -> PaginatedTransactionsResponse:
    """
    Fetches high-level transaction history where user was sender or receiver.
    """
    wallet = user.wallet
    if not wallet:
        return PaginatedTransactionsResponse(items=[], total=0, limit=limit, offset=offset, has_more=False)

    clean_filter = (filter_type or "ALL").strip().upper()

    if clean_filter == "SENT":
        query = db.query(Transaction).filter(Transaction.sender_wallet_id == wallet.id)
    elif clean_filter == "RECEIVED":
        query = db.query(Transaction).filter(Transaction.receiver_wallet_id == wallet.id)
    else:
        query = db.query(Transaction).filter(
            or_(Transaction.sender_wallet_id == wallet.id, Transaction.receiver_wallet_id == wallet.id)
        )

    total_count = query.count()

    txs = (
        query.order_by(desc(Transaction.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = []
    for tx in txs:
        is_sender = tx.sender_wallet_id == wallet.id
        tx_type = "SENT" if is_sender else "RECEIVED"

        if is_sender:
            target_user = tx.receiver_wallet.user if tx.receiver_wallet else None
        else:
            target_user = tx.sender_wallet.user if tx.sender_wallet else None

        counterparty_username = target_user.username if target_user else "System"
        counterparty_full_name = target_user.full_name if target_user else "System Deposit"

        items.append(
            TransactionHistoryItem(
                id=tx.id,
                type=tx_type,
                counterparty_username=counterparty_username,
                counterparty_full_name=counterparty_full_name,
                amount_cents=tx.amount,
                amount_dollars=tx.amount / 100.0,
                currency=tx.currency,
                status=tx.status,
                description=tx.description,
                created_at=tx.created_at,
            )
        )

    has_more = (offset + limit) < total_count
    return PaginatedTransactionsResponse(
        items=items,
        total=total_count,
        limit=limit,
        offset=offset,
        has_more=has_more
    )
