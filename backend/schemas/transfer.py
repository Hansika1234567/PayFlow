from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator

class TransferRequest(BaseModel):
    receiver_username: str = Field(..., min_length=3, max_length=50, description="Recipient's username")
    amount: Decimal = Field(..., description="Transfer amount in USD. Must be positive with at most 2 decimal places.")
    idempotency_key: str = Field(..., min_length=8, max_length=64, description="Unique client-generated idempotency key (e.g. UUIDv4)")
    description: Optional[str] = Field(None, max_length=255, description="Optional payment reference or note")

    @field_validator("receiver_username")
    @classmethod
    def sanitize_username(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount_precision(cls, v) -> Decimal:
        if isinstance(v, (int, float)):
            v = str(v)
        try:
            d = Decimal(str(v).strip())
        except Exception:
            raise ValueError("Amount must be a valid numeric decimal value.")
        if d <= Decimal("0"):
            raise ValueError("Amount must be strictly greater than 0.00.")
        if d > Decimal("1000000"):
            raise ValueError("Amount exceeds maximum transfer limit of $1,000,000.00.")
        if d.as_tuple().exponent < -2:
            raise ValueError("Amount cannot have more than 2 decimal places (fractional cents not permitted).")
        return d

    @property
    def amount_in_cents(self) -> int:
        return int(self.amount * 100)

class TransferReceipt(BaseModel):
    transaction_id: str
    idempotency_key: str
    sender_username: str
    receiver_username: str
    amount_cents: int
    amount_dollars: float
    currency: str
    status: str
    description: Optional[str] = None
    created_at: datetime
    sender_balance_after_dollars: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)
