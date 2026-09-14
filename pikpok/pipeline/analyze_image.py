"""End-to-end single-image analysis pipeline.

Implements the pseudocode from §22 of the plan:
  ingest → hash → preprocess → Pass 1 → Pass 2 → validate → route → write
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PIL import Image

from pikpok.config import PipelineConfig
from pikpok.ingestion.hashing import sha256_file
from pikpok.ingestion.preprocessing import preprocess_image
from pikpok.pipeline.route_review import route_to_review
from pikpok.pipeline.validate_result import ValidationResult
from pikpok.pipeline.validate_result import validate_result
from pikpok.schemas.analysis import PuzzleAnalysis
from pikpok.schemas.classification import ClassificationResult
from pikpok.schemas.understanding import UnderstandingResult
from pikpok.taxonomy.loader import Taxonomy, load_taxonomy
from pikpok.taxonomy.suggestions import filter_discovery_suggestions
from pikpok.vlm.ollama_client import OllamaClient
from pikpok.vlm.pass_one import PassOneError, run_pass_one
from pikpok.vlm.pass_two import PassTwoError, run_pass_two

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Idempotency helpers
# ---------------------------------------------------------------------------


def _record_path(output_dir: Path, puzzle_id: str) -> Path:
    return output_dir / "records" / f"{puzzle_id}.json"


def _is_already_processed(
    output_dir: Path,
    puzzle_id: str,
    image_hash: str,
    config: PipelineConfig,
) -> bool:
    """Check whether a record exists for this image and run configuration.

    A prompt, taxonomy, or model revision change must not be hidden by the
    puzzle-id idempotency check, and neither may a changed image with the
    same filename. Such records are safely superseded by a new record when
    the pipeline is rerun.
    """
    record_path = _record_path(output_dir, puzzle_id)
    if not record_path.exists():
        return False

    try:
        existing = PuzzleAnalysis.model_validate_json(
            record_path.read_text(encoding="utf-8")
        )
    except Exception:
        # A corrupt/incomplete record should be repaired by rerunning it.
        return False

    config_matches = all(
        getattr(existing, field_name, object()) == expected_value
        for field_name, expected_value in config.run_key_fields().items()
    )
    return config_matches and existing.original_image_hash == image_hash


# ---------------------------------------------------------------------------
# Bounded VLM retries
# ---------------------------------------------------------------------------


def _run_pass_one_with_retries(
    client: OllamaClient,
    image: Image.Image,
    config: PipelineConfig,
) -> UnderstandingResult:
    """Run Pass 1, retrying structured-output parse failures."""
    last_error: PassOneError | None = None
    attempts = max(1, config.max_retries + 1)

    for attempt in range(1, attempts + 1):
        try:
            return run_pass_one(
                client,
                image,
                model=config.model_id,
                temperature=config.temperature,
            )
        except PassOneError as exc:
            last_error = exc
            logger.warning(
                "Pass 1 structured-output parse failed on attempt %d/%d: %s",
                attempt,
                attempts,
                exc,
            )

    assert last_error is not None
    raise last_error


def _run_pass_two_with_retries(
    client: OllamaClient,
    image: Image.Image,
    understanding: UnderstandingResult,
    taxonomy: Taxonomy,
    config: PipelineConfig,
) -> tuple[ClassificationResult, ValidationResult]:
    """Run Pass 2 with bounded parse and taxonomy-correction retries."""
    feedback: list[str] | None = None
    last_classification: ClassificationResult | None = None
    last_validation = None
    last_error: PassTwoError | None = None
    attempts = max(1, config.max_retries + 1)

    for attempt in range(1, attempts + 1):
        try:
            classification = run_pass_two(
                client,
                image,
                understanding,
                taxonomy,
                model=config.model_id,
                temperature=config.temperature,
                validation_feedback=feedback,
            )
        except PassTwoError as exc:
            last_error = exc
            feedback = [f"Previous response was not valid JSON: {exc}"]
            logger.warning(
                "Pass 2 structured-output parse failed on attempt %d/%d: %s",
                attempt,
                attempts,
                exc,
            )
            continue

        last_classification = classification
        last_validation = validate_result(classification, taxonomy)
        if last_validation.is_valid:
            break

        feedback = last_validation.errors
        logger.info(
            "Pass 2 taxonomy validation failed on attempt %d/%d; "
            "requesting correction",
            attempt,
            attempts,
        )

    if last_classification is None:
        assert last_error is not None
        raise last_error

    assert last_validation is not None
    return last_classification, last_validation


# ---------------------------------------------------------------------------
# Record writing
# ---------------------------------------------------------------------------


def write_json_record(analysis: PuzzleAnalysis, records_dir: Path) -> Path:
    """Write an immutable JSON record atomically.

    Writes to a temporary file first, then renames to avoid partial writes.
    """
    records_dir.mkdir(parents=True, exist_ok=True)
    dest = records_dir / f"{analysis.source_image_id}.json"

    # Atomic write: write to .tmp then rename
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(
        analysis.model_dump_json(indent=2),
        encoding="utf-8",
    )
    tmp.rename(dest)

    logger.info("Wrote record: %s", dest)
    return dest


def append_manifest(
    analysis: PuzzleAnalysis, manifest_path: Path
) -> None:
    """Append a single-line JSON entry to the JSONL manifest."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    line = analysis.model_dump_json() + "\n"
    with open(manifest_path, "a", encoding="utf-8") as f:
        f.write(line)


def append_error(
    error_entry: dict, errors_path: Path
) -> None:
    """Append an error entry to the JSONL error ledger."""
    errors_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(error_entry, ensure_ascii=False) + "\n"
    with open(errors_path, "a", encoding="utf-8") as f:
        f.write(line)


# ---------------------------------------------------------------------------
# Staging view generation
# ---------------------------------------------------------------------------


def generate_classification_views(
    analysis: PuzzleAnalysis, output_dir: Path
) -> None:
    """Generate staging classification views (symlinks or copies).

    Creates the directory structure from §17:
      staging/by_domain/<domain>/<subdomain>/<puzzle_id>.json
      staging/by_family/<family>/<puzzle_id>.json
      staging/by_skill/<skill>/<puzzle_id>.json
    """
    puzzle_id = analysis.source_image_id
    record_path = _record_path(output_dir, puzzle_id)
    cls = analysis.classification

    # --- by_domain view ---
    domain_id = cls.primary_domain.id
    subdomain_id = cls.subdomain.id
    if domain_id != "unknown":
        sub_dir = subdomain_id if subdomain_id != "unknown" else "_unknown"
        view_dir = output_dir / "staging" / "by_domain" / domain_id / sub_dir
        view_dir.mkdir(parents=True, exist_ok=True)
        _create_link_or_copy(record_path, view_dir / f"{puzzle_id}.json")

    # --- by_family view ---
    family_id = cls.puzzle_family.id
    if family_id != "unknown":
        view_dir = output_dir / "staging" / "by_family" / family_id
        view_dir.mkdir(parents=True, exist_ok=True)
        _create_link_or_copy(record_path, view_dir / f"{puzzle_id}.json")

    # --- by_skill views ---
    for skill in cls.skills:
        if skill.id != "unknown":
            view_dir = output_dir / "staging" / "by_skill" / skill.id
            view_dir.mkdir(parents=True, exist_ok=True)
            _create_link_or_copy(record_path, view_dir / f"{puzzle_id}.json")

    # --- review folder for uncertain items ---
    if analysis.review_status == "pending":
        review_dir = output_dir / "review" / "low_confidence"
        review_dir.mkdir(parents=True, exist_ok=True)
        _create_link_or_copy(record_path, review_dir / f"{puzzle_id}.json")
    elif analysis.review_status == "needs_taxonomy":
        review_dir = output_dir / "review" / "taxonomy_gap"
        review_dir.mkdir(parents=True, exist_ok=True)
        _create_link_or_copy(record_path, review_dir / f"{puzzle_id}.json")
    elif analysis.review_status == "rejected":
        review_dir = output_dir / "review" / "rejected"
        review_dir.mkdir(parents=True, exist_ok=True)
        _create_link_or_copy(record_path, review_dir / f"{puzzle_id}.json")

    # --- unknown domain/subdomain views ---
    if domain_id == "unknown":
        review_dir = output_dir / "review" / "unknown_domain"
        review_dir.mkdir(parents=True, exist_ok=True)
        _create_link_or_copy(record_path, review_dir / f"{puzzle_id}.json")
    if subdomain_id == "unknown" and domain_id != "unknown":
        review_dir = output_dir / "review" / "unknown_subdomain"
        review_dir.mkdir(parents=True, exist_ok=True)
        _create_link_or_copy(record_path, review_dir / f"{puzzle_id}.json")


def _create_link_or_copy(source: Path, dest: Path) -> None:
    """Create a symlink if possible, otherwise copy."""
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    try:
        dest.symlink_to(source.resolve())
    except OSError:
        # Fallback to copy if symlinks aren't supported
        import shutil
        shutil.copy2(source, dest)


def _remove_existing_views(output_dir: Path, puzzle_id: str) -> None:
    """Remove generated views for one puzzle before replacing its record.

    A rerun can change a puzzle from rejected to approved (or vice versa).
    Removing only this puzzle's generated links prevents stale review entries
    while leaving all other records untouched.
    """
    for root_name in ("staging", "review"):
        root = output_dir / root_name
        if not root.is_dir():
            continue
        for view_path in root.rglob(f"{puzzle_id}.json"):
            if view_path.is_symlink() or view_path.is_file():
                view_path.unlink()


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------


def analyze_puzzle_image(
    image_path: Path | str,
    config: PipelineConfig | None = None,
    client: OllamaClient | None = None,
    taxonomy: Taxonomy | None = None,
) -> PuzzleAnalysis:
    """Analyze a single puzzle screenshot end-to-end.

    Parameters
    ----------
    image_path:
        Path to the puzzle screenshot.
    config:
        Pipeline configuration.  Uses defaults if ``None``.
    client:
        An initialized Ollama client.  Created internally if ``None``.
    taxonomy:
        The loaded taxonomy.  Loaded from the bundled YAML if ``None``.

    Returns
    -------
    PuzzleAnalysis
        The complete immutable analysis record.
    """
    if config is None:
        config = PipelineConfig()

    image_path = Path(image_path)
    puzzle_id = image_path.stem
    image_hash = sha256_file(image_path)

    # Check idempotency
    record_exists = _record_path(config.output_dir, puzzle_id).exists()
    if _is_already_processed(
        config.output_dir, puzzle_id, image_hash, config
    ):
        logger.info("Already processed: %s — loading existing record", puzzle_id)
        record = _record_path(config.output_dir, puzzle_id)
        return PuzzleAnalysis.model_validate_json(
            record.read_text(encoding="utf-8")
        )

    # Load taxonomy
    if taxonomy is None:
        taxonomy = load_taxonomy(expected_version=config.taxonomy_version)

    # Preprocess
    logger.info("Processing: %s", image_path.name)
    prep = preprocess_image(
        image_path,
        preprocessing_version=config.preprocessing_version,
        max_image_dimension=config.max_image_dimension,
    )

    # Create client if needed
    own_client = client is None
    if own_client:
        client = OllamaClient(
            base_url=config.ollama_base_url,
            timeout=config.request_timeout,
            context_size=config.context_size,
            max_output_tokens=config.max_output_tokens,
        )

    try:
        # Pass 1: Understanding
        understanding = _run_pass_one_with_retries(
            client,
            prep.processed_image,
            config,
        )

        # Pass 2 combines structured-output retries with taxonomy-correction
        # retries. The final result is still routed to review if it remains
        # invalid after all attempts.
        classification, validation = _run_pass_two_with_retries(
            client,
            prep.processed_image,
            understanding,
            taxonomy,
            config,
        )
    finally:
        if own_client:
            client.close()

    # ``validation`` is populated after the initial Pass 2 call and each
    # correction retry.  Keep the final result for review routing even when it
    # remains invalid after all retries.

    # Keep only genuine taxonomy candidates in the canonical record.  Models
    # often repeat an approved label as a "new" suggestion; that is not a gap
    # and must not create a taxonomy review item.
    classification = classification.model_copy(
        update={
            "discovery_suggestions": filter_discovery_suggestions(
                classification.discovery_suggestions,
                taxonomy,
            )
        }
    )

    # Route to review
    review_status, review_reason = route_to_review(
        classification, validation, config, taxonomy
    )

    # Build the immutable record
    analysis = PuzzleAnalysis(
        source_image_id=puzzle_id,
        original_image_hash=prep.original_hash,
        processed_image_hash=prep.processed_hash,
        original_dimensions=prep.original_dimensions,
        processed_dimensions=prep.processed_dimensions,
        taxonomy_version=config.taxonomy_version,
        extraction_version=config.extraction_version,
        schema_version=config.schema_version,
        model_id=config.model_id,
        model_revision=config.model_revision,
        context_size=config.context_size,
        max_output_tokens=config.max_output_tokens,
        max_image_dimension=config.max_image_dimension,
        prompt_version=config.prompt_version,
        preprocessing_version=config.preprocessing_version,
        understanding=understanding,
        classification=classification,
        review_status=review_status,
        review_reason=review_reason,
    )

    # Write outputs.  Clean stale generated views only after analysis has
    # succeeded, so a failed rerun leaves the previous record and its views
    # consistent.
    if record_exists:
        _remove_existing_views(config.output_dir, puzzle_id)
    write_json_record(analysis, config.output_dir / "records")
    generate_classification_views(analysis, config.output_dir)
    append_manifest(
        analysis, config.output_dir / "reports" / "manifest.jsonl"
    )

    logger.info(
        "Completed: %s → %s/%s (review: %s)",
        puzzle_id,
        classification.primary_domain.id,
        classification.subdomain.id,
        review_status,
    )

    return analysis
