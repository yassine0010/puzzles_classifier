"""Review queue management.

Loads all records, filters by review status, and provides a simple interface
for inspecting items that need human attention.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pikpok.schemas.analysis import PuzzleAnalysis

logger = logging.getLogger(__name__)


@dataclass
class ReviewQueue:
    """In-memory review queue loaded from the records directory."""

    pending: list[PuzzleAnalysis] = field(default_factory=list)
    needs_taxonomy: list[PuzzleAnalysis] = field(default_factory=list)
    rejected: list[PuzzleAnalysis] = field(default_factory=list)
    approved: list[PuzzleAnalysis] = field(default_factory=list)

    @property
    def total_for_review(self) -> int:
        return len(self.pending) + len(self.needs_taxonomy)

    def summary(self) -> dict[str, int]:
        return {
            "pending": len(self.pending),
            "needs_taxonomy": len(self.needs_taxonomy),
            "rejected": len(self.rejected),
            "approved": len(self.approved),
            "total_for_review": self.total_for_review,
        }


def load_review_queue(records_dir: Path) -> ReviewQueue:
    """Load all records and sort into review buckets.

    Parameters
    ----------
    records_dir:
        Path to the ``records/`` directory containing JSON files.

    Returns
    -------
    ReviewQueue
        Populated queue with all analyses sorted by review status.
    """
    queue = ReviewQueue()

    if not records_dir.is_dir():
        logger.warning("Records directory not found: %s", records_dir)
        return queue

    for record_path in sorted(records_dir.glob("*.json")):
        try:
            analysis = PuzzleAnalysis.model_validate_json(
                record_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            logger.error("Failed to load record %s: %s", record_path.name, exc)
            continue

        status = analysis.review_status
        if status == "pending":
            queue.pending.append(analysis)
        elif status == "needs_taxonomy":
            queue.needs_taxonomy.append(analysis)
        elif status == "rejected":
            queue.rejected.append(analysis)
        elif status == "approved":
            queue.approved.append(analysis)

    logger.info(
        "Review queue loaded: %s",
        json.dumps(queue.summary(), indent=2),
    )
    return queue
