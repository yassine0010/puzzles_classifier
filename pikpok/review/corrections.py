"""Append-only corrections storage.

Corrections are stored in a JSONL file (``reports/corrections.jsonl``).
The original model output is never overwritten — corrections reference
the original record and describe what changed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Correction:
    """A single correction to a puzzle analysis."""

    puzzle_id: str
    field_path: str  # e.g. "classification.primary_domain.id"
    old_value: str
    new_value: str
    reason: str
    reviewer: str = "human"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def append_correction(
    correction: Correction, corrections_path: Path
) -> None:
    """Append a correction entry to the JSONL file."""
    corrections_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "puzzle_id": correction.puzzle_id,
        "field_path": correction.field_path,
        "old_value": correction.old_value,
        "new_value": correction.new_value,
        "reason": correction.reason,
        "reviewer": correction.reviewer,
        "timestamp": correction.timestamp,
    }

    with open(corrections_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger.info(
        "Correction recorded: %s.%s: %s → %s",
        correction.puzzle_id,
        correction.field_path,
        correction.old_value,
        correction.new_value,
    )


def load_corrections(corrections_path: Path) -> list[Correction]:
    """Load all corrections from the JSONL file."""
    corrections: list[Correction] = []

    if not corrections_path.exists():
        return corrections

    with open(corrections_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                corrections.append(Correction(**data))
            except Exception as exc:
                logger.error(
                    "Failed to parse correction at line %d: %s", line_num, exc
                )

    return corrections
