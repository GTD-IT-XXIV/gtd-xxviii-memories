from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.db.models import Face

router = APIRouter(prefix="/faces", tags=["faces"])


@router.get("/{face_id}/thumbnail")
def get_face_thumbnail(face_id: int, session: Session = Depends(get_session)):
    face = session.get(Face, face_id)
    if face is None or not face.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(face.thumbnail_path, media_type="image/jpeg")
