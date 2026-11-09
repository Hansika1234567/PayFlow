import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, BigInteger, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from backend.database import Base

class Transaction(Base):
    __tablename__ = "transactions"

    # UUID primary key prevents sequential ID enumeration attacks
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Idempotency key sent by client to prevent duplicate charges on retry
    idempotency_key = Column(String(64), unique=True, index=True, nullable=False)
    
    sender_wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=False, index=True)
    receiver_wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=False, index=True)
    
    amount = Column(BigInteger, nullable=False)  # in integer cents
    currency = Column(String(3), default="USD", nullable=False)
    
    # Transaction status: PENDING, COMPLETED, FAILED
    status = Column(String(20), default="PENDING", nullable=False, index=True)
    description = Column(String(255), nullable=True)
    
    # SHA-256 hash of transfer payload (sender, receiver, amount) to detect parameter mismatch on key reuse
    request_hash = Column(String(64), nullable=True, index=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    sender_wallet = relationship("Wallet", foreign_keys=[sender_wallet_id])
    receiver_wallet = relationship("Wallet", foreign_keys=[receiver_wallet_id])
    ledger_entries = relationship("LedgerEntry", back_populates="transaction", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_tx_sender_created", "sender_wallet_id", "created_at"),
        Index("ix_tx_receiver_created", "receiver_wallet_id", "created_at"),
    )
