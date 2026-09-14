"""Helpers for separating taxonomy discovery from classification.

Discovery suggestions are free-text proposals produced by the model.  This
module filters out suggestions that already exist in the approved taxonomy so
they do not become false taxonomy gaps or noisy review items.
"""

from __future__ import annotations

import re

from pikpok.schemas.classification import DiscoverySuggestion, DiscoverySuggestions
from pikpok.taxonomy.loader import Taxonomy


def normalize_suggestion_name(name: str) -> str:
    """Normalize a free-text suggestion for comparison and grouping."""
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")


def _known_names(taxonomy: Taxonomy, category: str) -> set[str]:
    if category == "domains":
        labels = {
            domain_id: domain.name
            for domain_id, domain in taxonomy.domains.items()
        }
    elif category == "subdomains":
        labels = taxonomy.all_subdomains()
    elif category == "families":
        labels = taxonomy.puzzle_families
    elif category == "skills":
        labels = taxonomy.skills
    else:
        raise ValueError(f"Unknown suggestion category: {category}")

    return {
        normalize_suggestion_name(label)
        for label in [*labels.keys(), *labels.values()]
    }


def is_known_suggestion(
    suggestion: DiscoverySuggestion,
    category: str,
    taxonomy: Taxonomy,
) -> bool:
    """Return whether a suggestion already exists in the taxonomy."""
    return normalize_suggestion_name(suggestion.name) in _known_names(
        taxonomy, category
    )


def filter_discovery_suggestions(
    suggestions: DiscoverySuggestions,
    taxonomy: Taxonomy,
) -> DiscoverySuggestions:
    """Remove suggestions that duplicate approved taxonomy labels."""
    fields: dict[str, list[DiscoverySuggestion]] = {}
    for category in ("domains", "subdomains", "families", "skills"):
        values = getattr(suggestions, category)
        fields[category] = [
            suggestion
            for suggestion in values
            if not is_known_suggestion(suggestion, category, taxonomy)
        ]
    return DiscoverySuggestions(**fields)


def count_discovery_suggestions(suggestions: DiscoverySuggestions) -> int:
    """Count all suggestions in a cleaned suggestion container."""
    return sum(
        len(getattr(suggestions, category))
        for category in ("domains", "subdomains", "families", "skills")
    )
