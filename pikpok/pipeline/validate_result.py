"""Validation orchestration for classification results.

Combines Pydantic schema validation (done at parse time) with taxonomy-level
validation (domain→subdomain relationships, ID existence, etc.).
"""

from __future__ import annotations

import logging

from pikpok.schemas.classification import ClassificationResult
from pikpok.taxonomy.loader import Taxonomy
from pikpok.taxonomy.validator import ValidationResult, validate_classification

logger = logging.getLogger(__name__)


def validate_result(
    classification: ClassificationResult,
    taxonomy: Taxonomy,
    *,
    raise_on_error: bool = False,
) -> ValidationResult:
    """Validate a classification result against the taxonomy.

    Parameters
    ----------
    classification:
        The Pass 2 classification result (already schema-validated by Pydantic).
    taxonomy:
        The loaded taxonomy.
    raise_on_error:
        If ``True``, raise ``ValueError`` when validation fails.

    Returns
    -------
    ValidationResult
        Contains the list of errors (empty if valid).
    """
    result = validate_classification(classification, taxonomy)

    if result.is_valid:
        logger.debug("Taxonomy validation passed")
    else:
        for err in result.errors:
            logger.warning("Taxonomy validation error: %s", err)
        if raise_on_error:
            result.raise_if_invalid()

    return result
