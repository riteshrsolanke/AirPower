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

    @classmethod
    def _init_keys(cls):
        priv_path = CORE_DIR / "private.pem"
        pub_path = CORE_DIR / "public.pem"
        if priv_path.exists() and pub_path.exists():
            try:
                return priv_path.read_text(), pub_path.read_text()
            except Exception:
                pass
        try:
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import serialization
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            priv_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ).decode("utf-8")
            pub_pem = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ).decode("utf-8")
            priv_path.write_text(priv_pem)
            pub_path.write_text(pub_pem)
            return priv_pem, pub_pem
        except Exception:
            return "fallback_private", "fallback_public"

    _keys = None

    @property
    def PRIVATE_KEY(self) -> str:
        if Settings._keys is None:
            Settings._keys = Settings._init_keys()
        return Settings._keys[0]

    @property
    def PUBLIC_KEY(self) -> str:
        if Settings._keys is None:
            Settings._keys = Settings._init_keys()
        return Settings._keys[1]

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
