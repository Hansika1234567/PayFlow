from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.user import User
from backend.models.wallet import Wallet
from backend.dependencies.auth import get_current_user
from backend.schemas.wallet import DepositRequest, WalletResponse
from backend.services.wallet_service import (
    get_or_create_wallet,
    format_wallet_response,
    deposit_funds,
)

router = APIRouter(prefix="/wallets", tags=["Wallets & Balances"])

@router.get("/me", response_model=WalletResponse, status_code=status.HTTP_200_OK)
def get_my_wallet(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Fetch the authenticated user's digital wallet balance and currency status.
    Strictly read-only query; never performs hidden database writes or commits.
    """
    wallet = current_user.wallet or db.query(Wallet).filter(Wallet.user_id == current_user.id).first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not provisioned for this account. Please initialize your wallet via /wallets/initialize or contact support."
        )
    return format_wallet_response(wallet)

@router.post("/initialize", response_model=WalletResponse, status_code=status.HTTP_201_CREATED)
def initialize_wallet(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Explicit recovery endpoint to provision a digital wallet for legacy accounts.
    Explicitly owns the transaction boundary and commits the provisioning.
    """
    existing = current_user.wallet or db.query(Wallet).filter(Wallet.user_id == current_user.id).first()
    if existing:
        return format_wallet_response(existing)
    wallet = get_or_create_wallet(db, current_user, auto_commit=False)
    db.commit()
    db.refresh(wallet)
    return format_wallet_response(wallet)

@router.post("/deposit", response_model=WalletResponse, status_code=status.HTTP_200_OK)
def deposit(
    request: DepositRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Simulate depositing money into the authenticated user's wallet.
    Updates balance and creates an audit ledger credit entry.
    """
    return deposit_funds(db, current_user, request)

