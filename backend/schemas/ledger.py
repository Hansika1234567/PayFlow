from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

class LedgerEntryResponse(BaseModel):
    id: int
    transaction_id: str
    entry_type: str = Field(..., description="'DEBIT' (money sent/withdrawn) or 'CREDIT' (money received/deposited)")
    amount_cents: int
    amount_dollars: float
    balance_after_dollars: float
    description: Optional[str] = None
    counterparty_username: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class PaginatedLedgerResponse(BaseModel):
    items: List[LedgerEntryResponse]
    total: int
    limit: int
    offset: int
    has_more: bool

class TransactionHistoryItem(BaseModel):
    id: str
    type: str = Field(..., description="'SENT' if user paid, 'RECEIVED' if user was recipient")
    counterparty_username: str
    counterparty_full_name: str
    amount_cents: int
    amount_dollars: float
    currency: str
    status: str
    description: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class PaginatedTransactionsResponse(BaseModel):
    items: List[TransactionHistoryItem]
    total: int
    limit: int
    offset: int
    has_more: bool
