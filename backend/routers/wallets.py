from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.user import User
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
    """
    wallet = get_or_create_wallet(db, current_user)
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
