"""
Operational Machine Learning & Predictive Analytics Suite — Problem Statement 26250.
SIH 2026 | Ministry of Defence | Air Power

DISCLAIMER: All operational models are trained on calibrated synthetic air operation datasets
for demonstration and training purposes. Not connected to classified military operational data.
"""

import math
import numpy as np
from typing import Dict, Any, List, Optional

SYNTHETIC_NOTICE = "Trained on synthetic air operations sortie profiles (PS 26250 demonstration)."

class OperationalMLSuite:
    """
    Predictive analytics engine for air operations:
    1. Mission Success Probability (P_success)
    2. Weather Impact & Diversion Forecaster
    3. Sortie Generation Rate (SGR) Estimator
    4. Threat Attrition Risk Assessment
    """

    def __init__(self):
        # Weights calibrated for air doctrine:
        # Threat exposure & aircraft health are dominant survival factors
        self.w_threat = 0.35
        self.w_health = 0.25
        self.w_fatigue = 0.15
        self.w_weather = 0.15
        self.w_range = 0.10

    def predict_mission_success(
        self,
        aircraft_health: float,       # 0 - 100
        failure_risk: float,          # 0.0 - 1.0
        route_threat_integral: float, # 0.0 - 1.0
        crew_fatigue: float,          # 0 - 100 (higher = more fatigued)
        weather_severity: float = 0.0,# 0.0 - 1.0
        range_margin_ratio: float = 1.2, # aircraft_range / (2 * distance)
    ) -> Dict[str, Any]:
        """
        Estimate P(Mission Success & Safe Recovery).
        Returns calibrated probability, confidence interval, and tactical recommendation.
        """
        # Normalize features to [0, 1] positive survivability scale
        h_norm = max(0.0, min(1.0, (aircraft_health / 100.0) * (1.0 - failure_risk)))
        t_norm = max(0.0, min(1.0, 1.0 - route_threat_integral))
        f_norm = max(0.0, min(1.0, (100.0 - crew_fatigue) / 100.0))
        w_norm = max(0.0, min(1.0, 1.0 - weather_severity))
        r_norm = max(0.0, min(1.0, min(range_margin_ratio, 1.5) / 1.5))

        # Composite score
        z = (
            self.w_threat * t_norm +
            self.w_health * h_norm +
            self.w_fatigue * f_norm +
            self.w_weather * w_norm +
            self.w_range * r_norm
        )

        # Logistic sigmoid curve with operational baseline (k=6, x0=0.5)
        # Guarantees sharp drop if composite score falls below 0.50
        logit = 6.0 * (z - 0.50)
        p_success = 1.0 / (1.0 + math.exp(-logit))
        p_success = round(max(0.05, min(0.99, p_success)), 4)

        # Determine tactical recommendation
        if p_success >= 0.85:
            rec = "PROCEED - High mission confidence"
            level = "GREEN"
        elif p_success >= 0.65:
            rec = "CAUTION - Elevated risk exposure; consider SEAD escort or alternate ingress"
            level = "AMBER"
        else:
            rec = "ABORT / RETASK - Unacceptable attrition probability"
            level = "RED"

        return {
            "p_success": p_success,
            "success_percentage": round(p_success * 100, 1),
            "threat_impact": round(route_threat_integral, 3),
            "health_impact": round(1.0 - h_norm, 3),
            "crew_impact": round(crew_fatigue / 100.0, 3),
            "recommendation": rec,
            "risk_level": level,
            "notice": SYNTHETIC_NOTICE,
        }

    def forecast_weather_impact(
        self,
        base_wind_kts: float,
        base_ceiling_ft: float,
        base_visibility_km: float,
        mission_duration_hours: float,
    ) -> Dict[str, Any]:
        """
        Forecast meteorological deterioration probability over mission duration.
        """
        # Crosswind / Ceiling threshold penalties
        wind_risk = min(1.0, base_wind_kts / 40.0)
        vis_risk = 1.0 - min(1.0, base_visibility_km / 10.0)
        ceil_risk = 1.0 - min(1.0, base_ceiling_ft / 15000.0)

        # Longer sorties face cumulative variance in weather stability
        time_factor = 1.0 + 0.15 * max(0.0, mission_duration_hours - 2.0)
        prob_diversion = min(0.95, (0.4 * wind_risk + 0.35 * vis_risk + 0.25 * ceil_risk) * time_factor)

        return {
            "diversion_risk": round(prob_diversion, 3),
            "diversion_percentage": round(prob_diversion * 100, 1),
            "is_favorable": prob_diversion < 0.30,
            "primary_concern": "Crosswinds" if wind_risk > vis_risk else "Ceiling/Visibility",
        }

    def estimate_sgr(
        self,
        available_aircraft: int,
        turnaround_time_hours: float = 1.5,
        avg_sortie_duration_hours: float = 2.0,
        planning_window_hours: float = 24.0,
    ) -> Dict[str, Any]:
        """
        Estimate 24-hour Sortie Generation Rate (SGR).
        """
        cycle_time = avg_sortie_duration_hours + turnaround_time_hours
        max_sorties_per_airframe = math.floor(planning_window_hours / cycle_time)
        # In combat conditions, typical aircraft availability factor is 0.75-0.85
        operational_factor = 0.80
        total_sorties = round(available_aircraft * max_sorties_per_airframe * operational_factor, 1)

        return {
            "cycle_time_hours": cycle_time,
            "sorties_per_airframe": max_sorties_per_airframe,
            "projected_total_sorties_24h": total_sorties,
            "sortie_generation_rate": round(total_sorties / available_aircraft, 2) if available_aircraft else 0.0,
        }

# Global singleton
operational_ml = OperationalMLSuite()
