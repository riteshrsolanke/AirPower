from backend.app.services.audit import log_audit
"""
Authentication API routes.
Implements: Login, MFA, Refresh, Logout, Password Change, MFA Setup.
"""
import hashlib
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, validator
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.security import (
    verify_password, hash_password, create_access_token,
    create_refresh_token, decode_token, hash_token,
    generate_totp_secret, get_totp_uri, generate_qr_code_base64,
    verify_totp, generate_recovery_codes, hash_recovery_code,
    validate_password_strength,
)
from backend.app.db.database import get_db
from backend.app.models.models import User, RefreshToken, AuditLog, UserRole
from backend.app.core.deps import get_current_active_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ── Request/Response Schemas ──────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str  # username or email
    password: str


class MFAVerifyRequest(BaseModel):
    temp_token: str
    code: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    requires_mfa: bool = False
    temp_token: Optional[str] = None
    user: Optional[dict] = None


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

    @validator("new_password")
    def validate_new_password(cls, v):
        errors = validate_password_strength(v)
        if errors:
            raise ValueError("; ".join(errors))
        return v


class MFAEnrollResponse(BaseModel):
    secret: str
    qr_code: str
    uri: str
    recovery_codes: list


class MFAEnrollConfirmRequest(BaseModel):
    code: str
    secret: str


# ── Audit Helper ──────────────────────────────────────────────────────────────

def _audit(db, user, action, resource, result, ip, details=None):
    log_audit(db, user, action, resource, result, ip, details)

def _get_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/login")
async def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """
    Step 1: Authenticate with username/password.
    Returns either full tokens (no MFA) or temp_token (MFA required).
    """
    ip = _get_ip(request)

    # Find user by username or email
    user = (
        db.query(User).filter(User.username == req.username).first()
        or db.query(User).filter(User.email == req.username).first()
    )

    if not user:
        _audit(db, None, "LOGIN_FAILURE", req.username, "FAILURE", ip, {"reason": "user_not_found"})
        # Generic message to prevent username enumeration
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Check lockout
    if user.is_locked and user.locked_until and datetime.utcnow() < user.locked_until:
        remaining = int((user.locked_until - datetime.utcnow()).total_seconds() / 60)
        _audit(db, user, "LOGIN_FAILURE", user.username, "FAILURE", ip, {"reason": "account_locked"})
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account locked. Try again in {remaining} minutes.",
        )

    # Verify password
    if not verify_password(req.password, user.hashed_password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            user.is_locked = True
            user.locked_until = datetime.utcnow() + timedelta(minutes=settings.LOCKOUT_DURATION_MINUTES)
            _audit(db, user, "LOGIN_FAILURE", user.username, "FAILURE", ip, {"reason": "max_attempts_exceeded"})
        else:
            _audit(db, user, "LOGIN_FAILURE", user.username, "FAILURE", ip,
                   {"reason": "wrong_password", "attempts": user.failed_login_attempts})
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account is inactive")

    # Reset failed attempts on success
    user.failed_login_attempts = 0
    user.is_locked = False
    user.locked_until = None

    # If MFA enabled, return temp token
    if user.mfa_enabled:
        temp_token = create_access_token(
            {"sub": user.id, "type_override": "mfa_pending"},
            expires_delta=timedelta(minutes=5),
        )
        db.commit()
        _audit(db, user, "LOGIN_MFA_REQUIRED", user.username, "PENDING", ip)
        return {"requires_mfa": True, "temp_token": temp_token, "token_type": "bearer"}

    # No MFA: issue full tokens
    return _issue_tokens(user, db, ip)


@router.post("/mfa/verify")
async def verify_mfa(req: MFAVerifyRequest, request: Request, db: Session = Depends(get_db)):
    """Step 2: Verify TOTP code after successful password login."""
    ip = _get_ip(request)

    payload = decode_token(req.temp_token)
    if not payload or payload.get("type_override") != "mfa_pending":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired MFA session")

    user = db.query(User).filter(User.id == payload.get("sub")).first()
    if not user or not user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA not configured")

    # Try TOTP code
    if not verify_totp(user.mfa_secret, req.code):
        # Try recovery codes
        recovery_used = False
        if user.mfa_recovery_codes:
            code_hash = hash_recovery_code(req.code.upper())
            codes = user.mfa_recovery_codes.copy()
            if code_hash in codes:
                codes.remove(code_hash)
                user.mfa_recovery_codes = codes
                db.commit()
                recovery_used = True

        if not recovery_used:
            _audit(db, user, "MFA_FAILURE", user.username, "FAILURE", ip)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA code")

    _audit(db, user, "MFA_SUCCESS" if not False else "MFA_RECOVERY_USED", user.username, "SUCCESS", ip)
    return _issue_tokens(user, db, ip)


@router.post("/refresh")
async def refresh_token(req: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    """Rotate refresh token and issue new access token."""
    ip = _get_ip(request)
    payload = decode_token(req.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    token_hash = hash_token(req.refresh_token)
    stored = db.query(RefreshToken).filter(
        RefreshToken.token_hash == token_hash,
        RefreshToken.revoked == False,
    ).first()

    if not stored or datetime.utcnow() > stored.expires_at:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired or revoked")

    user = db.query(User).filter(User.id == payload.get("sub")).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Revoke old token (rotation)
    stored.revoked = True
    db.commit()

    return _issue_tokens(user, db, ip)


@router.post("/logout")
async def logout(request: Request, current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """Revoke all refresh tokens for the current user."""
    ip = _get_ip(request)
    db.query(RefreshToken).filter(
        RefreshToken.user_id == current_user.id,
        RefreshToken.revoked == False,
    ).update({"revoked": True})
    db.commit()
    _audit(db, current_user, "LOGOUT", current_user.username, "SUCCESS", ip)
    return {"message": "Logged out successfully"}


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_active_user)):
    """Get current user profile."""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "role": current_user.role.value,
        "mfa_enabled": current_user.mfa_enabled,
        "last_login": current_user.last_login.isoformat() if current_user.last_login else None,
        "must_change_password": current_user.must_change_password,
    }


@router.post("/change-password")
async def change_password(
    req: PasswordChangeRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Change the current user's password."""
    ip = _get_ip(request)
    if not verify_password(req.current_password, current_user.hashed_password):
        _audit(db, current_user, "PASSWORD_CHANGE_FAILED", current_user.username, "FAILURE", ip)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    current_user.hashed_password = hash_password(req.new_password)
    current_user.password_changed_at = datetime.utcnow()
    current_user.must_change_password = False
    db.commit()
    _audit(db, current_user, "PASSWORD_CHANGED", current_user.username, "SUCCESS", ip)
    return {"message": "Password changed successfully"}


@router.post("/mfa/enroll")
async def mfa_enroll(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Generate MFA secret and QR code for enrollment."""
    secret = generate_totp_secret()
    uri = get_totp_uri(secret, current_user.username)
    qr_code = generate_qr_code_base64(uri)
    recovery_codes = generate_recovery_codes(8)
    hashed_codes = [hash_recovery_code(c) for c in recovery_codes]

    # Temporarily store secret (confirmed on next step)
    current_user.mfa_secret = secret
    current_user.mfa_recovery_codes = hashed_codes
    db.commit()

    return {
        "secret": secret,
        "uri": uri,
        "qr_code": f"data:image/png;base64,{qr_code}",
        "recovery_codes": recovery_codes,
    }


@router.post("/mfa/confirm")
async def mfa_confirm(
    req: MFAEnrollConfirmRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Confirm MFA enrollment by verifying the first TOTP code."""
    ip = _get_ip(request)
    if not verify_totp(req.secret, req.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code")

    current_user.mfa_secret = req.secret
    current_user.mfa_enabled = True
    db.commit()
    _audit(db, current_user, "MFA_ENABLED", current_user.username, "SUCCESS", ip)
    return {"message": "MFA enabled successfully"}


@router.post("/mfa/disable")
async def mfa_disable(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Disable MFA for current user (Admin can disable for others)."""
    ip = _get_ip(request)
    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    current_user.mfa_recovery_codes = None
    db.commit()
    _audit(db, current_user, "MFA_DISABLED", current_user.username, "SUCCESS", ip)
    return {"message": "MFA disabled"}


# ── Internal Helper ───────────────────────────────────────────────────────────

def _issue_tokens(user: User, db: Session, ip: str) -> dict:
    """Create access + refresh tokens, record in DB, update last login."""
    access_token = create_access_token({"sub": user.id, "role": user.role.value})
    refresh_token_str = create_refresh_token({"sub": user.id})

    token_hash = hash_token(refresh_token_str)
    rt = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(rt)
    user.last_login = datetime.utcnow()
    db.commit()

    _audit(db, user, "LOGIN_SUCCESS", user.username, "SUCCESS", ip)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
        "requires_mfa": False,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role.value,
            "full_name": user.full_name,
            "mfa_enabled": user.mfa_enabled,
        },
    }
