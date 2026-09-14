"""Load and verify puzzle screenshot images.

Supports common image formats (PNG, JPEG, WEBP, BMP).
See §14 of the implementation plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image


SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

# Reasonable limits to reject corrupt or extremely large images
MIN_DIMENSION = 32
MAX_DIMENSION = 8192


@dataclass
class LoadedImage:
    """An image that has been loaded and verified."""

    path: Path
    image: Image.Image
    width: int
    height: int
    format: str | None

    @property
    def dimensions(self) -> tuple[int, int]:
        return (self.width, self.height)


class ImageLoadError(Exception):
    """Raised when an image cannot be loaded or fails validation."""


def load_image(path: Path | str) -> LoadedImage:
    """Load an image from disk and perform basic validation.

    Raises
    ------
    ImageLoadError
        If the file does not exist, is not a supported format, or has
        invalid dimensions.
    """
    path = Path(path)

    if not path.exists():
        raise ImageLoadError(f"File not found: {path}")

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ImageLoadError(
            f"Unsupported image format '{path.suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    try:
        img = Image.open(path)
        img.load()  # Force full decode to catch corrupt files
    except Exception as exc:
        raise ImageLoadError(f"Failed to open image '{path}': {exc}") from exc

    width, height = img.size

    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        raise ImageLoadError(
            f"Image too small: {width}×{height} (minimum {MIN_DIMENSION}×{MIN_DIMENSION})"
        )

    if width > MAX_DIMENSION or height > MAX_DIMENSION:
        raise ImageLoadError(
            f"Image too large: {width}×{height} (maximum {MAX_DIMENSION}×{MAX_DIMENSION})"
        )

    return LoadedImage(
        path=path,
        image=img,
        width=width,
        height=height,
        format=img.format,
    )


def list_images(directory: Path | str) -> list[Path]:
    """List all supported image files in a directory (non-recursive)."""
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"Directory not found: {directory}")

    images = [
        p
        for p in sorted(directory.iterdir())
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return images
