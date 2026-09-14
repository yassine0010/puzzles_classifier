#!/usr/bin/env python3
"""Compute operational evaluation metrics from pipeline outputs.

Usage:
    python -m pikpok.scripts.evaluate_model --output classified_puzzles/

Implements the operational metrics from §18 of the plan:
- Schema-valid output rate
- Unknown rate
- Low-confidence rate
- Taxonomy contradiction rate
- Discovery suggestion count
- Processing time per image
- Review queue breakdown
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from pikpok.review.queue import load_review_queue
from pikpok.schemas.analysis import PuzzleAnalysis
from pikpok.taxonomy.loader import load_taxonomy
from pikpok.taxonomy.suggestions import (
    count_discovery_suggestions,
    filter_discovery_suggestions,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute operational metrics for the PikPok pipeline."
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("classified_puzzles"),
        help="Output directory containing records and reports.",
    )
    return parser.parse_args()


def compute_metrics(output_dir: Path) -> dict:
    """Compute all operational metrics from the pipeline output."""
    records_dir = output_dir / "records"
    errors_path = output_dir / "reports" / "errors.jsonl"

    # Load all records
    records: list[PuzzleAnalysis] = []
    if records_dir.is_dir():
        for rp in sorted(records_dir.glob("*.json")):
            try:
                records.append(
                    PuzzleAnalysis.model_validate_json(
                        rp.read_text(encoding="utf-8")
                    )
                )
            except Exception:
                pass

    total_records = len(records)

    # Count error events, but derive attempted puzzles from unique IDs. A
    # puzzle can fail several times and later succeed; those repeated events
    # must not inflate the image-level success denominator.
    error_count = 0
    error_puzzle_ids: set[str] = set()
    if errors_path.exists():
        with open(errors_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                if not line.strip():
                    continue
                error_count += 1
                try:
                    error_entry = json.loads(line)
                    puzzle_id = error_entry.get("puzzle_id")
                except json.JSONDecodeError:
                    puzzle_id = None
                error_puzzle_ids.add(
                    puzzle_id if isinstance(puzzle_id, str) and puzzle_id
                    else f"<missing-id:{line_num}>"
                )

    record_ids = {record.source_image_id for record in records}
    total_attempted = len(record_ids | error_puzzle_ids)

    if total_attempted == 0:
        return {"error": "No records or errors found", "total_records": 0}

    # Schema-valid output rate
    schema_valid_rate = total_records / total_attempted if total_attempted > 0 else 0

    # Unknown rate
    unknown_domain = sum(
        1 for r in records
        if r.classification.primary_domain.status == "unknown"
    )
    unknown_subdomain = sum(
        1 for r in records
        if r.classification.subdomain.status == "unknown"
    )
    unknown_family = sum(
        1 for r in records
        if r.classification.puzzle_family.status == "unknown"
    )

    # Low-confidence rate
    low_conf_domain = sum(
        1 for r in records
        if r.classification.primary_domain.confidence < 0.80
    )
    low_conf_subdomain = sum(
        1 for r in records
        if r.classification.subdomain.confidence < 0.75
    )

    # Genuine discovery suggestions only. Existing labels repeated by the
    # model are filtered out and are not taxonomy-gap metrics.
    taxonomy = load_taxonomy()
    total_discoveries = sum(
        count_discovery_suggestions(
            filter_discovery_suggestions(
                r.classification.discovery_suggestions,
                taxonomy,
            )
        )
        for r in records
    )

    # Review queue
    queue = load_review_queue(records_dir)

    # Domain distribution
    domain_dist: dict[str, int] = {}
    for r in records:
        d = r.classification.primary_domain.id
        domain_dist[d] = domain_dist.get(d, 0) + 1

    # Puzzle family distribution
    family_dist: dict[str, int] = {}
    for r in records:
        f = r.classification.puzzle_family.id
        family_dist[f] = family_dist.get(f, 0) + 1

    metrics = {
        "total_attempted": total_attempted,
        "total_records": total_records,
        "total_errors": error_count,
        "unique_error_puzzle_count": len(error_puzzle_ids),
        "failed_puzzle_count": len(error_puzzle_ids - record_ids),
        "schema_valid_rate": round(schema_valid_rate, 4),
        "unknown_count": {
            "domain": unknown_domain,
            "subdomain": unknown_subdomain,
            "puzzle_family": unknown_family,
        },
        "unknown_rate": {
            "domain": round(unknown_domain / total_records, 4)
            if total_records
            else 0.0,
            "subdomain": round(unknown_subdomain / total_records, 4)
            if total_records
            else 0.0,
            "puzzle_family": round(unknown_family / total_records, 4)
            if total_records
            else 0.0,
        },
        "low_confidence_count": {
            "domain_below_0.80": low_conf_domain,
            "subdomain_below_0.75": low_conf_subdomain,
        },
        "low_confidence_rate": {
            "domain_below_0.80": round(low_conf_domain / total_records, 4)
            if total_records
            else 0.0,
            "subdomain_below_0.75": round(low_conf_subdomain / total_records, 4)
            if total_records
            else 0.0,
        },
        "discovery_suggestion_count": total_discoveries,
        "review_queue": queue.summary(),
        "domain_distribution": dict(
            sorted(domain_dist.items(), key=lambda x: x[1], reverse=True)
        ),
        "family_distribution": dict(
            sorted(family_dist.items(), key=lambda x: x[1], reverse=True)
        ),
    }

    return metrics


def main() -> None:
    args = parse_args()
    metrics = compute_metrics(args.output)

    print(json.dumps(metrics, indent=2, ensure_ascii=False))

    # Also write to file
    metrics_path = args.output / "reports" / "metrics.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Metrics written to %s", metrics_path)


if __name__ == "__main__":
    main()
