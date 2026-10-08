import pytest
from backend.app.ml.predictor import get_ml_model
from backend.app.models.models import Aircraft
from backend.app.db.database import SessionLocal

def test_rul_confidence_bounds():
    db = SessionLocal()
    try:
        model = get_ml_model()
        aircrafts = db.query(Aircraft).limit(5).all()
        assert len(aircrafts) > 0, "No aircraft found in DB. Seed DB first."
        for aircraft in aircrafts:
            # mock sensor data based on reasonable values
            sensor_data = {
                "engine_temperature": 75,
                "vibration": 2.0,
                "oil_pressure": 47,
                "fuel_consumption": 240,
                "hydraulic_pressure": 3000,
                "operating_hours": 1000,
            }
            prediction = model.predict(sensor_data)
            
            rul = prediction["rul_hours"]
            rul_low = prediction["rul_low"]
            rul_high = prediction["rul_high"]
            
            assert rul_low <= rul, f"rul_low ({rul_low}) > rul ({rul})"
            assert rul <= rul_high, f"rul ({rul}) > rul_high ({rul_high})"
            assert prediction["uncertainty_label"] in ["LOW", "MEDIUM", "HIGH"]
            assert prediction["confidence_level"] == "80%"
    finally:
        db.close()
