from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict

class UserRegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50, description="Unique username")
    password: str = Field(..., min_length=6, max_length=128, description="Plain text password")
    full_name: str = Field(..., min_length=1, max_length=100, description="Full display name")

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip().lower()
        if not v.isalnum() and "_" not in v:
            raise ValueError("Username can only contain alphanumeric characters and underscores.")
        return v

class UserLoginRequest(BaseModel):
    email_or_username: str = Field(..., description="User email or username")
    password: str = Field(..., description="User password")

class WalletSummary(BaseModel):
    id: int
    balance_cents: int
    balance_dollars: float
    currency: str
    status: str

    model_config = ConfigDict(from_attributes=True)

class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    full_name: str
    is_active: bool
    created_at: datetime
    wallet: Optional[WalletSummary] = None

    model_config = ConfigDict(from_attributes=True)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    user: UserResponse
