import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

class Settings(BaseSettings):
    PROJECT_NAME: str = "PayFlow - Digital Wallet & Transaction Management System"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    
    # Database Configuration (supports PostgreSQL if specified in env, defaults to SQLite)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./payflow.db")
    
    # Security Configuration
    # In production, SECRET_KEY must be provided explicitly via environment variable.
    # In development/test, a fallback is provided for convenience.
    SECRET_KEY: str = os.getenv("SECRET_KEY", "payflow-dev-secret-key-change-in-production-2026")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    
    # Allowed CORS Origins - parsed from env (comma-separated)
    ALLOWED_CORS_ORIGINS: List[str] = [
        origin.strip()
        for origin in os.getenv("ALLOWED_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,*").split(",")
        if origin.strip()
    ]
    
    # Financial Invariants
    INITIAL_WALLET_BALANCE_CENTS: int = 100000  # $1,000.00 in cents for newly registered test accounts
    DEFAULT_CURRENCY: str = "USD"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_production_secret(cls, v: str) -> str:
        env = os.getenv("ENVIRONMENT", "development").lower()
        if env == "production":
            insecure_markers = ["dev-secret", "change-in-production", "test"]
            if any(marker in v.lower() for marker in insecure_markers) or len(v) < 32:
                raise ValueError(
                    "FATAL SECURITY VIOLATION: Production environment detected with insecure or default SECRET_KEY! "
                    "You must provide a high-entropy 256-bit secret key via the SECRET_KEY environment variable."
                )
        return v

settings = Settings()
