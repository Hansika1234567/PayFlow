from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator

class DepositRequest(BaseModel):
    amount: Decimal = Field(..., description="Amount to deposit in USD. Must be positive with at most 2 decimal places.")
    description: Optional[str] = Field("Wallet Top-up Deposit", max_length=255)
    idempotency_key: Optional[str] = Field(None, max_length=64, description="Optional unique idempotency key for the deposit")

    @field_validator("amount", mode="before")
    @classmethod
    def validate_deposit_precision(cls, v) -> Decimal:
        if isinstance(v, (int, float)):
            v = str(v)
        try:
            d = Decimal(str(v).strip())
        except Exception:
            raise ValueError("Amount must be a valid numeric decimal value.")
        if d <= Decimal("0"):
            raise ValueError("Amount must be strictly greater than 0.00.")
        if d > Decimal("100000"):
            raise ValueError("Amount exceeds maximum deposit limit of $100,000.00.")
        if d.as_tuple().exponent < -2:
            raise ValueError("Amount cannot have more than 2 decimal places (fractional cents not permitted).")
        return d

    @property
    def amount_in_cents(self) -> int:
        return int(self.amount * 100)

class WalletResponse(BaseModel):
    id: int
    user_id: int
    balance_cents: int
    balance_dollars: float
    currency: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
