from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.user import User
from backend.dependencies.auth import get_current_user
from backend.schemas.ledger import PaginatedLedgerResponse, PaginatedTransactionsResponse
from backend.services.ledger_service import get_user_ledger_entries, get_user_transaction_history

router = APIRouter(tags=["Ledger & Transaction History"])

@router.get("/ledger", response_model=PaginatedLedgerResponse, status_code=status.HTTP_200_OK)
def get_ledger(
    entry_type: Optional[str] = Query(None, description="Filter by entry type: 'DEBIT' or 'CREDIT'"),
    limit: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Fetch the authenticated user's double-entry ledger audit trail.
    Each entry shows the exact debit or credit and the running balance snapshot immediately after the mutation.
    """
    return get_user_ledger_entries(db, current_user, entry_type=entry_type, limit=limit, offset=offset)

@router.get("/transactions", response_model=PaginatedTransactionsResponse, status_code=status.HTTP_200_OK)
def get_transactions(
    filter_type: Optional[str] = Query("ALL", description="Filter by transaction type: 'ALL', 'SENT', or 'RECEIVED'"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Fetch the authenticated user's high-level transaction history, including counterparty details and statuses.
    """
    return get_user_transaction_history(db, current_user, filter_type=filter_type, limit=limit, offset=offset)
