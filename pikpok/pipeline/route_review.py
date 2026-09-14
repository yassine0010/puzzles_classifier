"""Confidence-based review routing.

Routes classification results to review queues based on the configurable
thresholds from §16 of the plan:
- Primary domain confidence < 0.80 → review
- Subdomain confidence < 0.75 → review
- Puzzle family confidence < 0.75 → review
- Skill confidence < 0.70 → omit or review
- Unknown label → review
- Taxonomy contradiction → reject
"""

from __future__ import annotations

import logging
from typing import Literal

from pikpok.config import PipelineConfig
from pikpok.schemas.classification import ClassificationResult
from pikpok.taxonomy.loader import Taxonomy
from pikpok.taxonomy.suggestions import (
    count_discovery_suggestions,
    filter_discovery_suggestions,
)
from pikpok.taxonomy.validator import ValidationResult

logger = logging.getLogger(__name__)

ReviewStatus = Literal["pending", "approved", "rejected", "needs_taxonomy"]


def route_to_review(
    classification: ClassificationResult,
    validation: ValidationResult,
    config: PipelineConfig | None = None,
    taxonomy: Taxonomy | None = None,
) -> tuple[ReviewStatus, str | None]:
    """Determine the review status for a classification result.

    Parameters
    ----------
    classification:
        The validated classification result.
    validation:
        The taxonomy validation result.
    config:
        Pipeline config with thresholds.  Uses defaults if ``None``.
    taxonomy:
        Optional taxonomy used to ignore suggestions that duplicate approved
        labels. The analysis pipeline supplies this value.

    Returns
    -------
    tuple[ReviewStatus, str | None]
        The review status and an optional reason string.
    """
    if config is None:
        config = PipelineConfig()

    reasons: list[str] = []

    # ------------------------------------------------------------------
    # Taxonomy contradiction → reject
    # ------------------------------------------------------------------
    if not validation.is_valid:
        return "rejected", "; ".join(validation.errors)

    # ------------------------------------------------------------------
    # Uncertain required labels → review
    # ------------------------------------------------------------------
    required_labels = (
        ("primary domain", classification.primary_domain),
        ("subdomain", classification.subdomain),
        ("puzzle family", classification.puzzle_family),
    )
    for field_name, label in required_labels:
        if label.status in ("unknown", "ambiguous", "not_applicable"):
            reasons.append(f"{label.status.capitalize()} {field_name}")

    # ------------------------------------------------------------------
    # Out-of-taxonomy → needs_taxonomy
    # ------------------------------------------------------------------
    out_of_taxonomy_fields = []
    for field_name, label in required_labels:
        if label.status == "out_of_taxonomy":
            out_of_taxonomy_fields.append(field_name)

    if out_of_taxonomy_fields:
        return "needs_taxonomy", (
            f"Out-of-taxonomy fields: {', '.join(out_of_taxonomy_fields)}"
        )

    # ------------------------------------------------------------------
    # Genuine discovery suggestions → taxonomy review. Suggestions are not
    # ordinary low-confidence review items: they are proposals to evolve the
    # approved taxonomy and belong in the taxonomy-gap queue.
    # ------------------------------------------------------------------
    ds = classification.discovery_suggestions
    if taxonomy is not None:
        ds = filter_discovery_suggestions(ds, taxonomy)
    total_suggestions = count_discovery_suggestions(ds)
    if total_suggestions > 0:
        return "needs_taxonomy", f"{total_suggestions} new taxonomy candidate(s)"

    # ------------------------------------------------------------------
    # Low confidence → review
    # ------------------------------------------------------------------
    if classification.primary_domain.confidence < config.domain_confidence_threshold:
        reasons.append(
            f"Low domain confidence: {classification.primary_domain.confidence:.2f}"
        )

    if classification.subdomain.confidence < config.subdomain_confidence_threshold:
        reasons.append(
            f"Low subdomain confidence: {classification.subdomain.confidence:.2f}"
        )

    if (
        classification.puzzle_family.confidence
        < config.puzzle_family_confidence_threshold
    ):
        reasons.append(
            "Low puzzle family confidence: "
            f"{classification.puzzle_family.confidence:.2f}"
        )

    # Check skills individually — low-confidence skills are flagged but
    # don't invalidate the overall record
    for skill in classification.skills:
        if skill.confidence < config.skill_confidence_threshold:
            reasons.append(
                f"Low skill confidence for '{skill.id}': {skill.confidence:.2f}"
            )

    # ------------------------------------------------------------------
    # Route decision
    # ------------------------------------------------------------------
    if reasons:
        return "pending", "; ".join(reasons)

    return "approved", None
