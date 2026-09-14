"""Full puzzle analysis record — the immutable canonical output per puzzle.

This is the single source of truth stored in ``records/<puzzle_id>.json``.
See §11 and §20 of the implementation plan.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pikpok.schemas.understanding import UnderstandingResult
from pikpok.schemas.classification import ClassificationResult


class PuzzleAnalysis(BaseModel):
    """Complete immutable analysis record for one puzzle screenshot."""

    # --- Image provenance ---
    source_image_id: str = Field(
        ..., description="Identifier for the source image (typically the filename stem)."
    )
    original_image_hash: str = Field(
        ..., description="SHA-256 hash of the original image bytes."
    )
    processed_image_hash: str | None = Field(
        default=None,
        description="SHA-256 hash of the preprocessed image, if different.",
    )
    original_dimensions: tuple[int, int] | None = Field(
        default=None, description="(width, height) of the original image."
    )
    processed_dimensions: tuple[int, int] | None = Field(
        default=None, description="(width, height) of the processed image."
    )

    # --- Version pinning ---
    taxonomy_version: str
    extraction_version: str
    schema_version: str
    model_id: str
    model_revision: str | None = None
    context_size: int | None = None
    max_output_tokens: int | None = None
    max_image_dimension: int | None = None
    prompt_version: str
    preprocessing_version: str

    # --- Analysis results ---
    understanding: UnderstandingResult
    classification: ClassificationResult

    # --- Review ---
    review_status: Literal[
        "pending", "approved", "rejected", "needs_taxonomy"
    ] = Field(
        default="pending",
        description="Current review state of this analysis.",
    )
    review_reason: str | None = Field(
        default=None,
        description="Explanation when review_status is not 'pending'.",
    )
