"""Pass 2 output schema — taxonomy classification.

These models capture the classification result with evidence and confidence.
See §10 and §11 of the implementation plan.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


class LabelEvidence(BaseModel):
    """A single taxonomy label with confidence, evidence, and status."""

    id: str = Field(
        ..., description="Approved taxonomy ID, or 'unknown'."
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score between 0 and 1."
    )
    evidence: str = Field(
        ..., description="Observable evidence supporting this label."
    )
    status: Literal[
        "assigned",
        "unknown",
        "ambiguous",
        "out_of_taxonomy",
        "not_applicable",
    ] = Field(
        default="assigned",
        description="Classification status for this label.",
    )


class PuzzleMechanic(BaseModel):
    """An observable puzzle operation or mechanic."""

    name: str = Field(..., description="Short mechanic name.")
    evidence: str = Field(
        ..., description="Observable evidence for this mechanic."
    )


class DiscoverySuggestion(BaseModel):
    """A proposed new label not yet in the taxonomy."""

    name: str = Field(..., description="Suggested label name.")
    reason: str = Field(
        ..., description="Why the current taxonomy is insufficient."
    )
    evidence: str = Field(
        ..., description="Observable evidence for this suggestion."
    )


class DiscoverySuggestions(BaseModel):
    """Container for proposed taxonomy additions across label types.

    These are candidates for human taxonomy review, not classification labels
    and not generator instructions.
    """

    domains: list[DiscoverySuggestion] = Field(default_factory=list)
    subdomains: list[DiscoverySuggestion] = Field(default_factory=list)
    families: list[DiscoverySuggestion] = Field(default_factory=list)
    skills: list[DiscoverySuggestion] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level classification result
# ---------------------------------------------------------------------------


class ClassificationResult(BaseModel):
    """Complete taxonomy classification produced by VLM Pass 2."""

    puzzle_family: LabelEvidence
    primary_domain: LabelEvidence
    subdomain: LabelEvidence
    secondary_domains: list[LabelEvidence] = Field(
        default_factory=list,
        description="Zero to two secondary domains when justified.",
    )
    mechanics: list[PuzzleMechanic] = Field(
        default_factory=list,
        description="Observable puzzle mechanics.",
    )
    skills: list[LabelEvidence] = Field(
        default_factory=list,
        description="Zero to four inferred skills with evidence.",
    )
    discovery_suggestions: DiscoverySuggestions = Field(
        default_factory=DiscoverySuggestions,
        description="Proposed new labels for human review only.",
    )
    uncertainties: list[str] = Field(
        default_factory=list,
        description="Free-text uncertainty notes.",
    )
