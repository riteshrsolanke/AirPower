import pytest
from datetime import datetime, timedelta
from backend.app.services.fatigue import compute_fatigue_score
from backend.app.models.models import CrewDutyLog

def test_fatigue_score_monotonic():
    now = datetime.utcnow()
    
    # Base: 1 hour duty
    logs1 = [
        CrewDutyLog(start_time=now - timedelta(hours=2), end_time=now - timedelta(hours=1))
    ]
    score1 = compute_fatigue_score(logs1, current_time=now)["score"]
    
    # 9 hours duty
    logs2 = [
        CrewDutyLog(start_time=now - timedelta(hours=10), end_time=now - timedelta(hours=1))
    ]
    score2 = compute_fatigue_score(logs2, current_time=now)["score"]
    
    # 15 hours duty
    logs3 = [
        CrewDutyLog(start_time=now - timedelta(hours=16), end_time=now - timedelta(hours=1))
    ]
    score3 = compute_fatigue_score(logs3, current_time=now)["score"]
    
    assert score1 <= score2 <= score3
