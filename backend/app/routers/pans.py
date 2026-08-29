from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SaltPan, TwinSnapshot
from app.schemas import PanCreate, PanOut, PanUpdate, TwinSnapshotOut, TwinUpdateRequest
from app.services.digital_twin import default_twin_state, progress_to_harvest

router = APIRouter(prefix="/api/pans", tags=["salt pans / digital twins"])


@router.get("", response_model=List[PanOut])
def list_pans(db: Session = Depends(get_db)):
    return db.query(SaltPan).order_by(SaltPan.pan_id).all()


@router.post("", response_model=PanOut, status_code=201)
def create_pan(body: PanCreate, db: Session = Depends(get_db)):
    if db.query(SaltPan).filter(SaltPan.pan_id == body.pan_id).first():
        raise HTTPException(409, f"Salt pan '{body.pan_id}' already exists")
    pan = SaltPan(
        pan_id=body.pan_id,
        name=body.name,
        location=body.location,
        latitude=body.latitude,
        longitude=body.longitude,
        area_m2=body.area_m2,
        twin_state=body.twin_state or default_twin_state(),
    )
    db.add(pan)
    db.commit()
    db.refresh(pan)
    return pan


@router.get("/{pan_id}", response_model=PanOut)
def get_pan(pan_id: int, db: Session = Depends(get_db)):
    pan = db.get(SaltPan, pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")
    return pan


@router.patch("/{pan_id}", response_model=PanOut)
def update_pan(pan_id: int, body: PanUpdate, db: Session = Depends(get_db)):
    pan = db.get(SaltPan, pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")
    for field in ("name", "location", "latitude", "longitude", "area_m2", "twin_state"):
        val = getattr(body, field)
        if val is not None:
            setattr(pan, field, val)
    db.commit()
    db.refresh(pan)
    return pan


@router.get("/{pan_id}/twin")
def get_twin(pan_id: int, db: Session = Depends(get_db)):
    pan = db.get(SaltPan, pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")
    return {
        "pan": PanOut.model_validate(pan),
        "state": pan.twin_state,
        "progress_to_harvest": progress_to_harvest(pan),
    }


@router.post("/{pan_id}/twin", response_model=PanOut)
def update_twin_state(pan_id: int, body: TwinUpdateRequest, db: Session = Depends(get_db)):
    pan = db.get(SaltPan, pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")
    merged = {**default_twin_state(), **(pan.twin_state or {}), **body.state}
    pan.twin_state = merged
    db.add(TwinSnapshot(pan_id=pan.id, snapshot_date=merged.get("last_update", ""),
                        source=body.source, state=merged))
    db.commit()
    db.refresh(pan)
    return pan


@router.get("/{pan_id}/snapshots", response_model=List[TwinSnapshotOut])
def twin_snapshots(pan_id: int, db: Session = Depends(get_db)):
    if not db.get(SaltPan, pan_id):
        raise HTTPException(404, "Salt pan not found")
    return db.query(TwinSnapshot).filter(TwinSnapshot.pan_id == pan_id)\
        .order_by(TwinSnapshot.created_at.desc()).all()