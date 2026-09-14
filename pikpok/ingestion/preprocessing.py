"""Minimal image preprocessing pipeline.

Per §14 of the plan:
- Load image
- Verify file, dimensions, and format
- Hash and preserve the original bytes
- Convert to RGB and create a recorded, proportionally downscaled variant
- Preserve the complete puzzle by default (no aggressive cropping)

The preprocessing version is recorded on every analysis for reproducibility.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from pikpok.ingestion.hashing import sha256_bytes, sha256_file
from pikpok.ingestion.image_loader import LoadedImage, load_image


@dataclass
class PreprocessingResult:
    """The result of preprocessing one image."""

    original_path: Path
    original_hash: str
    original_dimensions: tuple[int, int]
    processed_image: Image.Image
    processed_hash: str
    processed_dimensions: tuple[int, int]
    preprocessing_version: str

    # OCR placeholder for future use
    ocr: str | None = None


def preprocess_image(
    path: Path | str,
    *,
    preprocessing_version: str = "0.2.0",
    max_image_dimension: int = 1280,
) -> PreprocessingResult:
    """Run the minimal preprocessing pipeline on a single image.

    Steps:
    1. Load and verify the image.
    2. Hash the original file bytes.
    3. Convert to RGB (handles RGBA, palette, grayscale).
    4. Proportionally downscale large images for faster VLM inference.
    5. Hash the processed image bytes.
    6. Return both hashes and the processed image.
    """
    path = Path(path)
    if max_image_dimension < 1:
        raise ValueError("max_image_dimension must be at least 1 pixel")

    # Step 1: Load and verify
    loaded: LoadedImage = load_image(path)

    # Step 2: Hash original bytes
    original_hash = sha256_file(path)

    # Step 3: Convert to RGB
    processed = loaded.image.convert("RGB")

    # Step 4: Preserve the complete puzzle while reducing vision tokens.
    # ``thumbnail`` modifies in place, keeps the aspect ratio, and never
    # enlarges an already small image.
    processed.thumbnail(
        (max_image_dimension, max_image_dimension),
        Image.Resampling.LANCZOS,
    )

    # Step 5: Hash the processed image (as PNG bytes for determinism)
    buf = io.BytesIO()
    processed.save(buf, format="PNG")
    processed_bytes = buf.getvalue()
    processed_hash = sha256_bytes(processed_bytes)

    return PreprocessingResult(
        original_path=path,
        original_hash=original_hash,
        original_dimensions=loaded.dimensions,
        processed_image=processed,
        processed_hash=processed_hash,
        processed_dimensions=processed.size,
        preprocessing_version=preprocessing_version,
    )


def image_to_base64(image: Image.Image, fmt: str = "PNG") -> str:
    """Encode a PIL Image as a base64 string for the Ollama API."""
    import base64

    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("utf-8")
