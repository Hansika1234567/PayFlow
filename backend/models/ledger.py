from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from backend.database import Base

class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(Integer, primary_key=True, index=True)
    
    # Associated transaction
    transaction_id = Column(String(36), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Target wallet for this ledger entry
    wallet_id = Column(Integer, ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Entry type: DEBIT (money leaving) or CREDIT (money entering)
    entry_type = Column(String(10), nullable=False)
    
    # Amount in integer cents (always positive)
    amount = Column(BigInteger, nullable=False)
    
    # Wallet balance snapshot immediately after this ledger entry was written
    balance_after = Column(BigInteger, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    transaction = relationship("Transaction", back_populates="ledger_entries")
    wallet = relationship("Wallet", back_populates="ledger_entries")

    __table_args__ = (
        Index("ix_ledger_wallet_created", "wallet_id", "created_at"),
    )
