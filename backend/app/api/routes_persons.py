from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.services import person_service

router = APIRouter(prefix="/persons", tags=["persons"])


@router.get("")
def list_persons(query: str | None = None, limit: int = 50, offset: int = 0, session: Session = Depends(get_session)):
    results, total = person_service.list_persons(session, query, limit, offset)
    items = [
        {
            "person_name": r["person_name"],
            "photo_count": r["photo_count"],
            "representative_thumbnail_url": (
                f"/clusters/{r['representative_cluster_id']}/thumbnail" if r["has_thumbnail"] else None
            ),
        }
        for r in results
    ]
    return {"items": items, "total": total}


@router.get("/{person_name:path}/photos")
def get_person_photos(person_name: str, limit: int = 60, offset: int = 0, session: Session = Depends(get_session)):
    photos, total = person_service.get_person_photos(session, person_name, limit, offset)
    return {
        "items": [
            {
                "id": p.id,
                "filename": p.filename,
                "width": p.width,
                "height": p.height,
                "taken_at": p.taken_at,
            }
            for p in photos
        ],
        "total": total,
    }
