"""
Simulation service for demo mode.
Generates synthetic sensor data that degrades over time.
"""
import asyncio
import math
import random
from datetime import datetime, timedelta
from typing import Dict, Optional

from sqlalchemy.orm import Session

from backend.app.models.models import (
    Aircraft, AircraftComponent, SensorReading, Prediction,
    Alert, AlertSeverity, AlertStatus, AircraftStatus,
    ComponentStatus, RiskLevel
)

# Demo simulation state per aircraft
_simulation_state: Dict[str, dict] = {}


def get_simulation_state(aircraft_id: str) -> Optional[dict]:
    return _simulation_state.get(aircraft_id)


def start_simulation(aircraft_id: str, anomaly_type: str = "normal"):
    """Start or reset simulation for an aircraft."""
    _simulation_state[aircraft_id] = {
        "step": 0,
        "anomaly_type": anomaly_type,
        "running": True,
        "started_at": datetime.utcnow().isoformat(),
        "base_temp": 75.0,
        "base_vibration": 2.0,
        "base_oil_pressure": 47.0,
        "base_fuel": 240.0,
        "base_hydraulic": 3000.0,
    }


def stop_simulation(aircraft_id: str):
    if aircraft_id in _simulation_state:
        _simulation_state[aircraft_id]["running"] = False


def reset_simulation(aircraft_id: str):
    if aircraft_id in _simulation_state:
        del _simulation_state[aircraft_id]


def compute_sensor_values(aircraft_id: str, step: int, anomaly_type: str) -> dict:
    """
    Compute sensor readings at a given simulation step.
    Anomaly types:
      - 'normal': healthy baseline
      - 'engine_anomaly': temperature + vibration rise, oil pressure drops
      - 'hydraulic_anomaly': hydraulic pressure drops
      - 'complete_failure': all sensors degrading toward failure
    """
    noise = lambda std: random.gauss(0, std)

    base_temp = 75.0
    base_vibration = 2.0
    base_oil = 47.0
    base_fuel = 240.0
    base_hydraulic = 3000.0

    # Degradation rate increases with step
    severity = min(1.0, step / 20.0)  # 0→1 over 20 steps

    if anomaly_type == "normal":
        temp = base_temp + noise(2)
        vibration = base_vibration + noise(0.1)
        oil = base_oil + noise(1.5)
        fuel = base_fuel + noise(10)
        hydraulic = base_hydraulic + noise(30)

    elif anomaly_type == "engine_anomaly":
        temp = base_temp + severity * 25 + noise(2)       # rises to ~100°C
        vibration = base_vibration + severity * 2.5 + noise(0.2)  # rises to ~4.5
        oil = base_oil - severity * 20 + noise(1.5)       # drops to ~27
        fuel = base_fuel + severity * 60 + noise(10)      # rises
        hydraulic = base_hydraulic + noise(30)

    elif anomaly_type == "hydraulic_anomaly":
        temp = base_temp + severity * 5 + noise(2)
        vibration = base_vibration + severity * 0.5 + noise(0.1)
        oil = base_oil + noise(1.5)
        fuel = base_fuel + noise(10)
        hydraulic = base_hydraulic - severity * 600 + noise(50)  # drops to ~2400

    elif anomaly_type == "complete_failure":
        temp = base_temp + severity * 30 + noise(3)
        vibration = base_vibration + severity * 3.5 + noise(0.3)
        oil = base_oil - severity * 25 + noise(2)
        fuel = base_fuel + severity * 80 + noise(15)
        hydraulic = base_hydraulic - severity * 700 + noise(60)

    else:  # default normal
        temp = base_temp + noise(2)
        vibration = base_vibration + noise(0.1)
        oil = base_oil + noise(1.5)
        fuel = base_fuel + noise(10)
        hydraulic = base_hydraulic + noise(30)

    return {
        "engine_temperature": round(temp, 2),
        "vibration": round(vibration, 3),
        "oil_pressure": round(oil, 2),
        "fuel_consumption": round(fuel, 1),
        "hydraulic_pressure": round(hydraulic, 1),
        "operating_hours": round(500 + step * 10, 0),
    }


def advance_simulation_step(aircraft_id: str, db: Session) -> dict:
    """
    Advance one simulation step: compute sensors, store reading, return result.
    """
    from backend.app.ml.predictor import get_ml_model

    state = _simulation_state.get(aircraft_id)
    if not state or not state["running"]:
        return {"error": "Simulation not running"}

    step = state["step"]
    anomaly_type = state["anomaly_type"]

    sensor_values = compute_sensor_values(aircraft_id, step, anomaly_type)

    # Get ML prediction
    try:
        model = get_ml_model()
        prediction = model.predict(sensor_values)
    except Exception as e:
        prediction = {
            "failure_risk": 0.1,
            "risk_level": "LOW",
            "rul_hours": 400,
            "health_score": 90,
            "anomaly_score": 0.1,
            "contributing_factors": [],
        }

    # Store sensor reading
    reading = SensorReading(
        aircraft_id=aircraft_id,
        timestamp=datetime.utcnow(),
        simulation_step=step,
        anomaly_flag=prediction["failure_risk"] > 0.5,
        **sensor_values,
    )
    db.add(reading)

    # Update aircraft status
    aircraft = db.query(Aircraft).filter(Aircraft.id == aircraft_id).first()
    if aircraft:
        aircraft.health_score = prediction["health_score"]
        aircraft.failure_risk = prediction["failure_risk"]
        aircraft.rul_hours = prediction["rul_hours"]

        if prediction["risk_level"] == "CRITICAL":
            aircraft.status = AircraftStatus.CRITICAL
        elif prediction["risk_level"] == "HIGH":
            aircraft.status = AircraftStatus.WARNING
        elif prediction["risk_level"] == "MEDIUM":
            aircraft.status = AircraftStatus.WARNING
        else:
            aircraft.status = AircraftStatus.AVAILABLE

        # Create alert if risk is high and step is critical moment
        if prediction["failure_risk"] > 0.7 and step in [8, 12, 16]:
            existing = db.query(Alert).filter(
                Alert.aircraft_id == aircraft_id,
                Alert.status == AlertStatus.ACTIVE,
                Alert.title.contains("anomaly detected")
            ).first()
            if not existing:
                alert = Alert(
                    aircraft_id=aircraft_id,
                    severity=AlertSeverity.CRITICAL if prediction["failure_risk"] > 0.8 else AlertSeverity.WARNING,
                    status=AlertStatus.ACTIVE,
                    title=f"Engine anomaly detected on {aircraft_id}",
                    message=f"AI system detected elevated failure risk ({prediction['failure_risk']*100:.0f}%) based on sensor anomalies. Immediate inspection recommended.",
                    recommended_action="Schedule urgent inspection. Check engine temperature, vibration, and oil pressure. Review spare parts availability.",
                    failure_risk=prediction["failure_risk"],
                    factors=prediction.get("contributing_factors", []),
                )
                db.add(alert)

    # Store prediction
    pred_record = Prediction(
        aircraft_id=aircraft_id,
        generated_at=datetime.utcnow(),
        anomaly_score=prediction["anomaly_score"],
        failure_risk=prediction["failure_risk"],
        risk_level=prediction["risk_level"],
        rul_hours=prediction["rul_hours"],
        rul_low=prediction.get("rul_low"),
        rul_high=prediction.get("rul_high"),
        confidence_level=prediction.get("confidence_level"),
        uncertainty_label=prediction.get("uncertainty_label"),
        health_score=prediction["health_score"],
        contributing_factors=prediction["contributing_factors"],
    )
    db.add(pred_record)

    try:
        db.commit()
    except Exception as e:
        db.rollback()

    # Advance step
    state["step"] = step + 1

    return {
        "step": step,
        "sensor_values": sensor_values,
        "prediction": prediction,
        "aircraft_id": aircraft_id,
        "anomaly_type": anomaly_type,
    }
