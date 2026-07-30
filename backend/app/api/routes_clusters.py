from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.schemas import ClusterMergeRequest, ClusterNameRequest
from app.db.database import get_session
from app.db.models import Face
from app.services import cluster_service

router = APIRouter(prefix="/clusters", tags=["clusters"])


def _cluster_summary(c) -> dict:
    return {
        "id": c.id,
        "face_count": c.face_count,
        "status": c.status,
        "person_name": c.person_name,
        "representative_thumbnail_url": f"/clusters/{c.id}/thumbnail" if c.representative_thumbnail_path else None,
        "created_at": c.created_at,
    }


@router.get("")
def list_clusters(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    rows, total = cluster_service.list_clusters(session, status, limit, offset)
    return {"items": [_cluster_summary(c) for c in rows], "total": total}


@router.get("/{cluster_id}/thumbnail")
def get_cluster_thumbnail(cluster_id: int, session: Session = Depends(get_session)):
    cluster = cluster_service.get_cluster(session, cluster_id)
    if cluster is None or not cluster.representative_thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(cluster.representative_thumbnail_path, media_type="image/jpeg")


@router.get("/{cluster_id}")
def get_cluster(cluster_id: int, session: Session = Depends(get_session)):
    cluster = cluster_service.get_cluster(session, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    faces = session.query(Face).filter(Face.cluster_id == cluster_id).all()
    return {
        **_cluster_summary(cluster),
        "faces": [
            {"id": f.id, "photo_id": f.photo_id, "det_score": f.det_score}
            for f in faces
        ],
    }


@router.post("/{cluster_id}/name")
def name_cluster(cluster_id: int, req: ClusterNameRequest, session: Session = Depends(get_session)):
    try:
        cluster = cluster_service.name_cluster(session, cluster_id, req.name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _cluster_summary(cluster)


@router.post("/{cluster_id}/discard")
def discard_cluster(cluster_id: int, session: Session = Depends(get_session)):
    try:
        cluster = cluster_service.discard_cluster(session, cluster_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _cluster_summary(cluster)


@router.post("/merge")
def merge_clusters(req: ClusterMergeRequest, session: Session = Depends(get_session)):
    try:
        target = cluster_service.merge_clusters(session, req.source_cluster_id, req.target_cluster_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _cluster_summary(target)


@router.post("/{cluster_id}/faces/{face_id}/remove")
def remove_face(cluster_id: int, face_id: int, session: Session = Depends(get_session)):
    try:
        new_cluster = cluster_service.remove_face_from_cluster(session, cluster_id, face_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _cluster_summary(new_cluster)
