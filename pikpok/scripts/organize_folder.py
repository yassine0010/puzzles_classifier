#!/usr/bin/env python3
"""Regenerate classification views from existing records.

Usage:
    python -m pikpok.scripts.organize_folder --output classified_puzzles/

This reads all records from ``records/`` and regenerates the staging and
review directory views.  Useful after corrections or taxonomy updates.
"""

from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

from pikpok.pipeline.analyze_image import generate_classification_views
from pikpok.review.taxonomy_gaps import write_taxonomy_suggestions_report
from pikpok.schemas.analysis import PuzzleAnalysis
from pikpok.taxonomy.loader import load_taxonomy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regenerate classification folder views from records."
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("classified_puzzles"),
        help="Output directory (same as used by analyze_folder).",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove existing staging/ and review/ before regenerating.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output
    records_dir = output_dir / "records"

    if not records_dir.is_dir():
        logger.error("Records directory not found: %s", records_dir)
        return

    # Optionally clean existing views
    if args.clean:
        for view_dir_name in ("staging", "review"):
            view_dir = output_dir / view_dir_name
            if view_dir.exists():
                logger.info("Removing %s", view_dir)
                shutil.rmtree(view_dir)

    # Load all records and regenerate views
    record_files = sorted(records_dir.glob("*.json"))
    logger.info("Regenerating views for %d records", len(record_files))

    for record_path in record_files:
        try:
            analysis = PuzzleAnalysis.model_validate_json(
                record_path.read_text(encoding="utf-8")
            )
            generate_classification_views(analysis, output_dir)
        except Exception as exc:
            logger.error("Failed to process %s: %s", record_path.name, exc)

    # Generate the one canonical taxonomy-candidate report.
    report_path = output_dir / "reports" / "taxonomy_suggestions.json"
    write_taxonomy_suggestions_report(records_dir, report_path, load_taxonomy())

    logger.info("View regeneration complete: %s", output_dir)


if __name__ == "__main__":
    main()
