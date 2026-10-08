"""
Authentication and authorization dependencies for FastAPI.
Enforces role-based access control on the backend.
"""
from datetime import datetime
from typing import Optional, List

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from backend.app.core.security import decode_token
from backend.app.db.database import get_db
from backend.app.models.models import User, UserRole, AuditLog

security = HTTPBearer(auto_error=False)


def _log_audit(db: Session, user: Optional[User], action: str, resource: str,
               result: str, ip: str, details: dict = None):
    """Write an audit log entry."""
    try:
        log = AuditLog(
            user_id=user.id if user else None,
            username=user.username if user else "anonymous",
            role=user.role.value if user else None,
            action=action,
            resource=resource,
            result=result,
            ip_address=ip,
            details=details,
        )
        db.add(log)
        db.commit()
    except Exception:
        pass  # Audit log failure should not block the request


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Extract and validate current user from JWT Bearer token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not credentials:
        raise credentials_exception

    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise credentials_exception

    user_id = payload.get("sub")
    if not user_id:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise credentials_exception

    if user.is_locked:
        if user.locked_until and datetime.utcnow() < user.locked_until:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Account is temporarily locked due to too many failed login attempts",
            )
        else:
            user.is_locked = False
            user.failed_login_attempts = 0
            db.commit()

    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Ensure the user is active."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user


def require_roles(*roles: UserRole):
    """Factory: returns a dependency that requires one of the given roles."""
    def checker(
        request: Request,
        current_user: User = Depends(get_current_active_user),
        db: Session = Depends(get_db),
    ) -> User:
        if current_user.role not in roles:
            ip = request.client.host if request.client else "unknown"
            _log_audit(
                db, current_user,
                "UNAUTHORIZED_ACCESS_ATTEMPT",
                str(request.url.path),
                "DENIED",
                ip,
                {"required_roles": [r.value for r in roles]},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user
    return checker


# Convenience role-check dependencies
require_admin = require_roles(UserRole.ADMIN)
require_manager_or_above = require_roles(UserRole.ADMIN, UserRole.MAINTENANCE_MANAGER)
require_analyst_or_above = require_roles(
    UserRole.ADMIN, UserRole.MAINTENANCE_MANAGER, UserRole.ANALYST
)
require_any_authenticated = require_roles(
    UserRole.ADMIN, UserRole.MAINTENANCE_MANAGER, UserRole.ANALYST, UserRole.VIEWER
)
