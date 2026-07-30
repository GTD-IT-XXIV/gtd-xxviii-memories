from fastapi import APIRouter, HTTPException

from app.api.schemas import ScanStartRequest, ScanStatusResponse
from app.scanning.job_manager import job_manager

router = APIRouter(prefix="/scan", tags=["scan"])


@router.post("/start", response_model=ScanStatusResponse)
def start_scan(req: ScanStartRequest):
    try:
        status = job_manager.start(req.scan_root)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ScanStatusResponse(**status.__dict__)


@router.post("/stop")
def stop_scan():
    job_manager.stop()
    return {"status": "stop_requested"}


@router.get("/status", response_model=ScanStatusResponse)
def get_scan_status():
    status = job_manager.get_status()
    return ScanStatusResponse(**status.__dict__)
