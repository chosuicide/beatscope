"""Single-range media responses shared by the HTTP stream and in-process API."""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path


def describe_media(path: Path, range_header: str | None):
    size = path.stat().st_size
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {"Content-Type": mime, "Accept-Ranges": "bytes", "Content-Length": str(size)}
    if not range_header or not range_header.startswith("bytes="):
        return 200, headers, 0, size
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
    if not match or not any(match.groups()) or size == 0:
        return 416, {**headers, "Content-Range": f"bytes */{size}", "Content-Length": "0"}, 0, 0
    left, right = match.groups()
    if left:
        start = int(left)
        end = min(size - 1, int(right)) if right else size - 1
    else:
        start, end = max(0, size - int(right)), size - 1
    if start > end or start >= size:
        return 416, {**headers, "Content-Range": f"bytes */{size}", "Content-Length": "0"}, 0, 0
    length = end - start + 1
    return 206, {**headers, "Content-Length": str(length), "Content-Range": f"bytes {start}-{end}/{size}"}, start, length
