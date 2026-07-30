import os
from dataclasses import dataclass
from pathlib import Path

from app.config import settings


@dataclass
class FoundFile:
    path: str
    size_bytes: int
    mtime: float


def walk_images(root: str) -> list[FoundFile]:
    """Recursively walk `root` and return all image files matching configured extensions.

    Uses os.scandir (not os.walk's higher-level wrapper) for lower per-entry overhead,
    important at 10k+ file scale.
    """
    exts = settings.image_extensions
    results: list[FoundFile] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            ext = Path(entry.name).suffix.lower()
                            if ext in exts:
                                st = entry.stat(follow_symlinks=False)
                                results.append(
                                    FoundFile(path=entry.path, size_bytes=st.st_size, mtime=st.st_mtime)
                                )
                    except OSError:
                        continue
        except OSError:
            continue
    return results


def count_images(root: str) -> int:
    return len(walk_images(root))
