from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.db.models import Cluster, Face, Photo


def list_persons(session: Session, query: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
    base = select(Cluster.person_name).where(Cluster.status == "labeled", Cluster.person_name.is_not(None))
    if query:
        base = base.where(Cluster.person_name.ilike(f"%{query}%"))

    names = sorted(set(session.execute(base).scalars().all()))
    total = len(names)
    page_names = names[offset : offset + limit]

    results: list[dict] = []
    for name in page_names:
        clusters = (
            session.execute(select(Cluster).where(Cluster.person_name == name, Cluster.status == "labeled"))
            .scalars()
            .all()
        )
        cluster_ids = [c.id for c in clusters]
        photo_count = session.scalar(
            select(func.count(distinct(Face.photo_id))).where(Face.cluster_id.in_(cluster_ids))
        ) or 0
        rep = next((c.representative_thumbnail_path for c in clusters if c.representative_thumbnail_path), None)
        rep_cluster_id = next((c.id for c in clusters if c.representative_thumbnail_path), clusters[0].id if clusters else None)
        results.append(
            {
                "person_name": name,
                "photo_count": photo_count,
                "representative_cluster_id": rep_cluster_id,
                "has_thumbnail": rep is not None,
            }
        )
    return results, total


def get_person_photos(session: Session, person_name: str, limit: int, offset: int) -> tuple[list[Photo], int]:
    cluster_ids = (
        session.execute(
            select(Cluster.id).where(Cluster.person_name == person_name, Cluster.status == "labeled")
        )
        .scalars()
        .all()
    )
    if not cluster_ids:
        return [], 0

    photo_id_query = (
        select(distinct(Face.photo_id)).where(Face.cluster_id.in_(cluster_ids))
    )
    total = session.scalar(select(func.count()).select_from(photo_id_query.subquery())) or 0

    photos = (
        session.execute(
            select(Photo)
            .where(Photo.id.in_(photo_id_query))
            .where(Photo.status == "processed")
            .order_by(Photo.taken_at.desc().nullslast(), Photo.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return list(photos), total
