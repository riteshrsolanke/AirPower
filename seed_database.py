"""
Database seeder — generates 30 synthetic aircraft with components, sensors, maintenance, spares, and demo accounts.
ALL DATA IS SYNTHETIC FOR DEMONSTRATION PURPOSES ONLY.
DO NOT USE real military aircraft identifiers.
"""
import sys
import os
import random
import hashlib
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.db.database import SessionLocal, engine
from backend.app.models.models import (
    Base, User, UserRole, Aircraft, AircraftComponent, ComponentStatus,
    SensorReading, Prediction, MaintenanceRecord, MaintenanceStatus,
    MaintenancePriority, SparePart, SpareStatus, Alert, AlertSeverity,
    AlertStatus, AuditLog, AircraftStatus, RiskLevel
)
from backend.app.core.security import hash_password, generate_recovery_codes, hash_recovery_code
from backend.app.services.seed_ops import seed_operational_data

# Create all tables
Base.metadata.create_all(bind=engine)

random.seed(42)

SYNTHETIC_AIRCRAFT_MODELS = [
    "DEMO-FIGHTER-Alpha",
    "DEMO-TRAINER-Bravo",
    "DEMO-TRANSPORT-Charlie",
    "DEMO-HELICOPTER-Delta",
    "DEMO-MARITIME-Echo",
]

COMPONENT_TYPES = [
    ("ENGINE", "Propulsion"),
    ("HYDRAULICS", "Hydraulic System"),
    ("AVIONICS", "Avionics Suite"),
    ("FUEL_SYSTEM", "Fuel System"),
    ("STRUCTURE", "Airframe Structure"),
]

LOCATIONS = ["Base Alpha", "Base Bravo", "Base Charlie", "Forward Station Delta"]

SPARE_PARTS = [
    ("HYD-PUMP-001", "Hydraulic Pump Assembly", "HYDRAULICS", 2, 5),
    ("ENG-FILTER-001", "Engine Oil Filter", "ENGINE", 12, 5),
    ("ENG-BLADE-001", "Turbine Blade Set", "ENGINE", 1, 3),
    ("FUEL-SEAL-001", "Fuel System Seal Kit", "FUEL_SYSTEM", 8, 6),
    ("AVI-SENSOR-001", "Avionics Sensor Module", "AVIONICS", 4, 3),
    ("HYD-SEAL-001", "Hydraulic Seal Set", "HYDRAULICS", 3, 5),
    ("ENG-BEARING-001", "Engine Main Bearing", "ENGINE", 5, 4),
    ("STRUCT-RIVET-001", "Structural Fastener Kit", "STRUCTURE", 20, 10),
    ("FUEL-PUMP-001", "Fuel Boost Pump", "FUEL_SYSTEM", 6, 4),
    ("AVI-GYRO-001", "Gyroscope Module", "AVIONICS", 2, 3),
    ("HYD-ACTUATOR-001", "Hydraulic Actuator", "HYDRAULICS", 1, 4),
    ("ENG-IGNITER-001", "Engine Igniter Assembly", "ENGINE", 7, 5),
]


def create_demo_accounts(db):
    """Create demo accounts with secure hashed passwords."""
    print("\n🔐 Creating demo accounts...")
    accounts = [
        {
            "email": "admin@demo.local",
            "username": "admin",
            "password": "123",
            "role": UserRole.ADMIN,
            "full_name": "Demo Administrator",
            "clearance_level": "TOP SECRET",
            "department": "HQ"
        },
        {
            "email": "maintenance@demo.local",
            "username": "maintenance_mgr",
            "password": "123",
            "role": UserRole.MAINTENANCE_MANAGER,
            "full_name": "Maintenance Manager",
            "clearance_level": "SECRET",
            "department": "MAINTENANCE"
        },
        {
            "email": "analyst@demo.local",
            "username": "analyst",
            "password": "123",
            "role": UserRole.ANALYST,
            "full_name": "Data Analyst",
            "clearance_level": "UNCLASSIFIED",
            "department": "OPERATIONS"
        },
        {
            "email": "viewer@demo.local",
            "username": "viewer",
            "password": "123",
            "role": UserRole.VIEWER,
            "full_name": "Read-Only Viewer",
        },
    ]

    created = []
    for acc in accounts:
        existing = db.query(User).filter(User.username == acc["username"]).first()
        if not existing:
            user = User(
                email=acc["email"],
                username=acc["username"],
                hashed_password=hash_password(acc["password"]),
                role=acc["role"],
                full_name=acc["full_name"],
                clearance_level=acc.get("clearance_level", "UNCLASSIFIED"),
                department=acc.get("department", "HQ"),
                is_active=True,
            )
            db.add(user)
            created.append(acc)
        else:
            existing.hashed_password = hash_password(acc["password"])
            existing.is_active = True
            existing.failed_login_attempts = 0
            existing.is_locked = False

    db.commit()

    print("\n" + "=" * 60)
    print("  DEMO CREDENTIALS (Development & Evaluation)")
    print("  ALL PASSWORDS SET TO: 123")
    print("=" * 60)
    for acc in accounts:
        role_str = acc["role"].value.ljust(20)
        print(f"  {role_str} | {acc['username']:20} | 123")
    print("=" * 60 + "\n")


def create_aircraft(db):
    """Create 30 synthetic aircraft with components."""
    print("✈️  Creating synthetic aircraft fleet...")

    aircraft_configs = []
    for i in range(1, 31):
        aid = f"DEMO-A{i:03d}"
        health = random.uniform(55, 98)
        failure_risk = random.uniform(0.02, 0.9)
        rul = random.uniform(20, 500)

        if failure_risk > 0.75 or health < 65:
            status = random.choice([AircraftStatus.CRITICAL, AircraftStatus.WARNING])
        elif failure_risk > 0.5 or health < 75:
            status = AircraftStatus.WARNING
        elif random.random() < 0.15:
            status = AircraftStatus.MAINTENANCE
        else:
            status = AircraftStatus.AVAILABLE

        model = random.choice(SYNTHETIC_AIRCRAFT_MODELS)
        location = random.choice(LOCATIONS)

        existing = db.query(Aircraft).filter(Aircraft.id == aid).first()
        if existing:
            continue

        a = Aircraft(
            id=aid,
            model=model,
            serial_number=f"SYN-SN-{1000 + i}",
            manufacture_year=random.randint(2005, 2020),
            status=status,
            health_score=round(health, 1),
            failure_risk=round(failure_risk, 3),
            rul_hours=round(rul, 1),
            total_flight_hours=round(random.uniform(500, 9000), 0),
            last_maintenance_date=datetime.utcnow() - timedelta(days=random.randint(10, 200)),
            next_maintenance_date=datetime.utcnow() + timedelta(days=random.randint(5, 90)),
            location=location,
            notes=f"Synthetic demonstration aircraft {aid}. All data is simulated.",
        )
        db.add(a)
        aircraft_configs.append((aid, health, failure_risk))

        # Add components
        for (comp_type, comp_name) in COMPONENT_TYPES:
            comp_health = min(100, health + random.uniform(-15, 15))
            comp_risk = min(1.0, failure_risk + random.uniform(-0.2, 0.2))

            if comp_health < 65:
                comp_status = ComponentStatus.CRITICAL
            elif comp_health < 75:
                comp_status = ComponentStatus.WARNING
            else:
                comp_status = ComponentStatus.NORMAL

            c = AircraftComponent(
                aircraft_id=aid,
                name=comp_type,
                component_type=comp_name,
                status=comp_status,
                health_score=round(max(20, comp_health), 1),
                failure_risk=round(max(0, min(1, comp_risk)), 3),
                rul_hours=round(random.uniform(10, 600), 1),
                operating_hours=round(random.uniform(200, 8000), 0),
                anomaly_score=round(random.uniform(0, 0.6), 3),
                last_maintenance_date=datetime.utcnow() - timedelta(days=random.randint(5, 300)),
            )
            db.add(c)

    db.commit()
    print(f"  → Created {len(aircraft_configs)} aircraft with {len(aircraft_configs) * 5} components")
    return aircraft_configs


def create_sensor_history(db, aircraft_ids):
    """Create historical sensor readings (30 per aircraft)."""
    print("📡 Generating sensor history...")
    count = 0
    for aid in aircraft_ids:
        aircraft = db.query(Aircraft).filter(Aircraft.id == aid).first()
        if not aircraft:
            continue
        base_health = aircraft.health_score

        for j in range(30):
            degradation = (30 - j) / 30.0
            hrs_ago = 30 - j

            # Engine temperature rises as health drops
            temp = 75 + (100 - base_health) * 0.3 * (1 - degradation) + random.gauss(0, 2)
            vib = 2.0 + (100 - base_health) * 0.025 * (1 - degradation) + random.gauss(0, 0.1)
            oil = 47 - (100 - base_health) * 0.2 * (1 - degradation) + random.gauss(0, 1.5)
            fuel = 240 + (100 - base_health) * 0.6 * (1 - degradation) + random.gauss(0, 10)
            hydraulic = 3000 - (100 - base_health) * 5 * (1 - degradation) + random.gauss(0, 30)

            r = SensorReading(
                aircraft_id=aid,
                timestamp=datetime.utcnow() - timedelta(hours=hrs_ago),
                engine_temperature=round(temp, 2),
                vibration=round(vib, 3),
                oil_pressure=round(oil, 2),
                fuel_consumption=round(fuel, 1),
                hydraulic_pressure=round(hydraulic, 1),
                operating_hours=round(1000 + j * 10, 0),
                anomaly_flag=base_health < 70,
                simulation_step=j,
            )
            db.add(r)
            count += 1

    db.commit()
    print(f"  → Created {count} sensor readings")


def create_predictions(db, aircraft_ids):
    """Create ML predictions for each aircraft."""
    print("🤖 Generating predictions...")
    from backend.app.ml.predictor import get_ml_model
    model = get_ml_model()
    count = 0

    for aid in aircraft_ids:
        aircraft = db.query(Aircraft).filter(Aircraft.id == aid).first()
        reading = (
            db.query(SensorReading)
            .filter(SensorReading.aircraft_id == aid)
            .order_by(SensorReading.timestamp.desc())
            .first()
        )
        if not reading:
            continue

        try:
            result = model.predict({
                "engine_temperature": reading.engine_temperature,
                "vibration": reading.vibration,
                "oil_pressure": reading.oil_pressure,
                "fuel_consumption": reading.fuel_consumption,
                "hydraulic_pressure": reading.hydraulic_pressure,
                "operating_hours": reading.operating_hours,
            })
            pred = Prediction(
                aircraft_id=aid,
                failure_risk=result["failure_risk"],
                risk_level=RiskLevel(result["risk_level"]),
                rul_hours=result["rul_hours"],
                rul_low=result.get("rul_low"),
                rul_high=result.get("rul_high"),
                confidence_level=result.get("confidence_level"),
                uncertainty_label=result.get("uncertainty_label"),
                health_score=result["health_score"],
                anomaly_score=result["anomaly_score"],
                contributing_factors=result["contributing_factors"],
            )
            db.add(pred)
            count += 1
        except Exception as e:
            print(f"  Prediction failed for {aid}: {e}")

    db.commit()
    print(f"  → Created {count} predictions")


def create_maintenance_records(db, aircraft_ids):
    """Create synthetic maintenance records."""
    print("🔧 Creating maintenance records...")
    count = 0
    for i, aid in enumerate(aircraft_ids[:15]):
        if i < 5:
            status = MaintenanceStatus.ACTIVE
        elif i < 10:
            status = MaintenanceStatus.PLANNED
        else:
            status = MaintenanceStatus.COMPLETED

        priority = random.choice(list(MaintenancePriority))
        start = datetime.utcnow() - timedelta(days=random.randint(0, 30))
        r = MaintenanceRecord(
            aircraft_id=aid,
            title=f"Scheduled {'Engine' if i % 2 == 0 else 'Hydraulic'} Inspection",
            description=f"Synthetic maintenance record for demonstration. Aircraft {aid}.",
            status=status,
            priority=priority,
            scheduled_start=start,
            scheduled_end=start + timedelta(hours=8),
            actual_start=start if status in [MaintenanceStatus.ACTIVE, MaintenanceStatus.COMPLETED] else None,
            actual_end=start + timedelta(hours=7) if status == MaintenanceStatus.COMPLETED else None,
            estimated_duration_hours=8,
            spare_parts_required=["ENG-FILTER-001", "HYD-SEAL-001"],
            notes="Synthetic maintenance demonstration record.",
        )
        db.add(r)
        count += 1

    db.commit()
    print(f"  → Created {count} maintenance records")


def create_spare_parts(db):
    """Create spare parts inventory."""
    print("📦 Creating spare parts inventory...")
    count = 0
    for (pn, name, category, stock, minimum) in SPARE_PARTS:
        existing = db.query(SparePart).filter(SparePart.part_number == pn).first()
        if existing:
            continue

        available = max(0, stock - random.randint(0, 1))
        if stock == 0:
            status = SpareStatus.OUT_OF_STOCK
        elif available < minimum * 0.5:
            status = SpareStatus.CRITICAL
        elif available < minimum:
            status = SpareStatus.LOW
        else:
            status = SpareStatus.NORMAL

        s = SparePart(
            part_number=pn,
            name=name,
            category=category,
            compatible_components=[category],
            current_stock=stock,
            minimum_stock=minimum,
            reserved_stock=random.randint(0, 1),
            unit_cost=round(random.uniform(500, 50000), 2),
            status=status,
            supplier=f"DEMO-SUPPLIER-{random.randint(1, 5)}",
            lead_time_days=random.randint(3, 21),
            location=random.choice(["Warehouse A", "Warehouse B", "Forward Store"]),
        )
        db.add(s)
        count += 1

    db.commit()
    print(f"  → Created {count} spare parts")


def create_alerts(db, aircraft_ids):
    """Create alerts for high-risk aircraft."""
    print("🚨 Creating alerts...")
    count = 0
    for aid in aircraft_ids:
        aircraft = db.query(Aircraft).filter(Aircraft.id == aid).first()
        if not aircraft:
            continue

        if aircraft.failure_risk > 0.7:
            a = Alert(
                aircraft_id=aid,
                severity=AlertSeverity.CRITICAL if aircraft.failure_risk > 0.85 else AlertSeverity.WARNING,
                status=AlertStatus.ACTIVE,
                title=f"Elevated failure risk on {aid}",
                message=f"AI system (synthetic demo) detected {aircraft.failure_risk*100:.0f}% failure risk. Sensor anomalies detected in engine and hydraulic systems.",
                recommended_action="Schedule immediate inspection. Review spare parts availability.",
                failure_risk=aircraft.failure_risk,
                factors=[
                    {"name": "Engine Temp", "contribution": 0.45},
                    {"name": "Vibration", "contribution": 0.35},
                    {"name": "Oil Pressure", "contribution": 0.20}
                ]
            )
            db.add(a)
            count += 1
        elif aircraft.health_score < 70:
            a = Alert(
                aircraft_id=aid,
                severity=AlertSeverity.WARNING,
                status=AlertStatus.ACTIVE,
                title=f"Low health score on {aid}",
                message=f"Aircraft health score is {aircraft.health_score:.0f}%. Monitor closely.",
                recommended_action="Schedule preventive maintenance during next available window.",
                failure_risk=aircraft.failure_risk,
                factors=[
                    {"name": "Flight Hours", "contribution": 0.60},
                    {"name": "General Wear", "contribution": 0.40}
                ]
            )
            db.add(a)
            count += 1

    db.commit()
    print(f"  → Created {count} alerts")


def seed_audit_logs(db):
    """Seed some demo audit log entries with chained cryptographic hashes."""
    from backend.app.services.audit import log_audit
    admin = db.query(User).filter(User.username == "admin").first()
    if not admin:
        return
    events = [
        ("LOGIN_SUCCESS", "admin", "SUCCESS"),
        ("AIRCRAFT_UPDATED", "DEMO-A001", "SUCCESS"),
        ("PREDICTION_GENERATED", "DEMO-A001", "SUCCESS"),
        ("MAINTENANCE_CREATED", "DEMO-A005", "SUCCESS"),
        ("SPARE_STOCK_UPDATED", "HYD-PUMP-001", "SUCCESS"),
        ("LOGIN_FAILURE", "unknown_user", "FAILURE"),
        ("UNAUTHORIZED_ACCESS_ATTEMPT", "/api/audit-logs", "DENIED"),
    ]
    for action, resource, result in events:
        log_audit(db, admin, action, resource, result, "127.0.0.1")



def main():
    print("\n" + "=" * 60)
    print("  AIR POWER PREDICTIVE MAINTENANCE — DATABASE SEEDER")
    print("  SYNTHETIC DATA ONLY — FOR DEMONSTRATION PURPOSES")
    print("=" * 60)

    db = SessionLocal()

    try:
        create_demo_accounts(db)
        aircraft_configs = create_aircraft(db)
        aircraft_ids = [a[0] for a in aircraft_configs]

        # Also include any existing aircraft
        all_aircraft = db.query(Aircraft).all()
        all_ids = [a.id for a in all_aircraft]

        create_sensor_history(db, all_ids)
        create_predictions(db, all_ids)
        create_maintenance_records(db, all_ids)
        create_spare_parts(db)
        create_alerts(db, all_ids)
        seed_audit_logs(db)

        # Phase 1: seed operational planning tables
        seed_operational_data(db)

        print("\n" + "=" * 60)
        print("  ✅ DATABASE SEEDED SUCCESSFULLY")
        print(f"  📊 {len(all_ids)} aircraft | 12 spare parts")
        print("  🔒 Demo accounts created (see credentials above)")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n❌ Seeding failed: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()
