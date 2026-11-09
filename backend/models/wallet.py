from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base

class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    
    # Financial balance stored in integer cents (e.g., $100.50 is stored as 10050)
    # Why integer cents? Avoids floating point precision errors (e.g. 0.1 + 0.2 = 0.30000000000000004)
    balance = Column(BigInteger, default=0, nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    
    # Wallet lifecycle status: ACTIVE, FROZEN, CLOSED
    status = Column(String(20), default="ACTIVE", nullable=False)
    
    # Version column for optimistic concurrency control if needed
    version = Column(Integer, default=1, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="wallet")
    ledger_entries = relationship("LedgerEntry", back_populates="wallet", cascade="all, delete-orphan")

    @property
    def balance_in_dollars(self) -> float:
        """Helper to represent integer cents as dollars for display."""
        return self.balance / 100.0
