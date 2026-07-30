import os

FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000


def is_cloud_placeholder(path: str) -> bool:
    """Detect OneDrive "Files On-Demand" placeholders that aren't actually downloaded
    locally yet. Opening these would trigger a slow on-demand download, so scanning
    should skip them instead and pick them up on a later re-scan once hydrated.

    Windows-only check via file attributes; on non-Windows platforms this always
    returns False (no-op).
    """
    if os.name != "nt":
        return False
    try:
        attrs = os.stat(path).st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return False
    cloud_flags = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | FILE_ATTRIBUTE_RECALL_ON_OPEN
    return bool(attrs & cloud_flags)
