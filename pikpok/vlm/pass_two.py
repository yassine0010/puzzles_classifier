"""Pass 2 execution — taxonomy classification via VLM.

Sends the image, Pass 1 understanding, and the approved taxonomy to the model.
Returns a validated ``ClassificationResult``.
"""

from __future__ import annotations

import json
import logging

from PIL import Image

from pikpok.ingestion.preprocessing import image_to_base64
from pikpok.schemas.classification import ClassificationResult
from pikpok.schemas.understanding import UnderstandingResult
from pikpok.taxonomy.loader import Taxonomy
from pikpok.vlm.ollama_client import OllamaClient
from pikpok.vlm.prompts import build_pass_two_prompt

logger = logging.getLogger(__name__)


class PassTwoError(Exception):
    """Raised when Pass 2 fails to produce a valid result."""


def run_pass_two(
    client: OllamaClient,
    image: Image.Image,
    understanding: UnderstandingResult,
    taxonomy: Taxonomy,
    model: str = "qwen3-vl:8b",
    temperature: float = 0.1,
    validation_feedback: list[str] | None = None,
) -> ClassificationResult:
    """Execute Pass 2: taxonomy classification of the puzzle.

    Parameters
    ----------
    client:
        An initialized ``OllamaClient``.
    image:
        The preprocessed PIL image (same one sent to Pass 1).
    understanding:
        The validated Pass 1 output.
    taxonomy:
        The loaded taxonomy with approved IDs.
    model:
        The Ollama model name.
    temperature:
        Sampling temperature.
    validation_feedback:
        Optional errors from a previous taxonomy validation attempt. These are
        included in the prompt when Pass 2 is retried.

    Returns
    -------
    ClassificationResult
        A validated Pydantic model of the classification output.

    Raises
    ------
    PassTwoError
        If the model response cannot be parsed or validated.
    """
    understanding_json = understanding.model_dump_json(indent=2)
    prompt = build_pass_two_prompt(
        taxonomy,
        understanding_json,
        validation_feedback=validation_feedback,
    )
    image_b64 = image_to_base64(image)
    json_schema = ClassificationResult.model_json_schema()

    logger.info("Pass 2: sending image + understanding to %s", model)

    response = client.generate(
        model=model,
        prompt=prompt,
        system="You are a concise taxonomy classification assistant. Return ONLY valid JSON matching the schema without reasoning or think tags.",
        images=[image_b64],
        json_schema=json_schema,
        temperature=temperature,
    )

    logger.info(
        "Pass 2 complete in %.1fs (%d tokens)",
        response.total_duration_seconds or 0,
        response.eval_count or 0,
    )

    try:
        data = response.parse_json()
        classification = ClassificationResult.model_validate(data)
    except Exception as exc:
        logger.error("Pass 2 validation failed: %s", exc)
        logger.debug("Raw response: %s", response.raw_text)
        raise PassTwoError(
            f"Failed to parse Pass 2 output: {exc}"
        ) from exc

    return classification
