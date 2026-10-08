"""
Secure Audit Logging Service (Phase 6).
Implements a tamper-evident audit chain using cryptographic hashing.
"""

import hashlib
import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.app.models.models import AuditLog, User


def calculate_hash(prev_hash: str, timestamp: datetime, action: str, resource: str, result: str, user_id: str) -> str:
    """Calculate SHA-256 hash for the log entry."""
    data = f"{prev_hash}|{timestamp.isoformat()}|{action}|{resource}|{result}|{user_id}"
    return hashlib.sha256(data.encode()).hexdigest()


def log_audit(
    db: Session,
    user: Optional[User],
    action: str,
    resource: str,
    result: str,
    ip: str,
    details: dict = None
) -> AuditLog:
    """Creates a chained audit log entry."""
    
    # Get previous log for the chain
    last_log = db.query(AuditLog).filter(AuditLog.current_hash.isnot(None)).order_by(desc(AuditLog.timestamp), desc(AuditLog.id)).first()
    prev_hash = last_log.current_hash if last_log and last_log.current_hash else "GENESIS"
    
    now = datetime.utcnow()
    user_id = user.id if user else "SYSTEM"
    
    current_hash = calculate_hash(prev_hash, now, action, resource, result, user_id)
    
    new_log = AuditLog(
        timestamp=now,
        user_id=user.id if user else None,
        username=user.username if user else "SYSTEM",
        role=user.role.value if user else "SYSTEM",
        action=action,
        resource=resource,
        result=result,
        details=details,
        ip_address=ip,
        previous_hash=prev_hash,
        current_hash=current_hash
    )
    
    db.add(new_log)
    db.commit()
    db.refresh(new_log)
    return new_log


def verify_chain(db: Session) -> dict:
    """
    Recalculates hashes from the beginning of time to verify the chain is intact.
    Returns whether the chain is valid and the ID of the broken link if any.
    """
    logs = db.query(AuditLog).filter(AuditLog.current_hash.isnot(None)).order_by(AuditLog.timestamp, AuditLog.id).all()
    
    expected_prev = "GENESIS"
    
    for log in logs:
        # Check if the chain connects
        if log.previous_hash != expected_prev:
            return {"valid": False, "broken_at_id": log.id, "reason": "Chain link broken (prev_hash mismatch)"}
        
        # Recalculate hash
        user_id = log.user_id if log.user_id else "SYSTEM"
        recalc = calculate_hash(log.previous_hash, log.timestamp, log.action, log.resource, log.result, user_id)
        if recalc != log.current_hash:
            return {"valid": False, "broken_at_id": log.id, "reason": "Data tampering detected (current_hash mismatch)"}
        
        expected_prev = log.current_hash
            
    return {"valid": True, "broken_at_id": None, "reason": "Chain intact"}
