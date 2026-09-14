"""Pass 1 output schema — puzzle understanding.

This model captures what is *visible* in the screenshot without assigning
taxonomy labels.  See §9 of the implementation plan.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class UnderstandingResult(BaseModel):
    """Structured interpretation produced by VLM Pass 1."""

    puzzle_summary: str = Field(
        ...,
        description="A concise description of the puzzle visible in the screenshot.",
    )
    visible_text: str | None = Field(
        default=None,
        description="All text, numbers, and symbols visible in the image.",
    )
    mechanism: str = Field(
        ...,
        description="The inferred task or rule the player must apply.",
    )
    visual_structure: str | None = Field(
        default=None,
        description="Layout description (e.g. 'grid', 'horizontal_numeric_sequence').",
    )
    input_type: str | None = Field(
        default=None,
        description="Expected input type (e.g. 'numbers', 'words', 'shapes').",
    )
    output_type: str | None = Field(
        default=None,
        description="Expected output type (e.g. 'single_number', 'arrangement').",
    )
    possible_ambiguities: list[str] = Field(
        default_factory=list,
        description="Anything unclear or potentially misread in the image.",
    )
