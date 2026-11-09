import uuid
from sqlalchemy.orm import Session
from sqlalchemy import or_
from fastapi import HTTPException, status

from backend.config import settings
from backend.models.user import User
from backend.models.wallet import Wallet
from backend.models.transaction import Transaction
from backend.models.ledger import LedgerEntry
from backend.schemas.auth import UserRegisterRequest, WalletSummary, UserResponse
from backend.utils.security import get_password_hash, verify_password

def format_user_response(user: User) -> UserResponse:
    """Helper to convert a User ORM model to a UserResponse Pydantic schema."""
    wallet_summary = None
    if user.wallet:
        wallet_summary = WalletSummary(
            id=user.wallet.id,
            balance_cents=user.wallet.balance,
            balance_dollars=user.wallet.balance_in_dollars,
            currency=user.wallet.currency,
            status=user.wallet.status,
        )
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        is_active=user.is_active,
        created_at=user.created_at,
        wallet=wallet_summary,
    )

def register_user(db: Session, request: UserRegisterRequest) -> User:
    """
    Registers a new user and atomically provisions their digital wallet
    with an initial test credit ($1,000.00).
    """
    # Check if email or username already exists
    existing = db.query(User).filter(
        or_(User.email == request.email, User.username == request.username)
    ).first()

    if existing:
        if existing.email == request.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this email address already exists."
            )
        if existing.username == request.username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this username already exists."
            )

    # Hash the plain password with bcrypt
    hashed_pwd = get_password_hash(request.password)

    # Atomic transaction block
    try:
        new_user = User(
            email=request.email,
            username=request.username,
            hashed_password=hashed_pwd,
            full_name=request.full_name,
            is_active=True,
        )
        db.add(new_user)
        db.flush()  # Flushes new_user to allocate user.id

        # Provision wallet
        initial_balance = settings.INITIAL_WALLET_BALANCE_CENTS
        new_wallet = Wallet(
            user_id=new_user.id,
            balance=initial_balance,
            currency=settings.DEFAULT_CURRENCY,
            status="ACTIVE",
            version=1,
        )
        db.add(new_wallet)
        db.flush()  # Flushes new_wallet to allocate wallet.id

        # Record welcome initial funding transaction & ledger entry
        welcome_tx = Transaction(
            id=str(uuid.uuid4()),
            idempotency_key=f"welcome-bonus-{new_user.id}-{uuid.uuid4().hex[:8]}",
            sender_wallet_id=new_wallet.id,  # Self-originated test bonus
            receiver_wallet_id=new_wallet.id,
            amount=initial_balance,
            currency=settings.DEFAULT_CURRENCY,
            status="COMPLETED",
            description="Welcome Account Initialization Bonus",
        )
        db.add(welcome_tx)
        db.flush()

        # Immutable ledger credit entry
        ledger_entry = LedgerEntry(
            transaction_id=welcome_tx.id,
            wallet_id=new_wallet.id,
            entry_type="CREDIT",
            amount=initial_balance,
            balance_after=initial_balance,
        )
        db.add(ledger_entry)

        db.commit()
        db.refresh(new_user)
        return new_user

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to register user and provision wallet: {str(e)}"
        )

def authenticate_user(db: Session, email_or_username: str, plain_password: str) -> User:
    """
    Authenticates a user by email or username and verifies password hash.
    Raises HTTP 401 Unauthorized on failure.
    """
    query_param = email_or_username.strip().lower()
    user = db.query(User).filter(
        or_(User.email == query_param, User.username == query_param)
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(plain_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive."
        )

    return user
