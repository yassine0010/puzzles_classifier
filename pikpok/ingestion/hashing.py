"""SHA-256 hashing for image provenance and idempotency.

The image hash together with the run configuration versions forms the
idempotency key so that re-running the pipeline skips already-processed images.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path | str) -> str:
    """Return the hex-encoded SHA-256 hash of a file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Return the hex-encoded SHA-256 hash of raw bytes."""
    return hashlib.sha256(data).hexdigest()
