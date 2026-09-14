"""Build one deduplicated report of genuine taxonomy candidates.

Records retain genuine discovery suggestions for provenance. This module
creates the only standalone suggestion artifact:
``reports/taxonomy_suggestions.json``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from pikpok.schemas.analysis import PuzzleAnalysis
from pikpok.schemas.classification import DiscoverySuggestion
from pikpok.taxonomy.loader import Taxonomy, load_taxonomy
from pikpok.taxonomy.suggestions import (
    filter_discovery_suggestions,
    normalize_suggestion_name,
)

logger = logging.getLogger(__name__)

REPORT_VERSION = "1.0"
SUGGESTION_CATEGORIES = ("domains", "subdomains", "families", "skills")
CATEGORY_NAMES = {
    "domains": "domain",
    "subdomains": "subdomain",
    "families": "family",
    "skills": "skill",
}


@dataclass
class SuggestionCluster:
    """A group of equivalent, genuinely new suggestions."""

    category: str
    suggested_id: str
    suggested_name: str
    parent_domain: str | None = None
    occurrences: list[dict] = field(default_factory=list)

    @property
    def count(self) -> int:
        """Return the number of distinct puzzles supporting this candidate."""
        return len({item["puzzle_id"] for item in self.occurrences})


def _suggestions_by_category(
    analysis: PuzzleAnalysis, taxonomy: Taxonomy
) -> dict[str, list[DiscoverySuggestion]]:
    cleaned = filter_discovery_suggestions(
        analysis.classification.discovery_suggestions,
        taxonomy,
    )
    return {
        category: getattr(cleaned, category)
        for category in SUGGESTION_CATEGORIES
    }


def collect_taxonomy_suggestions(
    records_dir: Path,
    taxonomy: Taxonomy | None = None,
) -> list[SuggestionCluster]:
    """Scan records and return deduplicated, novel taxonomy candidates."""
    if taxonomy is None:
        taxonomy = load_taxonomy()

    clusters: dict[tuple[str, str, str | None], SuggestionCluster] = {}

    if not records_dir.is_dir():
        logger.warning("Records directory not found: %s", records_dir)
        return []

    for record_path in sorted(records_dir.glob("*.json")):
        try:
            analysis = PuzzleAnalysis.model_validate_json(
                record_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            logger.error("Failed to load %s: %s", record_path.name, exc)
            continue

        primary_domain = analysis.classification.primary_domain.id
        parent_domain = (
            primary_domain
            if primary_domain in taxonomy.domain_ids
            else None
        )

        for category, suggestions in _suggestions_by_category(
            analysis, taxonomy
        ).items():
            for suggestion in suggestions:
                suggested_id = normalize_suggestion_name(suggestion.name)
                category_parent = parent_domain if category == "subdomains" else None
                key = (category, suggested_id, category_parent)
                cluster = clusters.get(key)
                if cluster is None:
                    cluster = SuggestionCluster(
                        category=CATEGORY_NAMES[category],
                        suggested_id=suggested_id,
                        suggested_name=suggestion.name,
                        parent_domain=category_parent,
                    )
                    clusters[key] = cluster

                cluster.occurrences.append(
                    {
                        "puzzle_id": analysis.source_image_id,
                        "name": suggestion.name,
                        "reason": suggestion.reason,
                        "evidence": suggestion.evidence,
                    }
                )

    return sorted(
        clusters.values(),
        key=lambda cluster: (-cluster.count, cluster.category, cluster.suggested_id),
    )


def _cluster_to_json(cluster: SuggestionCluster) -> dict:
    puzzle_ids = sorted({item["puzzle_id"] for item in cluster.occurrences})
    return {
        "category": cluster.category,
        "suggested_id": cluster.suggested_id,
        "suggested_name": cluster.suggested_name,
        "parent_domain": cluster.parent_domain,
        "occurrence_count": cluster.count,
        "puzzle_ids": puzzle_ids,
        "examples": cluster.occurrences,
        "status": "candidate",
    }


def write_taxonomy_suggestions_report(
    records_dir: Path,
    report_path: Path,
    taxonomy: Taxonomy | None = None,
) -> None:
    """Write the canonical aggregated taxonomy suggestion report.

    Legacy standalone suggestion files are removed because they duplicate
    this report. Genuine suggestions remain available in each record.
    """
    if taxonomy is None:
        taxonomy = load_taxonomy()

    clusters = collect_taxonomy_suggestions(records_dir, taxonomy)
    suggestions = [_cluster_to_json(cluster) for cluster in clusters]
    summary = {
        category: sum(
            1 for suggestion in suggestions if suggestion["category"] == category
        )
        for category in ("domain", "subdomain", "family", "skill")
    }

    report = {
        "report_version": REPORT_VERSION,
        "taxonomy_version": taxonomy.version,
        "source": "records/",
        "summary": {
            "total_candidates": len(suggestions),
            **summary,
        },
        "suggestions": suggestions,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # These are generated artifacts from the old architecture. Remove only
    # the exact legacy filenames, never arbitrary files in the reports folder.
    for legacy_name in ("discovery_suggestions.json", "discovery_suggestions.jsonl"):
        legacy_path = report_path.parent / legacy_name
        if legacy_path != report_path and legacy_path.exists():
            legacy_path.unlink()

    logger.info("Taxonomy suggestions report written: %s", report_path)


# Backwards-compatible names for callers that used the old module API.
collect_discovery_suggestions = collect_taxonomy_suggestions
write_discovery_report = write_taxonomy_suggestions_report
