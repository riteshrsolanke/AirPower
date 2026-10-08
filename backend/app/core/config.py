"""
Application configuration loaded from environment variables.
Never store secrets in source code.
"""
import os
from functools import lru_cache
from typing import Optional
from pathlib import Path

CORE_DIR = Path(__file__).parent


class Settings:
    # Application
    APP_NAME: str = "Air Power — Dynamic Air Operations Decision-Support System"
    APP_VERSION: str = "2.0.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite:///./airpower.db"
    )

    # JWT Authentication - Phase 6 Hardening (RS256)
    try:
        PRIVATE_KEY: str = (CORE_DIR / "private.pem").read_text()
        PUBLIC_KEY: str  = (CORE_DIR / "public.pem").read_text()
    except FileNotFoundError:
        PRIVATE_KEY = "fallback"
        PUBLIC_KEY = "fallback"

    ALGORITHM: str = "RS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    LOGIN_RATE_LIMIT: str = os.getenv("LOGIN_RATE_LIMIT", "5/minute")
    MAX_LOGIN_ATTEMPTS: int = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
    LOCKOUT_DURATION_MINUTES: int = int(os.getenv("LOCKOUT_DURATION_MINUTES", "15"))

    # CORS
    ALLOWED_ORIGINS: list = os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")

    # ML
    ML_MODEL_PATH: str = os.getenv("ML_MODEL_PATH", "./ml/models")

    # MFA
    MFA_ISSUER: str = os.getenv("MFA_ISSUER", "AirPower-Demo")

    # Security Disclaimer
    SECURITY_DISCLAIMER: str = (
        "Prototype for training and demonstration using synthetic data. "
        "Not connected to operational defence systems."
    )
    ML_DISCLAIMER: str = (
        "AI predictions are generated using synthetic demonstration data and are not "
        "validated for operational aircraft maintenance."
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
