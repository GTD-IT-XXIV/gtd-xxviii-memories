from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_session
from app.db.models import Photo

router = APIRouter(prefix="/photos", tags=["photos"])


@router.get("/{photo_id}/thumbnail")
def get_photo_thumbnail(photo_id: int, session: Session = Depends(get_session)):
    photo = session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    path = settings.photo_thumb_dir / f"{photo_id}.jpg"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/{photo_id}/full")
def get_photo_full(photo_id: int, session: Session = Depends(get_session)):
    photo = session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    path = Path(photo.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Original file not found on disk")
    return FileResponse(path, filename=photo.filename)
