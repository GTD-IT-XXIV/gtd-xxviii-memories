from pydantic import BaseModel


class ScanStartRequest(BaseModel):
    scan_root: str


class ScanStatusResponse(BaseModel):
    id: int | None
    scan_root: str | None
    status: str
    total_files_seen: int
    files_processed: int
    files_skipped_unchanged: int
    files_skipped_placeholder: int
    files_errored: int
    faces_detected: int
    current_file: str | None
    error_message: str | None
    started_at: str | None
    finished_at: str | None


class ClusterNameRequest(BaseModel):
    name: str


class ClusterMergeRequest(BaseModel):
    source_cluster_id: int
    target_cluster_id: int


class DownloadZipRequest(BaseModel):
    photo_ids: list[int]
