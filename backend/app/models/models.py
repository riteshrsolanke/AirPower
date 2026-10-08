"""
SQLAlchemy ORM Models for the Air Power Predictive Maintenance Platform.
All data is SYNTHETIC for training/demonstration purposes.

Phase 1 additions (2026-10-03):
  AircraftMissionStatus, AirBase, Crew, WeaponType, WeaponInventory,
  AircraftWeaponCompat, Mission, AirspaceZone, ThreatZone,
  WeatherCondition, MissionPlan, PlanAssignment, DataFeed, EventLog
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, String, Text, JSON, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from backend.app.db.database import Base


def generate_uuid():
    return str(uuid.uuid4())


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────

class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    MAINTENANCE_MANAGER = "MAINTENANCE_MANAGER"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"


class AircraftStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    GROUNDED = "GROUNDED"


class ComponentStatus(str, enum.Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    FAILED = "FAILED"


class MaintenanceStatus(str, enum.Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MaintenancePriority(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertSeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    READ = "READ"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class RiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SpareStatus(str, enum.Enum):
    NORMAL = "NORMAL"
    LOW = "LOW"
    CRITICAL = "CRITICAL"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class AircraftMissionStatus(str, enum.Enum):
    """Derived from health/RUL; used by the planning engine."""
    CAPABLE   = "CAPABLE"    # RUL >= 50 h AND failure_risk < 0.50
    LIMITED   = "LIMITED"    # RUL 20-50 h OR failure_risk 0.50-0.75
    GROUNDED  = "GROUNDED"   # RUL < 20 h OR failure_risk > 0.75


class MissionStatus(str, enum.Enum):
    PENDING   = "PENDING"
    PLANNED   = "PLANNED"
    ACTIVE    = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ABORTED   = "ABORTED"


class PlanStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ZoneType(str, enum.Enum):
    RESTRICTED = "RESTRICTED"
    CORRIDOR   = "CORRIDOR"
    DANGER     = "DANGER"


class ThreatType(str, enum.Enum):
    SAM        = "SAM"        # Surface-to-Air Missile
    AAA        = "AAA"        # Anti-Aircraft Artillery
    FIGHTER    = "FIGHTER"    # Hostile fighter patrol
    RADAR      = "RADAR"      # Early-warning radar
    UNKNOWN    = "UNKNOWN"


class FeedStatus(str, enum.Enum):
    LIVE     = "LIVE"
    STALE    = "STALE"
    DEGRADED = "DEGRADED"
    DOWN     = "DOWN"


class EventType(str, enum.Enum):
    AIRCRAFT_UNSERVICEABLE  = "AIRCRAFT_UNSERVICEABLE"
    NEW_THREAT              = "NEW_THREAT"
    WEATHER_CLOSURE         = "WEATHER_CLOSURE"
    AIRSPACE_CLOSURE        = "AIRSPACE_CLOSURE"
    NEW_PRIORITY_MISSION    = "NEW_PRIORITY_MISSION"
    CREW_UNAVAILABLE        = "CREW_UNAVAILABLE"
    FEED_DEGRADED           = "FEED_DEGRADED"


# ─────────────────────────────────────────────
# User Model
# ─────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.VIEWER)
    full_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    is_locked = Column(Boolean, default=False)
    # Phase 6: ABAC attributes
    clearance_level = Column(String, default="UNCLASSIFIED")
    department = Column(String, default="HQ")
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    mfa_enabled = Column(Boolean, default=False)
    mfa_secret = Column(String, nullable=True)  # Stored encrypted in production
    mfa_recovery_codes = Column(JSON, nullable=True)
    last_login = Column(DateTime, nullable=True)
    password_changed_at = Column(DateTime, nullable=True)
    must_change_password = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="refresh_tokens")


# ─────────────────────────────────────────────
# Aircraft Models
# ─────────────────────────────────────────────

class Aircraft(Base):
    __tablename__ = "aircraft"

    id = Column(String, primary_key=True)  # e.g., DEMO-A001
    model = Column(String, nullable=False)
    serial_number = Column(String, unique=True, nullable=False)
    manufacture_year = Column(Integer)
    status = Column(Enum(AircraftStatus), default=AircraftStatus.AVAILABLE)
    health_score = Column(Float, default=100.0)  # 0–100
    failure_risk = Column(Float, default=0.0)  # 0–1
    rul_hours = Column(Float, default=500.0)  # Remaining Useful Life in flight hours
    total_flight_hours = Column(Float, default=0.0)
    last_maintenance_date = Column(DateTime, nullable=True)
    next_maintenance_date = Column(DateTime, nullable=True)
    location = Column(String, default="Base Alpha")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Phase 1: mission-capability status derived from health/RUL
    mission_capable_status = Column(
        Enum(AircraftMissionStatus),
        default=AircraftMissionStatus.CAPABLE,
        nullable=True,
    )
    # Phase 1: FK to operational base (nullable — keeps old rows valid)
    base_id = Column(String, ForeignKey("air_bases.id", ondelete="SET NULL"), nullable=True)

    # Phase 4: Synthetic range, fuel, and payload capabilities
    range_km = Column(Float, default=2000.0)
    fuel_capacity = Column(Float, default=5000.0)
    payload_capacity = Column(Float, default=4000.0)

    components = relationship("AircraftComponent", back_populates="aircraft", cascade="all, delete-orphan")
    sensor_readings = relationship("SensorReading", back_populates="aircraft", cascade="all, delete-orphan")
    maintenance_records = relationship("MaintenanceRecord", back_populates="aircraft", cascade="all, delete-orphan")
    predictions = relationship("Prediction", back_populates="aircraft", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="aircraft", cascade="all, delete-orphan")
    weapon_compatibilities = relationship("AircraftWeaponCompat", back_populates="aircraft", cascade="all, delete-orphan")
    plan_assignments = relationship("PlanAssignment", back_populates="aircraft")


class AircraftComponent(Base):
    __tablename__ = "aircraft_components"

    id = Column(String, primary_key=True, default=generate_uuid)
    aircraft_id = Column(String, ForeignKey("aircraft.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)  # ENGINE, HYDRAULICS, AVIONICS, FUEL_SYSTEM, STRUCTURE
    component_type = Column(String, nullable=False)
    status = Column(Enum(ComponentStatus), default=ComponentStatus.NORMAL)
    health_score = Column(Float, default=100.0)
    failure_risk = Column(Float, default=0.0)
    rul_hours = Column(Float, default=500.0)
    operating_hours = Column(Float, default=0.0)
    last_maintenance_date = Column(DateTime, nullable=True)
    anomaly_score = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    aircraft = relationship("Aircraft", back_populates="components")


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id = Column(String, primary_key=True, default=generate_uuid)
    aircraft_id = Column(String, ForeignKey("aircraft.id", ondelete="CASCADE"), nullable=False)
    component_id = Column(String, ForeignKey("aircraft_components.id", ondelete="SET NULL"), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    engine_temperature = Column(Float)  # Celsius
    vibration = Column(Float)  # mm/s
    oil_pressure = Column(Float)  # PSI
    fuel_consumption = Column(Float)  # L/hr
    hydraulic_pressure = Column(Float)  # PSI
    operating_hours = Column(Float)  # hours
    anomaly_flag = Column(Boolean, default=False)
    simulation_step = Column(Integer, default=0)

    aircraft = relationship("Aircraft", back_populates="sensor_readings")

    __table_args__ = (
        Index("idx_sensor_aircraft_time", "aircraft_id", "timestamp"),
    )


# ─────────────────────────────────────────────
# Prediction Model
# ─────────────────────────────────────────────

class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(String, primary_key=True, default=generate_uuid)
    aircraft_id = Column(String, ForeignKey("aircraft.id", ondelete="CASCADE"), nullable=False)
    component_id = Column(String, ForeignKey("aircraft_components.id", ondelete="SET NULL"), nullable=True)
    generated_at = Column(DateTime, default=datetime.utcnow, index=True)
    anomaly_score = Column(Float)
    failure_risk = Column(Float)
    risk_level = Column(Enum(RiskLevel))
    rul_hours = Column(Float)
    rul_low = Column(Float, nullable=True)
    rul_high = Column(Float, nullable=True)
    confidence_level = Column(String, nullable=True)
    uncertainty_label = Column(String, nullable=True)
    health_score = Column(Float)
    contributing_factors = Column(JSON)  # List of factor dicts
    model_version = Column(String, default="synthetic-v1")
    disclaimer = Column(String, default="Generated from synthetic demonstration data.")
    generated_by = Column(String, nullable=True)  # User ID who triggered it

    aircraft = relationship("Aircraft", back_populates="predictions")


# ─────────────────────────────────────────────
# Maintenance Model
# ─────────────────────────────────────────────

class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"

    id = Column(String, primary_key=True, default=generate_uuid)
    aircraft_id = Column(String, ForeignKey("aircraft.id", ondelete="CASCADE"), nullable=False)
    component_id = Column(String, ForeignKey("aircraft_components.id", ondelete="SET NULL"), nullable=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    status = Column(Enum(MaintenanceStatus), default=MaintenanceStatus.PLANNED)
    priority = Column(Enum(MaintenancePriority), default=MaintenancePriority.MEDIUM)
    assigned_to = Column(String, nullable=True)
    scheduled_start = Column(DateTime)
    scheduled_end = Column(DateTime)
    actual_start = Column(DateTime, nullable=True)
    actual_end = Column(DateTime, nullable=True)
    estimated_duration_hours = Column(Float, default=4.0)
    spare_parts_required = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    aircraft = relationship("Aircraft", back_populates="maintenance_records")


# ─────────────────────────────────────────────
# Spare Parts Model
# ─────────────────────────────────────────────

class SparePart(Base):
    __tablename__ = "spare_parts"

    id = Column(String, primary_key=True, default=generate_uuid)
    part_number = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    category = Column(String)
    compatible_components = Column(JSON)  # List of component types
    current_stock = Column(Integer, default=0)
    minimum_stock = Column(Integer, default=5)
    reserved_stock = Column(Integer, default=0)
    unit_cost = Column(Float, default=0.0)
    status = Column(Enum(SpareStatus), default=SpareStatus.NORMAL)
    supplier = Column(String, nullable=True)
    lead_time_days = Column(Integer, default=7)
    location = Column(String, default="Warehouse A")
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def available_stock(self):
        return max(0, self.current_stock - self.reserved_stock)


# ─────────────────────────────────────────────
# Alert Model
# ─────────────────────────────────────────────

class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String, primary_key=True, default=generate_uuid)
    aircraft_id = Column(String, ForeignKey("aircraft.id", ondelete="CASCADE"), nullable=True)
    component_id = Column(String, ForeignKey("aircraft_components.id", ondelete="SET NULL"), nullable=True)
    severity = Column(Enum(AlertSeverity), nullable=False)
    status = Column(Enum(AlertStatus), default=AlertStatus.ACTIVE)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    recommended_action = Column(Text, nullable=True)
    failure_risk = Column(Float, nullable=True)
    factors = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    acknowledged_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    aircraft = relationship("Aircraft", back_populates="alerts")


# ─────────────────────────────────────────────
# Audit Log Model
# ─────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username = Column(String, nullable=True)
    role = Column(String, nullable=True)
    action = Column(String, nullable=False)  # e.g., LOGIN_SUCCESS, AIRCRAFT_UPDATED
    resource = Column(String, nullable=True)  # e.g., DEMO-A001
    result = Column(String, nullable=False)  # SUCCESS, FAILURE, DENIED
    details = Column(JSON, nullable=True)
    ip_address = Column(String, nullable=True)
    
    # Phase 6: Audit chain verification (Merkle-tree / Blockchain style)
    previous_hash = Column(String, nullable=True)
    current_hash = Column(String, nullable=True)

    user = relationship("User", back_populates="audit_logs")


# ─────────────────────────────────────────────
# Demo Scenario Model
# ─────────────────────────────────────────────

class DemoScenario(Base):
    __tablename__ = "demo_scenarios"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    aircraft_id = Column(String, ForeignKey("aircraft.id", ondelete="CASCADE"), nullable=False)
    is_active = Column(Boolean, default=False)
    current_step = Column(Integer, default=0)
    scenario_data = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ═══════════════════════════════════════════════════════════════
# PHASE 1 — Operational Planning Models
# All synthetic data. Not connected to operational systems.
# ═══════════════════════════════════════════════════════════════


class AirBase(Base):
    """Synthetic air base / forward operating location."""
    __tablename__ = "air_bases"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False, unique=True)          # e.g. "Base Alpha"
    icao_code = Column(String, nullable=True)                   # 4-letter synthetic code
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    elevation_ft = Column(Integer, default=0)
    runway_status = Column(String, default="OPERATIONAL")       # OPERATIONAL / DEGRADED / CLOSED
    max_aircraft_capacity = Column(Integer, default=20)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # relationships
    crews   = relationship("Crew", back_populates="base")
    aircraft = relationship("Aircraft", foreign_keys="Aircraft.base_id")
    weapon_inventories = relationship("WeaponInventory", back_populates="base", cascade="all, delete-orphan")
    weather_conditions = relationship("WeatherCondition", back_populates="base", cascade="all, delete-orphan")


class Crew(Base):
    """Synthetic aircrew record."""
    __tablename__ = "crews"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    rank = Column(String, nullable=False)                        # e.g. "Sqn Ldr"
    role = Column(String, nullable=False)                        # PILOT / WSO / NAVIGATOR / LOADMASTER
    # Comma-separated synthetic aircraft model types this crew is qualified on
    aircraft_qualifications = Column(JSON, nullable=True)        # ["DEMO-FIGHTER-Alpha", ...]
    duty_hours_used = Column(Float, default=0.0)                 # hours flown in current duty cycle
    max_duty_hours = Column(Float, default=12.0)                 # regulatory limit (synthetic)
    rest_status = Column(String, default="RESTED")               # RESTED / FATIGUED / MANDATORY_REST
    is_available = Column(Boolean, default=True)
    base_id = Column(String, ForeignKey("air_bases.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    base = relationship("AirBase", back_populates="crews")
    plan_assignments = relationship("PlanAssignment", back_populates="crew")
    duty_logs = relationship("CrewDutyLog", back_populates="crew", cascade="all, delete-orphan")
    overrides = relationship("CrewOverride", back_populates="crew", cascade="all, delete-orphan")


class CrewDutyLog(Base):
    """Log of crew duty periods."""
    __tablename__ = "crew_duty_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    crew_id = Column(String, ForeignKey("crews.id", ondelete="CASCADE"), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    sortie_type = Column(String, nullable=True) # e.g. COMBAT, TRAINING, TRANSIT
    night_flag = Column(Boolean, default=False)
    
    crew = relationship("Crew", back_populates="duty_logs")


class CrewOverride(Base):
    """Override requests for UNFIT crew members."""
    __tablename__ = "crew_overrides"

    id = Column(String, primary_key=True, default=generate_uuid)
    crew_id = Column(String, ForeignKey("crews.id", ondelete="CASCADE"), nullable=False)
    requested_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    justification = Column(Text, nullable=False)
    status = Column(String, default="PENDING") # PENDING, APPROVED, REJECTED, EXPIRED
    approved_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    crew = relationship("Crew", back_populates="overrides")
    requester = relationship("User", foreign_keys=[requested_by])
    approver = relationship("User", foreign_keys=[approved_by])


class WeaponType(Base):
    """Catalogue of synthetic weapon types."""
    __tablename__ = "weapon_types"

    id = Column(String, primary_key=True, default=generate_uuid)
    code = Column(String, unique=True, nullable=False)           # e.g. "AAM-DEMO-1"
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)                    # AAM / AGM / BOMB / TORPEDO / POD
    weight_kg = Column(Float, default=0.0)
    range_km = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)

    inventories = relationship("WeaponInventory", back_populates="weapon_type", cascade="all, delete-orphan")
    compatibilities = relationship("AircraftWeaponCompat", back_populates="weapon_type", cascade="all, delete-orphan")


class WeaponInventory(Base):
    """Stock of a weapon type at a specific base."""
    __tablename__ = "weapon_inventories"

    id = Column(String, primary_key=True, default=generate_uuid)
    base_id = Column(String, ForeignKey("air_bases.id", ondelete="CASCADE"), nullable=False)
    weapon_type_id = Column(String, ForeignKey("weapon_types.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, default=0)
    reserved_quantity = Column(Integer, default=0)               # held for active plans
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    base = relationship("AirBase", back_populates="weapon_inventories")
    weapon_type = relationship("WeaponType", back_populates="inventories")

    __table_args__ = (
        UniqueConstraint("base_id", "weapon_type_id", name="uq_base_weapon"),
    )


class AircraftWeaponCompat(Base):
    """Which weapon types a given aircraft model can carry."""
    __tablename__ = "aircraft_weapon_compat"

    id = Column(String, primary_key=True, default=generate_uuid)
    aircraft_id = Column(String, ForeignKey("aircraft.id", ondelete="CASCADE"), nullable=False)
    weapon_type_id = Column(String, ForeignKey("weapon_types.id", ondelete="CASCADE"), nullable=False)
    max_load = Column(Integer, default=2)                        # max pylons/stations for this weapon

    aircraft = relationship("Aircraft", back_populates="weapon_compatibilities")
    weapon_type = relationship("WeaponType", back_populates="compatibilities")

    __table_args__ = (
        UniqueConstraint("aircraft_id", "weapon_type_id", name="uq_aircraft_weapon"),
    )


class Mission(Base):
    """A synthetic air tasking order mission."""
    __tablename__ = "missions"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    mission_type = Column(String, nullable=False)                # CAS / DCA / SEAD / ISR / TRANSPORT / SAR
    priority = Column(Integer, default=3)                       # 1=highest … 5=lowest
    status = Column(Enum(MissionStatus), default=MissionStatus.PENDING)
    # Target area encoded as {"lat": float, "lon": float, "radius_km": float}
    target_area = Column(JSON, nullable=True)
    # Earliest/latest start time (UTC)
    time_window_start = Column(DateTime, nullable=True)
    time_window_end   = Column(DateTime, nullable=True)
    estimated_duration_hours = Column(Float, default=2.0)
    required_aircraft_type = Column(String, nullable=True)       # must match Aircraft.model
    required_weapon_code   = Column(String, nullable=True)       # must match WeaponType.code
    min_aircraft_count = Column(Integer, default=1)
    # Phase 4: Synthetic mission distance and payload requirements
    distance_km = Column(Float, default=500.0)
    required_payload = Column(Float, default=1500.0)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    plan_assignments = relationship("PlanAssignment", back_populates="mission")


class AirspaceZone(Base):
    """Synthetic airspace zone (restricted or corridor)."""
    __tablename__ = "airspace_zones"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    zone_type = Column(Enum(ZoneType), nullable=False)           # RESTRICTED / CORRIDOR / DANGER
    # Geometry: {"type": "circle", "center": [lat, lon], "radius_km": r}
    #        or {"type": "polygon", "coordinates": [[lat,lon], ...]}
    geometry = Column(JSON, nullable=False)
    floor_ft  = Column(Integer, default=0)                       # altitude floor
    ceiling_ft = Column(Integer, default=60000)                  # altitude ceiling
    active_from = Column(DateTime, nullable=True)
    active_until = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)


class ThreatZone(Base):
    """Synthetic threat envelope (SAM, AAA, fighter CAP, etc.)."""
    __tablename__ = "threat_zones"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    threat_type = Column(Enum(ThreatType), nullable=False)
    center_lat = Column(Float, nullable=False)
    center_lon = Column(Float, nullable=False)
    radius_km  = Column(Float, nullable=False)
    severity   = Column(Integer, default=3)                      # 1=low … 5=critical
    is_active  = Column(Boolean, default=True)
    detected_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)


class WeatherCondition(Base):
    """Snapshot of synthetic weather at a base or target area."""
    __tablename__ = "weather_conditions"

    id = Column(String, primary_key=True, default=generate_uuid)
    base_id  = Column(String, ForeignKey("air_bases.id", ondelete="SET NULL"), nullable=True)
    # Free-text label for target areas (e.g. "ALPHA-SECTOR")
    area_label = Column(String, nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow)
    visibility_km = Column(Float, default=10.0)
    wind_speed_kts = Column(Float, default=0.0)
    wind_direction_deg = Column(Integer, default=0)
    ceiling_ft = Column(Integer, default=10000)
    temperature_c = Column(Float, default=20.0)
    is_go = Column(Boolean, default=True)                        # True = weather allows flying
    go_no_go_reason = Column(String, nullable=True)
    confidence = Column(Float, default=1.0)                      # 0–1 data confidence
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    base = relationship("AirBase", back_populates="weather_conditions")


class MissionPlan(Base):
    """A versioned collection of mission assignments (output of the optimizer)."""
    __tablename__ = "mission_plans"

    id = Column(String, primary_key=True, default=generate_uuid)
    version = Column(Integer, default=1)
    status = Column(Enum(PlanStatus), default=PlanStatus.PROPOSED)
    coverage_pct = Column(Float, default=0.0)                    # missions covered / total
    risk_score   = Column(Float, default=0.0)                    # aggregate threat exposure
    resource_use = Column(JSON, nullable=True)                   # {"aircraft": n, "crews": n, ...}
    summary      = Column(Text, nullable=True)                   # plain-language summary
    created_by   = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by  = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at  = Column(DateTime, nullable=True)
    rejected_by  = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rejected_at  = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    # Link to the event that triggered replanning (nullable for baseline plan)
    trigger_event_id = Column(String, ForeignKey("event_logs.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assignments = relationship("PlanAssignment", back_populates="plan", cascade="all, delete-orphan")
    creator  = relationship("User", foreign_keys=[created_by])
    approver = relationship("User", foreign_keys=[approved_by])
    rejector = relationship("User", foreign_keys=[rejected_by])
    trigger_event = relationship("EventLog", foreign_keys=[trigger_event_id])


class PlanAssignment(Base):
    """One aircraft+crew+weapon assignment within a MissionPlan."""
    __tablename__ = "plan_assignments"

    id = Column(String, primary_key=True, default=generate_uuid)
    plan_id    = Column(String, ForeignKey("mission_plans.id", ondelete="CASCADE"), nullable=False)
    mission_id = Column(String, ForeignKey("missions.id", ondelete="CASCADE"), nullable=False)
    aircraft_id = Column(String, ForeignKey("aircraft.id", ondelete="SET NULL"), nullable=True)
    crew_id     = Column(String, ForeignKey("crews.id",    ondelete="SET NULL"), nullable=True)
    weapon_type_id = Column(String, ForeignKey("weapon_types.id", ondelete="SET NULL"), nullable=True)
    weapon_quantity = Column(Integer, default=0)
    # Plain-language explanation generated by the optimizer
    explanation = Column(Text, nullable=True)
    # Risk metrics for this specific assignment
    threat_exposure_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    plan    = relationship("MissionPlan", back_populates="assignments")
    mission = relationship("Mission",    back_populates="plan_assignments")
    aircraft = relationship("Aircraft",  back_populates="plan_assignments")
    crew    = relationship("Crew",       back_populates="plan_assignments")
    weapon_type = relationship("WeaponType")


class DataFeed(Base):
    """Registry of simulated external data feeds for the fusion layer."""
    __tablename__ = "data_feeds"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, unique=True, nullable=False)           # e.g. "aircraft_health"
    description = Column(String, nullable=True)
    # Expected update interval in seconds
    update_interval_seconds = Column(Integer, default=60)
    last_update = Column(DateTime, nullable=True)
    status = Column(Enum(FeedStatus), default=FeedStatus.LIVE)
    # 0–1; degrades when feed is stale
    confidence = Column(Float, default=1.0)
    # Last known payload hash (SHA-256) for integrity tracking
    last_payload_hash = Column(String, nullable=True)
    # Whether incoming payloads require HMAC signature (Phase 5)
    requires_signature = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EventLog(Base):
    """Timeline of injected operational events that trigger replanning."""
    __tablename__ = "event_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    event_type = Column(Enum(EventType), nullable=False)
    # Affected resource (aircraft ID, zone name, base name, etc.)
    affected_resource = Column(String, nullable=True)
    payload = Column(JSON, nullable=True)                        # event-specific data
    injected_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    injected_at = Column(DateTime, default=datetime.utcnow)
    # Which plan version was active before this event
    previous_plan_id = Column(String, ForeignKey("mission_plans.id", ondelete="SET NULL"), nullable=True)
    # Which plan was produced in response
    resulting_plan_id = Column(String, ForeignKey("mission_plans.id", ondelete="SET NULL"), nullable=True)
    replanning_time_ms = Column(Integer, nullable=True)          # measured solver time

    injector = relationship("User",        foreign_keys=[injected_by])
    previous_plan = relationship("MissionPlan", foreign_keys=[previous_plan_id])
    resulting_plan = relationship("MissionPlan", foreign_keys=[resulting_plan_id])
