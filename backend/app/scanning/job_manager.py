import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from app.db.database import SessionLocal
from app.scanning.pipeline import ScanCounters, run_scan


@dataclass
class ScanStatus:
    id: int | None = None
    scan_root: str | None = None
    status: str = "idle"  # idle|running|completed|failed|cancelled
    total_files_seen: int = 0
    files_processed: int = 0
    files_skipped_unchanged: int = 0
    files_skipped_placeholder: int = 0
    files_errored: int = 0
    faces_detected: int = 0
    current_file: str | None = None
    error_message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class ScanJobManager:
    """Runs the scan pipeline in a single background thread, one scan at a time,
    exposing a pollable in-memory status snapshot. A solo-user local tool doesn't
    need a real task queue - a lock-guarded thread is sufficient."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_requested = False
        self._status = ScanStatus()
        self._status_lock = threading.Lock()
        self._next_id = 1

    def get_status(self) -> ScanStatus:
        with self._status_lock:
            return ScanStatus(**asdict(self._status))

    def is_running(self) -> bool:
        with self._status_lock:
            return self._status.status == "running"

    def start(self, scan_root: str) -> ScanStatus:
        with self._lock:
            if self.is_running():
                raise RuntimeError("A scan is already running")

            self._stop_requested = False
            with self._status_lock:
                self._status = ScanStatus(
                    id=self._next_id,
                    scan_root=scan_root,
                    status="running",
                    started_at=datetime.now(timezone.utc).isoformat(),
                )
                self._next_id += 1
                status_snapshot = ScanStatus(**asdict(self._status))

            self._thread = threading.Thread(target=self._run, args=(scan_root,), daemon=True)
            self._thread.start()
            return status_snapshot

    def stop(self) -> None:
        self._stop_requested = True

    def _on_progress(self, counters: ScanCounters) -> None:
        with self._status_lock:
            self._status.total_files_seen = counters.total_files_seen
            self._status.files_processed = counters.files_processed
            self._status.files_skipped_unchanged = counters.files_skipped_unchanged
            self._status.files_skipped_placeholder = counters.files_skipped_placeholder
            self._status.files_errored = counters.files_errored
            self._status.faces_detected = counters.faces_detected
            self._status.current_file = counters.current_file

    def _run(self, scan_root: str) -> None:
        try:
            run_scan(
                SessionLocal,
                scan_root,
                on_progress=self._on_progress,
                should_stop=lambda: self._stop_requested,
            )
            with self._status_lock:
                self._status.status = "cancelled" if self._stop_requested else "completed"
                self._status.finished_at = datetime.now(timezone.utc).isoformat()
        except Exception as exc:  # noqa: BLE001
            with self._status_lock:
                self._status.status = "failed"
                self._status.error_message = str(exc)[:1000]
                self._status.finished_at = datetime.now(timezone.utc).isoformat()


job_manager = ScanJobManager()
