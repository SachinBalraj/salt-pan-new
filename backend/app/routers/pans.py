from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DigitalTwinState, OperationEvent, Pan, Recommendation, SensorReading
from app.schemas import (
    DigitalTwinOut,
    OperationEventOut,
    PanCreate,
    PanOut,
    PanUpdate,
    SensorReadingOut,
    SimulateRainOut,
    SimulateRainRequest,
    TwinSnapshotOut,
    TwinUpdateRequest,
)
from app.services.digital_twin import (
    default_twin_state,
    get_twin_state,
    progress_to_harvest,
    record_state,
    twin_summary,
)
from app.services.serializers import (
    operation_event_to_dict,
    pan_to_dict,
    sensor_reading_to_dict,
    twin_snapshot_to_dict,
)
from app.services.simulator import simulate_rain

router = APIRouter(prefix="/api/pans", tags=["salt pans / digital twins"])


@router.get("", response_model=List[PanOut])
def list_pans(db: Session = Depends(get_db)):
    return [pan_to_dict(db, p) for p in db.query(Pan).order_by(Pan.pan_code).all()]


@router.post("", response_model=PanOut, status_code=201)
def create_pan(body: PanCreate, db: Session = Depends(get_db)):
    if db.query(Pan).filter(Pan.pan_code == body.pan_id).first():
        raise HTTPException(409, f"Salt pan '{body.pan_id}' already exists")
    pan = Pan(
        pan_code=body.pan_id,
        name=body.name,
        latitude=body.latitude,
        longitude=body.longitude,
        area_m2=body.area_m2 or 1000.0,
        safe_depth_cm=12.0,
        safe_storage_available=True,
    )
    db.add(pan)
    db.flush()
    state = {**default_twin_state(), **dict(body.twin_state or {})}
    state.setdefault("location", body.location or body.name)
    record_state(db, pan, state, source="initial")
    db.commit()
    db.refresh(pan)
    return pan_to_dict(db, pan)


@router.get("/{pan_id}", response_model=PanOut)
def get_pan(pan_id: int, db: Session = Depends(get_db)):
    pan = db.get(Pan, pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")
    return pan_to_dict(db, pan)


@router.patch("/{pan_id}", response_model=PanOut)
def update_pan(pan_id: int, body: PanUpdate, db: Session = Depends(get_db)):
    pan = db.get(Pan, pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")
    for field in ("name", "latitude", "longitude", "area_m2"):
        val = getattr(body, field)
        if val is not None:
            setattr(pan, field, val)
    if body.twin_state is not None:
        cur = get_twin_state(db, pan)
        merged = {**default_twin_state(), **cur, **body.twin_state}
        record_state(db, pan, merged, source="manual_update")
    db.commit()
    db.refresh(pan)
    return pan_to_dict(db, pan)


@router.get("/{pan_id}/twin")
def get_twin(pan_id: int, db: Session = Depends(get_db)):
    pan = db.get(Pan, pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")
    return {
        "pan": pan_to_dict(db, pan),
        "state": get_twin_state(db, pan),
        "progress_to_harvest": progress_to_harvest(get_twin_state(db, pan)),
    }


@router.get("/{pan_id}/digital-twin", response_model=DigitalTwinOut)
def get_digital_twin(pan_id: int, db: Session = Depends(get_db)):
    pan = db.get(Pan, pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")
    return twin_summary(db, pan)


@router.post("/{pan_id}/twin", response_model=PanOut)
def update_twin_state(pan_id: int, body: TwinUpdateRequest, db: Session = Depends(get_db)):
    pan = db.get(Pan, pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")
    merged = {**default_twin_state(), **get_twin_state(db, pan), **body.state}
    record_state(db, pan, merged, source=body.source)
    db.commit()
    db.refresh(pan)
    return pan_to_dict(db, pan)


@router.post("/{pan_id}/simulate-rain", response_model=SimulateRainOut)
def simulate_rain_impact(pan_id: int, body: SimulateRainRequest,
                         db: Session = Depends(get_db)):
    """What-if: model a single rain event on a pan's current twin state."""
    pan = db.get(Pan, pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")
    return simulate_rain(db, pan, body.rainfall_mm)


def _resolve_pan(db: Session, pan_id: str) -> Pan:
    """Resolve a pan by numeric primary key or by its PAN-XX pan code."""
    if pan_id.isdigit():
        pan = db.get(Pan, int(pan_id))
        if pan:
            return pan
    pan = db.query(Pan).filter(Pan.pan_code == pan_id).first()
    if not pan:
        raise HTTPException(404, "Salt pan not found")
    return pan


@router.post("/{pan_id}/predict")
def predict_advice(pan_id: str, db: Session = Depends(get_db)):
    """Phase-11 advisor: digital-twin + RF + what-if rain + SHAP factors fused
    by the YAML rule engine. Returns the primary recommendation cards plus the
    typed fact record; physical actions remain farmer-approved."""
    from app.services.advisor import run_advice

    pan = _resolve_pan(db, pan_id)
    return run_advice(db, pan)


@router.get("/{pan_id}/snapshots", response_model=List[TwinSnapshotOut])
def twin_snapshots(pan_id: int, db: Session = Depends(get_db)):
    if not db.get(Pan, pan_id):
        raise HTTPException(404, "Salt pan not found")
    rows = (db.query(DigitalTwinState).filter(DigitalTwinState.pan_id == pan_id)
            .order_by(DigitalTwinState.created_at.desc()).limit(200).all())
    return [twin_snapshot_to_dict(r) for r in rows]


@router.get("/{pan_id}/sensors", response_model=List[SensorReadingOut])
def sensor_history(pan_id: int, db: Session = Depends(get_db)):
    """Recent in-situ sensor readings for a pan, newest first (for charts)."""
    if not db.get(Pan, pan_id):
        raise HTTPException(404, "Salt pan not found")
    rows = (db.query(SensorReading).filter(SensorReading.pan_id == pan_id)
            .order_by(SensorReading.timestamp.desc()).limit(200).all())
    return [sensor_reading_to_dict(r) for r in rows]


@router.get("/{pan_id}/operations", response_model=List[OperationEventOut])
def operation_history(pan_id: int, db: Session = Depends(get_db)):
    """Logged field operations for a pan: recordings of pumped / transferred /
    protected / responded actions linked to recommendations."""
    if not db.get(Pan, pan_id):
        raise HTTPException(404, "Salt pan not found")
    rows = (db.query(OperationEvent).filter(OperationEvent.pan_id == pan_id)
            .order_by(OperationEvent.event_timestamp.desc()).limit(150).all())
    pan_refs = {p.id: p.pan_code for p in db.query(Pan).all()}
    rec_ids = {r.id for r in rows if r.recommendation_id}
    rec_titles = {}
    if rec_ids:
        for rec in db.query(Recommendation).filter(
                Recommendation.id.in_(rec_ids)).all():
            rec_titles[rec.id] = rec.recommended_action
    return [operation_event_to_dict(r, pan_refs=pan_refs, rec_titles=rec_titles)
            for r in rows]