"""HTTP client for the Ollama API with structured output support.

Uses Ollama's ``format`` field to pass a JSON Schema and enforce structured
output.  Low temperature is used per the Ollama docs recommendation for
reliable structured generation.

Reference: https://github.com/ollama/ollama/blob/main/docs/capabilities/structured-outputs.mdx
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    """Raised when the Ollama API returns an error."""


def extract_json_text(text: str) -> str:
    """Extract the first complete JSON object from model output.

    Thinking-capable models can place prose, tags, or multiple brace pairs
    around the final object. ``str.rfind('}')`` is unsafe in that situation;
    the JSON decoder can identify the end of the first complete object while
    still allowing control characters in legacy model output.
    """
    stripped = text.strip()
    if not stripped:
        return stripped
    if "```json" in stripped:
        start = stripped.find("```json") + 7
        end = stripped.find("```", start)
        if end != -1:
            return stripped[start:end].strip()
        return stripped[start:].strip()
    if "```" in stripped:
        start = stripped.find("```") + 3
        end = stripped.find("```", start)
        if end != -1:
            return stripped[start:end].strip()
        return stripped[start:].strip()
    decoder = json.JSONDecoder(strict=False)
    start = stripped.find("{")
    while start != -1:
        try:
            _, end = decoder.raw_decode(stripped, start)
            return stripped[start:end].strip()
        except json.JSONDecodeError:
            start = stripped.find("{", start + 1)
    return stripped


@dataclass
class OllamaResponse:
    """Parsed response from an Ollama generate/chat call."""

    raw_text: str
    model: str
    total_duration_ns: int | None = None
    eval_count: int | None = None

    @property
    def total_duration_seconds(self) -> float | None:
        if self.total_duration_ns is not None:
            return self.total_duration_ns / 1e9
        return None

    def parse_json(self) -> dict[str, Any]:
        """Parse the raw text as JSON, tolerating thinking wrappers and control characters."""
        cleaned = extract_json_text(self.raw_text)
        return json.loads(cleaned, strict=False)


class OllamaClient:
    """Synchronous HTTP client for the Ollama API."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout: int = 300,
        context_size: int = 8192,
        max_output_tokens: int = 2048,
    ) -> None:
        if context_size < 1:
            raise ValueError("context_size must be at least 1 token")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be at least 1 token")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.context_size = context_size
        self.max_output_tokens = max_output_tokens
        self._client = httpx.Client(timeout=timeout)

    def generate(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        images: list[str] | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.1,
        stream: bool = False,
    ) -> OllamaResponse:
        """Call the Ollama ``/api/generate`` endpoint.

        Parameters
        ----------
        model:
            The model name (e.g. ``qwen3-vl:8b``).
        prompt:
            The text prompt.
        system:
            Optional system prompt instructions.
        images:
            Optional list of base64-encoded images.
        json_schema:
            If provided, passed as the ``format`` field to enforce structured
            JSON output.
        temperature:
            Sampling temperature.  Low values recommended for structured output.
        stream:
            Whether to stream the response.  Currently only ``False`` is
            supported.
        """
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_ctx": self.context_size,
                "num_predict": self.max_output_tokens,
            },
        }

        # Structured classification does not need a visible reasoning trace.
        # Ollama supports this top-level switch for thinking-capable models;
        # older/model-specific runtimes may ignore it harmlessly.
        payload["think"] = False

        if system is not None:
            payload["system"] = system

        if images:
            payload["images"] = images

        if json_schema is not None:
            payload["format"] = json_schema

        url = f"{self.base_url}/api/generate"
        logger.debug("POST %s model=%s", url, model)

        try:
            resp = self._client.post(url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OllamaError(
                f"Ollama returned HTTP {exc.response.status_code}: "
                f"{exc.response.text}"
            ) from exc
        except httpx.ConnectError as exc:
            raise OllamaError(
                f"Cannot connect to Ollama at {self.base_url}. "
                f"Is `ollama serve` running?"
            ) from exc

        data = resp.json()
        raw_text = data.get("response", "")
        # If response is empty, check thinking tokens (e.g. Qwen3 thinking models)
        if not raw_text.strip() and "thinking" in data:
            raw_text = data.get("thinking", "")

        return OllamaResponse(
            raw_text=raw_text,
            model=data.get("model", model),
            total_duration_ns=data.get("total_duration"),
            eval_count=data.get("eval_count"),
        )

    def list_models(self) -> list[dict[str, Any]]:
        """List models available in the local Ollama instance."""
        resp = self._client.get(f"{self.base_url}/api/tags")
        resp.raise_for_status()
        return resp.json().get("models", [])

    def is_model_available(self, model: str) -> bool:
        """Check if a specific model is pulled locally."""
        models = self.list_models()
        return any(m.get("name", "").startswith(model) for m in models)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OllamaClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
