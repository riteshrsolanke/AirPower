"""
Crew Fatigue Modeling Service
SYNTHETIC DEMONSTRATION MODEL — Not medically validated.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Any

def compute_fatigue_score(duty_logs: List[Any], current_time: datetime = None) -> dict:
    """
    Compute a 0-100 fatigue score based on duty logs.
    Formula:
    - Duty hours in last 24h (weight: 2.0 per hour > 8)
    - Duty hours in last 7d (weight: 0.5 per hour > 40)
    - Hours since last rest (weight: 1.5 per hour > 12)
    - Consecutive duty days (weight: 5.0 per day > 4)
    - Night sorties (weight: 10.0 per sortie in last 48h)
    - Circadian penalty (weight: 15.0 if current time is 02:00-05:00 local)
    - Number of sorties today (weight: 3.0 per sortie > 1)
    """
    if current_time is None:
        current_time = datetime.utcnow()
        
    factors = []
    score = 0.0
    
    # Simple mock calculation if no logs
    if not duty_logs:
        return {
            "score": 0,
            "status": "FIT",
            "factors": [{"name": "Baseline", "impact": 0}]
        }
        
    # Sort logs by start time
    logs = sorted(duty_logs, key=lambda x: x.start_time)
    
    last_24h_logs = [l for l in logs if current_time - l.end_time <= timedelta(hours=24)]
    last_7d_logs = [l for l in logs if current_time - l.end_time <= timedelta(days=7)]
    
    # 1. Duty hours in last 24h
    hours_24h = sum((l.end_time - l.start_time).total_seconds() / 3600 for l in last_24h_logs)
    if hours_24h > 8:
        impact = (hours_24h - 8) * 2.0
        score += impact
        factors.append({"name": "High 24h Duty", "impact": round(impact, 1), "details": f"{round(hours_24h, 1)}h"})

    # 2. Duty hours in last 7d
    hours_7d = sum((l.end_time - l.start_time).total_seconds() / 3600 for l in last_7d_logs)
    if hours_7d > 40:
        impact = (hours_7d - 40) * 0.5
        score += impact
        factors.append({"name": "High 7d Duty", "impact": round(impact, 1), "details": f"{round(hours_7d, 1)}h"})
        
    # 3. Hours since last rest
    if logs:
        last_log = logs[-1]
        hours_since_rest = (current_time - last_log.end_time).total_seconds() / 3600
        if hours_since_rest > 12 and hours_since_rest < 24: # assuming rest is > 8h break
            impact = (hours_since_rest - 12) * 1.5
            score += impact
            factors.append({"name": "Time since rest", "impact": round(impact, 1), "details": f"{round(hours_since_rest, 1)}h"})
            
    # 4. Night sorties
    night_sorties = sum(1 for l in last_7d_logs if l.night_flag and current_time - l.end_time <= timedelta(hours=48))
    if night_sorties > 0:
        impact = night_sorties * 10.0
        score += impact
        factors.append({"name": "Recent Night Sorties", "impact": round(impact, 1), "details": f"{night_sorties} sorties"})
        
    # 5. Circadian penalty (simplified: UTC used as proxy for demo)
    if 2 <= current_time.hour <= 5:
        score += 15.0
        factors.append({"name": "Circadian Low", "impact": 15.0, "details": f"Time: {current_time.hour:02d}:00"})
        
    # 6. Sorties today
    sorties_today = len(last_24h_logs)
    if sorties_today > 1:
        impact = (sorties_today - 1) * 3.0
        score += impact
        factors.append({"name": "Multiple Sorties Today", "impact": round(impact, 1), "details": f"{sorties_today} sorties"})

    score = min(100, max(0, score))
    
    if score < 40:
        status = "FIT"
    elif score < 70:
        status = "CAUTION"
    else:
        status = "UNFIT"
        
    return {
        "score": round(score, 1),
        "status": status,
        "factors": sorted(factors, key=lambda x: x["impact"], reverse=True)
    }
