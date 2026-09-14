"""Pass 1 execution — puzzle understanding via VLM.

Sends the preprocessed image and the understanding prompt to the local model.
Returns a validated ``UnderstandingResult``.
"""

from __future__ import annotations

import json
import logging

from PIL import Image

from pikpok.ingestion.preprocessing import image_to_base64
from pikpok.schemas.understanding import UnderstandingResult
from pikpok.vlm.ollama_client import OllamaClient
from pikpok.vlm.prompts import build_pass_one_prompt

logger = logging.getLogger(__name__)


class PassOneError(Exception):
    """Raised when Pass 1 fails to produce a valid result."""


def run_pass_one(
    client: OllamaClient,
    image: Image.Image,
    model: str = "qwen3-vl:8b",
    temperature: float = 0.1,
) -> UnderstandingResult:
    """Execute Pass 1: visual understanding of the puzzle screenshot.

    Parameters
    ----------
    client:
        An initialized ``OllamaClient``.
    image:
        The preprocessed PIL image.
    model:
        The Ollama model name.
    temperature:
        Sampling temperature.

    Returns
    -------
    UnderstandingResult
        A validated Pydantic model of the understanding output.

    Raises
    ------
    PassOneError
        If the model response cannot be parsed or validated.
    """
    prompt = build_pass_one_prompt()
    image_b64 = image_to_base64(image)
    json_schema = UnderstandingResult.model_json_schema()

    logger.info("Pass 1: sending image to %s", model)

    response = client.generate(
        model=model,
        prompt=prompt,
        system="You are a concise visual puzzle understanding assistant. Return ONLY valid JSON matching the schema without reasoning or think tags.",
        images=[image_b64],
        json_schema=json_schema,
        temperature=temperature,
    )

    logger.info(
        "Pass 1 complete in %.1fs (%d tokens)",
        response.total_duration_seconds or 0,
        response.eval_count or 0,
    )

    try:
        data = response.parse_json()
        understanding = UnderstandingResult.model_validate(data)
    except Exception as exc:
        logger.error("Pass 1 validation failed: %s", exc)
        logger.debug("Raw response: %s", response.raw_text)
        raise PassOneError(
            f"Failed to parse Pass 1 output: {exc}"
        ) from exc

    return understanding
