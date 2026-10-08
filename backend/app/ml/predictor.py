"""
Predictive Maintenance ML Service.
IMPORTANT: All models are trained on SYNTHETIC data for demonstration only.
Not validated for operational aircraft maintenance.
"""
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import joblib
from pathlib import Path

from sklearn.ensemble import RandomForestClassifier, IsolationForest, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

MODEL_DIR = Path(__file__).parent.parent.parent / "ml" / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

DISCLAIMER = "AI predictions are generated using synthetic demonstration data and are not validated for operational aircraft maintenance."

# Sensor feature names
FEATURES = [
    "engine_temperature",
    "vibration",
    "oil_pressure",
    "fuel_consumption",
    "hydraulic_pressure",
    "operating_hours",
]

# Normal operating ranges for synthetic data
NORMAL_RANGES = {
    "engine_temperature": (65, 85),      # Celsius
    "vibration": (1.5, 2.5),             # mm/s
    "oil_pressure": (40, 55),             # PSI
    "fuel_consumption": (200, 280),       # L/hr
    "hydraulic_pressure": (2900, 3100),   # PSI
    "operating_hours": (0, 10000),        # hours
}

# Warning thresholds
WARNING_THRESHOLDS = {
    "engine_temperature": 90,
    "vibration": 3.0,
    "oil_pressure": 35,
    "fuel_consumption": 300,
    "hydraulic_pressure": 2700,
}

# Critical thresholds
CRITICAL_THRESHOLDS = {
    "engine_temperature": 100,
    "vibration": 4.0,
    "oil_pressure": 28,
    "fuel_consumption": 330,
    "hydraulic_pressure": 2500,
}


def _generate_synthetic_training_data(n_samples: int = 2000) -> pd.DataFrame:
    """Generate synthetic aircraft sensor data for training. NOT real data."""
    np.random.seed(42)
    data = []

    for i in range(n_samples):
        # Healthy samples (60%)
        if i < int(n_samples * 0.6):
            label = 0
            temp = np.random.normal(75, 5)
            vibration = np.random.normal(2.0, 0.3)
            oil_pressure = np.random.normal(47, 3)
            fuel_consumption = np.random.normal(240, 20)
            hydraulic_pressure = np.random.normal(3000, 50)
            operating_hours = np.random.uniform(100, 4000)
        # Warning samples (25%)
        elif i < int(n_samples * 0.85):
            label = 1
            temp = np.random.normal(87, 5)
            vibration = np.random.normal(3.2, 0.4)
            oil_pressure = np.random.normal(37, 3)
            fuel_consumption = np.random.normal(295, 25)
            hydraulic_pressure = np.random.normal(2750, 80)
            operating_hours = np.random.uniform(3000, 7000)
        # Critical/failing samples (15%)
        else:
            label = 2
            temp = np.random.normal(98, 6)
            vibration = np.random.normal(4.2, 0.5)
            oil_pressure = np.random.normal(27, 3)
            fuel_consumption = np.random.normal(325, 30)
            hydraulic_pressure = np.random.normal(2500, 100)
            operating_hours = np.random.uniform(6000, 10000)

        rul = max(5, 500 - (operating_hours * 0.05) - (temp - 75) * 2 - (vibration - 2.0) * 20 + np.random.normal(0, 10))

        data.append({
            "engine_temperature": temp,
            "vibration": vibration,
            "oil_pressure": oil_pressure,
            "fuel_consumption": fuel_consumption,
            "hydraulic_pressure": hydraulic_pressure,
            "operating_hours": operating_hours,
            "label": label,
            "rul": max(5, rul),
        })

    return pd.DataFrame(data)


class PredictiveMaintenanceModel:
    """
    Ensemble ML model for aircraft health prediction.
    SYNTHETIC DEMONSTRATION ONLY — Not operationally certified.
    """

    def __init__(self):
        self.risk_classifier = None
        self.rul_regressor_median = None
        self.rul_regressor_low = None
        self.rul_regressor_high = None
        self.anomaly_detector = None
        self.scaler = None
        self.is_trained = False
        self._load_or_train()

    def _load_or_train(self):
        """Load saved models or train fresh ones."""
        risk_path = MODEL_DIR / "risk_classifier.joblib"
        rul_median_path = MODEL_DIR / "rul_regressor_median.joblib"
        rul_low_path = MODEL_DIR / "rul_regressor_low.joblib"
        rul_high_path = MODEL_DIR / "rul_regressor_high.joblib"
        anomaly_path = MODEL_DIR / "anomaly_detector.joblib"
        scaler_path = MODEL_DIR / "scaler.joblib"

        if all(p.exists() for p in [risk_path, rul_median_path, rul_low_path, rul_high_path, anomaly_path, scaler_path]):
            try:
                self.risk_classifier = joblib.load(risk_path)
                self.rul_regressor_median = joblib.load(rul_median_path)
                self.rul_regressor_low = joblib.load(rul_low_path)
                self.rul_regressor_high = joblib.load(rul_high_path)
                self.anomaly_detector = joblib.load(anomaly_path)
                self.scaler = joblib.load(scaler_path)
                self.is_trained = True
                return
            except Exception:
                pass

        self._train()

    def _train(self):
        """Train models on synthetic data."""
        df = _generate_synthetic_training_data(2000)
        X = df[FEATURES].values
        y_label = df["label"].values
        y_rul = df["rul"].values

        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        # Risk classifier: 0=healthy, 1=warning, 2=critical
        self.risk_classifier = RandomForestClassifier(
            n_estimators=100, max_depth=8, random_state=42, n_jobs=-1
        )
        self.risk_classifier.fit(X_scaled, y_label)

        # RUL regressors (quantile)
        self.rul_regressor_median = GradientBoostingRegressor(
            loss="quantile", alpha=0.5, n_estimators=100, max_depth=5, random_state=42
        )
        self.rul_regressor_median.fit(X_scaled, y_rul)

        self.rul_regressor_low = GradientBoostingRegressor(
            loss="quantile", alpha=0.1, n_estimators=100, max_depth=5, random_state=42
        )
        self.rul_regressor_low.fit(X_scaled, y_rul)

        self.rul_regressor_high = GradientBoostingRegressor(
            loss="quantile", alpha=0.9, n_estimators=100, max_depth=5, random_state=42
        )
        self.rul_regressor_high.fit(X_scaled, y_rul)

        # Anomaly detector (uses only healthy samples)
        X_healthy = X_scaled[y_label == 0]
        self.anomaly_detector = IsolationForest(
            n_estimators=100, contamination=0.1, random_state=42
        )
        self.anomaly_detector.fit(X_healthy)

        # Save models
        joblib.dump(self.risk_classifier, MODEL_DIR / "risk_classifier.joblib")
        joblib.dump(self.rul_regressor_median, MODEL_DIR / "rul_regressor_median.joblib")
        joblib.dump(self.rul_regressor_low, MODEL_DIR / "rul_regressor_low.joblib")
        joblib.dump(self.rul_regressor_high, MODEL_DIR / "rul_regressor_high.joblib")
        joblib.dump(self.anomaly_detector, MODEL_DIR / "anomaly_detector.joblib")
        joblib.dump(self.scaler, MODEL_DIR / "scaler.joblib")

        self.is_trained = True

    def predict(self, sensor_data: dict) -> dict:
        """
        Generate health prediction from sensor readings.
        Returns anomaly score, failure risk, RUL, and contributing factors.
        """
        if not self.is_trained:
            raise RuntimeError("Model not trained")

        # Extract features
        features = np.array([[
            sensor_data.get("engine_temperature", 75),
            sensor_data.get("vibration", 2.0),
            sensor_data.get("oil_pressure", 47),
            sensor_data.get("fuel_consumption", 240),
            sensor_data.get("hydraulic_pressure", 3000),
            sensor_data.get("operating_hours", 1000),
        ]])

        X_scaled = self.scaler.transform(features)

        # Risk classification
        risk_proba = self.risk_classifier.predict_proba(X_scaled)[0]
        # risk_proba: [P(healthy), P(warning), P(critical)]
        failure_risk = risk_proba[1] * 0.5 + risk_proba[2] * 1.0  # weighted

        # Risk level
        if failure_risk < 0.25:
            risk_level = "LOW"
        elif failure_risk < 0.55:
            risk_level = "MEDIUM"
        elif failure_risk < 0.75:
            risk_level = "HIGH"
        else:
            risk_level = "CRITICAL"

        # Anomaly score (convert IsolationForest score to 0–1)
        anomaly_score_raw = self.anomaly_detector.score_samples(X_scaled)[0]
        anomaly_score = float(np.clip(1 - (anomaly_score_raw + 0.5), 0, 1))

        # RUL prediction
        rul_pred = float(max(5, self.rul_regressor_median.predict(X_scaled)[0]))
        rul_low = float(max(5, self.rul_regressor_low.predict(X_scaled)[0]))
        rul_high = float(max(5, self.rul_regressor_high.predict(X_scaled)[0]))

        # Ensure bounds are strictly <= and >= median
        rul_low = min(rul_low, rul_pred)
        rul_high = max(rul_high, rul_pred)

        interval_width = rul_high - rul_low
        relative_width = interval_width / rul_pred if rul_pred > 0 else 0
        if relative_width < 0.2:
            uncertainty_label = "LOW"
        elif relative_width < 0.5:
            uncertainty_label = "MEDIUM"
        else:
            uncertainty_label = "HIGH"

        # Health score (inverse of failure risk, normalized)
        health_score = float(np.clip(100 * (1 - failure_risk), 0, 100))

        # Contributing factors (feature importances + threshold analysis)
        contributing_factors = self._compute_contributing_factors(sensor_data)

        return {
            "anomaly_score": round(anomaly_score, 3),
            "failure_risk": round(float(failure_risk), 3),
            "risk_level": risk_level,
            "rul_hours": round(rul_pred, 1),
            "rul_low": round(rul_low, 1),
            "rul_high": round(rul_high, 1),
            "confidence_level": "80%",
            "uncertainty_label": uncertainty_label,
            "health_score": round(health_score, 1),
            "contributing_factors": contributing_factors,
            "model_version": "synthetic-rf-v1",
            "disclaimer": DISCLAIMER,
        }

    def _compute_contributing_factors(self, sensor_data: dict) -> List[dict]:
        """Identify which sensors are deviating from normal ranges."""
        factors = []

        checks = [
            ("engine_temperature", sensor_data.get("engine_temperature", 75),
             WARNING_THRESHOLDS["engine_temperature"], CRITICAL_THRESHOLDS["engine_temperature"], "↑", "High"),
            ("vibration", sensor_data.get("vibration", 2.0),
             WARNING_THRESHOLDS["vibration"], CRITICAL_THRESHOLDS["vibration"], "↑", "Elevated"),
            ("oil_pressure", sensor_data.get("oil_pressure", 47),
             WARNING_THRESHOLDS["oil_pressure"], CRITICAL_THRESHOLDS["oil_pressure"], "↓", "Low", True),
            ("fuel_consumption", sensor_data.get("fuel_consumption", 240),
             WARNING_THRESHOLDS["fuel_consumption"], CRITICAL_THRESHOLDS["fuel_consumption"], "↑", "Excessive"),
            ("hydraulic_pressure", sensor_data.get("hydraulic_pressure", 3000),
             WARNING_THRESHOLDS["hydraulic_pressure"], CRITICAL_THRESHOLDS["hydraulic_pressure"], "↓", "Low", True),
        ]

        for check in checks:
            name = check[0]
            value = check[1]
            warn_thresh = check[2]
            crit_thresh = check[3]
            direction = check[4]
            severity_label = check[5]
            is_inverted = len(check) > 6 and check[6]

            if is_inverted:
                deviation_warn = value < warn_thresh
                deviation_crit = value < crit_thresh
            else:
                deviation_warn = value > warn_thresh
                deviation_crit = value > crit_thresh

            if deviation_crit:
                severity = "CRITICAL"
                impact = 0.9
            elif deviation_warn:
                severity = "WARNING"
                impact = 0.5
            else:
                continue

            factors.append({
                "sensor": name.replace("_", " ").title(),
                "value": round(value, 2),
                "direction": direction,
                "severity": severity,
                "impact": impact,
                "description": f"{severity_label} {name.replace('_', ' ')} reading: {round(value, 2)}",
            })

        # Operating hours factor
        op_hours = sensor_data.get("operating_hours", 0)
        if op_hours > 6000:
            factors.append({
                "sensor": "Operating Hours",
                "value": round(op_hours, 0),
                "direction": "↑",
                "severity": "WARNING",
                "impact": 0.4,
                "description": f"High cumulative operating hours: {op_hours:.0f}h",
            })

        # Sort by impact
        factors.sort(key=lambda x: x["impact"], reverse=True)
        return factors[:5]  # Top 5 factors


# Singleton instance
_model_instance: Optional[PredictiveMaintenanceModel] = None


def get_ml_model() -> PredictiveMaintenanceModel:
    """Get or create the singleton ML model instance."""
    global _model_instance
    if _model_instance is None:
        _model_instance = PredictiveMaintenanceModel()
    return _model_instance
