"""Central configuration for the PikPok classification pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Version strings pinned per run
# ---------------------------------------------------------------------------

TAXONOMY_VERSION = "0.1.0"
EXTRACTION_VERSION = "0.1.0"
SCHEMA_VERSION = "0.3.0"
# Bumped whenever label-placement instructions change so existing records are
# eligible for reprocessing instead of being silently treated as up to date.
PROMPT_VERSION = "0.5.0"
PREPROCESSING_VERSION = "0.2.0"

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

DEFAULT_MODEL_ID = "qwen3-vl:8b"
DEV_MODEL_ID = "qwen3-vl:4b"
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_CONTEXT_SIZE = 8192
OLLAMA_MAX_OUTPUT_TOKENS = 2048
MAX_IMAGE_DIMENSION = 1280

# ---------------------------------------------------------------------------
# Confidence thresholds (§16 of the plan)
# ---------------------------------------------------------------------------

DOMAIN_CONFIDENCE_THRESHOLD = 0.80
SUBDOMAIN_CONFIDENCE_THRESHOLD = 0.75
PUZZLE_FAMILY_CONFIDENCE_THRESHOLD = 0.75
SKILL_CONFIDENCE_THRESHOLD = 0.70

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

MAX_SKILLS = 4
MAX_SECONDARY_DOMAINS = 2
MAX_RETRIES = 3
REQUEST_TIMEOUT_SECONDS = 300

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


@dataclass
class PipelineConfig:
    """Runtime configuration for a classification run."""

    model_id: str = DEFAULT_MODEL_ID
    model_revision: str | None = None
    ollama_base_url: str = OLLAMA_BASE_URL
    context_size: int = OLLAMA_CONTEXT_SIZE
    max_output_tokens: int = OLLAMA_MAX_OUTPUT_TOKENS
    max_image_dimension: int = MAX_IMAGE_DIMENSION

    taxonomy_version: str = TAXONOMY_VERSION
    extraction_version: str = EXTRACTION_VERSION
    schema_version: str = SCHEMA_VERSION
    prompt_version: str = PROMPT_VERSION
    preprocessing_version: str = PREPROCESSING_VERSION

    domain_confidence_threshold: float = DOMAIN_CONFIDENCE_THRESHOLD
    subdomain_confidence_threshold: float = SUBDOMAIN_CONFIDENCE_THRESHOLD
    puzzle_family_confidence_threshold: float = (
        PUZZLE_FAMILY_CONFIDENCE_THRESHOLD
    )
    skill_confidence_threshold: float = SKILL_CONFIDENCE_THRESHOLD

    max_retries: int = MAX_RETRIES
    request_timeout: int = REQUEST_TIMEOUT_SECONDS

    input_dir: Path = field(default_factory=lambda: Path("input_puzzles"))
    output_dir: Path = field(default_factory=lambda: Path("classified_puzzles"))

    temperature: float = 0.1  # Low temperature for structured output per Ollama docs

    def run_key_fields(self) -> dict:
        """Fields that together identify a unique run configuration."""
        return {
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "taxonomy_version": self.taxonomy_version,
            "prompt_version": self.prompt_version,
            "preprocessing_version": self.preprocessing_version,
            "schema_version": self.schema_version,
            "context_size": self.context_size,
            "max_output_tokens": self.max_output_tokens,
            "max_image_dimension": self.max_image_dimension,
        }
