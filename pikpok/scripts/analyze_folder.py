#!/usr/bin/env python3
"""Batch-process a folder of puzzle screenshots.

Usage:
    python -m pikpok.scripts.analyze_folder --input input_puzzles/ --output classified_puzzles/

This is the main entry point for v0.1. It processes every supported image in
the input directory, produces immutable JSON records, generates staging views,
and writes reports. Processing is resumable — images that already have records
for the current configuration are skipped.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path

from pikpok.config import PipelineConfig
from pikpok.ingestion.image_loader import list_images
from pikpok.pipeline.analyze_image import analyze_puzzle_image, append_error
from pikpok.review.taxonomy_gaps import write_taxonomy_suggestions_report
from pikpok.taxonomy.loader import load_taxonomy
from pikpok.vlm.ollama_client import OllamaClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-classify puzzle screenshots using PikPok VLM pipeline."
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=Path("input_puzzles"),
        help="Input directory containing puzzle screenshots.",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("classified_puzzles"),
        help="Output directory for records and views.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="qwen3-vl:8b",
        help="Ollama model name.",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama base URL.",
    )
    parser.add_argument(
        "--context-size",
        type=int,
        default=8192,
        help="Ollama context window in tokens (default: 8192).",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=300,
        help="HTTP timeout per Ollama request in seconds (default: 300).",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=2048,
        help="Maximum generated tokens per Ollama request (default: 2048).",
    )
    parser.add_argument(
        "--max-image-dimension",
        type=int,
        default=1280,
        help=(
            "Proportionally downscale images before VLM inference; larger "
            "values are slower but preserve detail (default: 1280)."
        ),
    )
    parser.add_argument(
        "--move-verified",
        action="store_true",
        help="Move automatically approved images out of the input folder.",
    )
    parser.add_argument(
        "--verified-dir",
        type=Path,
        default=None,
        help=(
            "Destination for approved images. Defaults to "
            "<input>/verified when --move-verified is used."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N images (useful for testing).",
    )
    return parser.parse_args()


def build_client(config: PipelineConfig) -> OllamaClient:
    """Build the shared Ollama client from the complete run configuration."""
    return OllamaClient(
        base_url=config.ollama_base_url,
        timeout=config.request_timeout,
        context_size=config.context_size,
        max_output_tokens=config.max_output_tokens,
    )


def move_verified_image(image_path: Path, destination_dir: Path) -> Path:
    """Move an approved image without overwriting an existing file."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / image_path.name
    counter = 2

    while destination.exists():
        destination = destination_dir / (
            f"{image_path.stem}-{counter}{image_path.suffix}"
        )
        counter += 1

    moved = shutil.move(str(image_path), str(destination))
    return Path(moved)


def main() -> None:
    args = parse_args()

    config = PipelineConfig(
        model_id=args.model,
        ollama_base_url=args.ollama_url,
        context_size=args.context_size,
        request_timeout=args.request_timeout,
        max_output_tokens=args.max_output_tokens,
        max_image_dimension=args.max_image_dimension,
        input_dir=args.input,
        output_dir=args.output,
    )
    verified_dir = args.verified_dir or config.input_dir / "verified"
    if args.move_verified and verified_dir.resolve() == config.input_dir.resolve():
        logger.error(
            "Verified directory cannot be the same as the input directory: %s",
            verified_dir,
        )
        sys.exit(1)

    # Discover images
    images = list_images(config.input_dir)
    if not images:
        logger.error("No images found in %s", config.input_dir)
        sys.exit(1)

    if args.limit:
        images = images[: args.limit]

    logger.info("Found %d images to process", len(images))

    # Load taxonomy once
    taxonomy = load_taxonomy(expected_version=config.taxonomy_version)
    logger.info("Taxonomy v%s loaded (%d domains, %d skills, %d families)",
                taxonomy.version,
                len(taxonomy.domains),
                len(taxonomy.skills),
                len(taxonomy.puzzle_families))

    # Create shared client
    client = build_client(config)

    try:
        # Check model availability
        if not client.is_model_available(config.model_id):
            logger.error(
                "Model '%s' not found in Ollama. Run: ollama pull %s",
                config.model_id,
                config.model_id,
            )
            sys.exit(1)

        # Process images
        errors_path = config.output_dir / "reports" / "errors.jsonl"
        total = len(images)
        succeeded = 0
        failed = 0
        moved = 0
        start_time = time.time()

        for idx, image_path in enumerate(images, 1):
            puzzle_id = image_path.stem
            logger.info("[%d/%d] %s", idx, total, image_path.name)

            try:
                analysis = analyze_puzzle_image(
                    image_path,
                    config=config,
                    client=client,
                    taxonomy=taxonomy,
                )

                succeeded += 1

                if args.move_verified and analysis.review_status == "approved":
                    moved_path = move_verified_image(image_path, verified_dir)
                    moved += 1
                    logger.info("Verified image moved to %s", moved_path)

            except Exception as exc:
                failed += 1
                logger.error("Failed to process %s: %s", image_path.name, exc)
                append_error(
                    {
                        "puzzle_id": puzzle_id,
                        "image_path": str(image_path),
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                    errors_path,
                )
    finally:
        client.close()

    write_taxonomy_suggestions_report(
        config.output_dir / "records",
        config.output_dir / "reports" / "taxonomy_suggestions.json",
        taxonomy,
    )

    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("Batch processing complete")
    logger.info("  Total:     %d", total)
    logger.info("  Succeeded: %d", succeeded)
    logger.info("  Failed:    %d", failed)
    logger.info("  Moved:     %d", moved)
    logger.info("  Time:      %.1fs (%.1fs per image)", elapsed, elapsed / max(total, 1))
    logger.info("  Output:    %s", config.output_dir)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
