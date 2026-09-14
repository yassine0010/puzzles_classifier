"""Validate a ClassificationResult against the loaded taxonomy.

Implements the validation rules from §13 of the plan:
- Schema validation (field presence, value ranges)
- Taxonomy validation (ID existence, domain→subdomain relationships)
- Status consistency (unknown IDs ↔ unknown status)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pikpok.schemas.classification import ClassificationResult, LabelEvidence
from pikpok.taxonomy.loader import Taxonomy


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Collects all validation errors for one classification."""

    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add(self, message: str) -> None:
        self.errors.append(message)

    def raise_if_invalid(self) -> None:
        if not self.is_valid:
            raise ValueError(
                "Invalid classification:\n  • " + "\n  • ".join(self.errors)
            )


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _validate_status_consistency(
    label: LabelEvidence,
    field_name: str,
    result: ValidationResult,
    *,
    optional: bool = False,
) -> None:
    """Check that label IDs and uncertainty states can be represented together."""
    if optional:
        if label.id == "unknown":
            result.add(
                f"{field_name}: optional labels must be omitted when unknown"
            )
        elif label.status != "assigned":
            result.add(
                f"{field_name}: optional label '{label.id}' must have "
                f"status='assigned' (got status='{label.status}')"
            )
        return

    if label.id == "unknown" and label.status == "assigned":
        result.add(
            f"{field_name}: an unknown label cannot have status='assigned'"
        )
    if label.id != "unknown" and label.status not in ("assigned", "ambiguous"):
        result.add(
            f"{field_name}: known label '{label.id}' must have "
            f"status='assigned' or 'ambiguous' "
            f"(got status='{label.status}')"
        )


def validate_classification(
    classification: ClassificationResult,
    taxonomy: Taxonomy,
) -> ValidationResult:
    """Run all validation checks and return a ``ValidationResult``.

    This performs both schema-level and taxonomy-level validation as
    described in §13 of the implementation plan.
    """
    result = ValidationResult()
    domain_id = classification.primary_domain.id
    subdomain_id = classification.subdomain.id
    family_id = classification.puzzle_family.id

    # ------------------------------------------------------------------
    # Status consistency on every labelled field
    # ------------------------------------------------------------------
    all_labels: list[tuple[str, LabelEvidence]] = [
        ("puzzle_family", classification.puzzle_family),
        ("primary_domain", classification.primary_domain),
        ("subdomain", classification.subdomain),
    ]
    for idx, sec in enumerate(classification.secondary_domains):
        _validate_status_consistency(
            sec,
            f"secondary_domains[{idx}]",
            result,
            optional=True,
        )
    for idx, skill in enumerate(classification.skills):
        _validate_status_consistency(
            skill, f"skills[{idx}]", result, optional=True
        )

    for name, label in all_labels:
        _validate_status_consistency(label, name, result)

    # ------------------------------------------------------------------
    # Primary domain exists in taxonomy
    # ------------------------------------------------------------------
    if domain_id != "unknown" and domain_id not in taxonomy.domain_ids:
        result.add(f"Unknown primary domain: '{domain_id}'")

    # ------------------------------------------------------------------
    # Subdomain exists under the correct domain
    # ------------------------------------------------------------------
    if subdomain_id != "unknown":
        if domain_id == "unknown":
            result.add(
                "A known subdomain cannot belong to an unknown domain"
            )
        elif domain_id not in taxonomy.domain_ids:
            result.add(
                "Cannot validate subdomain because the domain is invalid"
            )
        elif not taxonomy.is_valid_subdomain(domain_id, subdomain_id):
            result.add(
                f"Subdomain '{subdomain_id}' is not under domain '{domain_id}'"
            )

    # ------------------------------------------------------------------
    # Puzzle family exists
    # ------------------------------------------------------------------
    if family_id != "unknown" and family_id not in taxonomy.puzzle_family_ids:
        result.add(f"Unknown puzzle family: '{family_id}'")

    # ------------------------------------------------------------------
    # Secondary domains exist and must be top-level domains.  A common VLM
    # failure is to put a valid subdomain (for example, ``sequences``) in
    # this field.  Keep that as a validation error, but explain the correct
    # hierarchy so a retry or human reviewer can fix it quickly.
    # ------------------------------------------------------------------
    for sec in classification.secondary_domains:
        if sec.id != "unknown" and sec.id not in taxonomy.domain_ids:
            parent_domains = taxonomy.domains_for_subdomain(sec.id)
            if parent_domains:
                parents = ", ".join(f"'{domain_id}'" for domain_id in parent_domains)
                result.add(
                    f"Secondary label '{sec.id}' is a subdomain of {parents}, "
                    "not a top-level domain; use the subdomain field instead"
                )
            else:
                result.add(f"Unknown secondary domain: '{sec.id}'")

    secondary_ids = [
        sec.id for sec in classification.secondary_domains if sec.id != "unknown"
    ]
    if domain_id != "unknown" and domain_id in secondary_ids:
        result.add(
            f"Primary domain '{domain_id}' must not be repeated in secondary_domains"
        )
    if len(secondary_ids) != len(set(secondary_ids)):
        result.add("Duplicate secondary domains are not allowed")

    if len(classification.secondary_domains) > 2:
        result.add("At most two secondary domains are allowed")

    # ------------------------------------------------------------------
    # Skills exist, no duplicates, max 4
    # ------------------------------------------------------------------
    skill_ids: list[str] = []
    for skill in classification.skills:
        if skill.id != "unknown" and skill.id not in taxonomy.skill_ids:
            result.add(f"Unknown skill: '{skill.id}'")
        skill_ids.append(skill.id)

    if len(skill_ids) > 4:
        result.add("At most four skills are allowed")
    if len(skill_ids) != len(set(skill_ids)):
        result.add("Duplicate skills are not allowed")

    return result
