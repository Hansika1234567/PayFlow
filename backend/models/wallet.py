from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship
from backend.database import Base

class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    
    # Financial balance stored in integer cents (e.g., $100.50 is stored as 10050)
    # Avoids floating point precision errors.
    balance = Column(BigInteger, default=0, nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    
    # Wallet lifecycle status: ACTIVE, FROZEN, CLOSED
    status = Column(String(20), default="ACTIVE", nullable=False)
    
    # Version column for optimistic concurrency control if needed
    version = Column(Integer, default=1, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Database-level Invariant Constraint:
    # 1. Non-negative balance (prevents overdrafts at kernel level)
    # 2. Maximum safe integer bound (9,007,199,254,740,991 cents ~= $90.07T) to guarantee JavaScript Number.MAX_SAFE_INTEGER precision
    __table_args__ = (
        CheckConstraint(
            "balance >= 0 AND balance <= 9007199254740991",
            name="check_wallet_balance_safe_range"
        ),
    )

    # Relationships
    user = relationship("User", back_populates="wallet")
    ledger_entries = relationship("LedgerEntry", back_populates="wallet", cascade="all, delete-orphan")

    @property
    def balance_in_dollars(self) -> float:
        """Helper to represent integer cents as dollars for display with 2-decimal precision."""
        return round(self.balance / 100.0, 2)

    @property
    def balance_dollars_formatted(self) -> str:
        """Fixed-point string representation (e.g. '1000.00') using integer-only arithmetic to avoid float drift."""
        dollars, cents = divmod(self.balance, 100)
        return f"{dollars}.{cents:02d}"
