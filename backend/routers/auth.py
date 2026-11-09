from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.user import User
from backend.dependencies.auth import get_current_user
from backend.schemas.auth import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    UserResponse
)
from backend.services.user_service import (
    register_user,
    authenticate_user,
    format_user_response
)
from backend.utils.security import create_access_token

router = APIRouter(prefix="/auth", tags=["Authentication & User Management"])

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(request: UserRegisterRequest, db: Session = Depends(get_db)):
    """
    Register a new user account.
    Upon successful registration, PayFlow automatically provisions a digital wallet
    with an initial $1,000.00 test balance and issues a signed JWT access token.
    """
    user = register_user(db, request)
    access_token = create_access_token(subject=user.id)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        user=format_user_response(user)
    )

@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
def login(request: UserLoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate a user using their email or username and password.
    Returns a signed JWT access token and the user's profile with wallet summary.
    """
    user = authenticate_user(db, request.email_or_username, request.password)
    access_token = create_access_token(subject=user.id)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        user=format_user_response(user)
    )

@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
def get_me(current_user: User = Depends(get_current_user)):
    """
    Get the authenticated user's profile and current wallet balance summary.
    Requires Bearer token authorization header.
    """
    return format_user_response(current_user)
