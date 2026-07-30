from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.schemas import DownloadZipRequest
from app.db.database import get_session
from app.services.zip_service import InvalidPhotoSelection, build_zip_stream

router = APIRouter(prefix="/download", tags=["download"])


@router.post("/zip")
def download_zip(req: DownloadZipRequest, session: Session = Depends(get_session)):
    try:
        stream = build_zip_stream(session, req.photo_ids)
    except InvalidPhotoSelection as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return StreamingResponse(
        stream,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="photos.zip"'},
    )
