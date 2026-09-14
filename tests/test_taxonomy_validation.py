from __future__ import annotations

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from pikpok.config import PipelineConfig
from pikpok.ingestion.preprocessing import preprocess_image
from pikpok.pipeline import analyze_image
from pikpok.pipeline.route_review import route_to_review
from pikpok.pipeline.validate_result import ValidationResult
from pikpok.review.taxonomy_gaps import write_taxonomy_suggestions_report
from pikpok.schemas.analysis import PuzzleAnalysis
from pikpok.schemas.classification import (
    ClassificationResult,
    DiscoverySuggestion,
    DiscoverySuggestions,
    LabelEvidence,
)
from pikpok.schemas.understanding import UnderstandingResult
from pikpok.taxonomy.loader import load_taxonomy
from pikpok.taxonomy.suggestions import filter_discovery_suggestions
from pikpok.taxonomy.validator import validate_classification
from pikpok.scripts import analyze_folder
from pikpok.scripts.analyze_folder import build_client, move_verified_image
from pikpok.scripts.evaluate_model import compute_metrics
from pikpok.vlm.ollama_client import OllamaClient
from pikpok.vlm.ollama_client import extract_json_text
from pikpok.vlm.pass_two import PassTwoError
from pikpok.vlm.prompts import build_pass_two_prompt


def label(
    label_id: str,
    *,
    status: str = "assigned",
    confidence: float = 0.9,
) -> LabelEvidence:
    return LabelEvidence(
        id=label_id,
        confidence=confidence,
        evidence="Visible puzzle evidence",
        status=status,
    )


class TaxonomyHierarchyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.taxonomy = load_taxonomy()

    def test_subdomain_in_secondary_domains_has_actionable_error(self) -> None:
        classification = ClassificationResult(
            puzzle_family=label("sequence_completion"),
            primary_domain=label("math"),
            subdomain=label("arithmetic"),
            secondary_domains=[label("number_theory"), label("sequences")],
        )

        result = validate_classification(classification, self.taxonomy)

        self.assertFalse(result.is_valid)
        self.assertTrue(
            any(
                "'number_theory' is a subdomain of 'math'" in error
                and "subdomain field" in error
                for error in result.errors
            )
        )
        self.assertTrue(
            any(
                "'sequences' is a subdomain of 'math'" in error
                for error in result.errors
            )
        )

    def test_prompt_distinguishes_secondary_domains_from_subdomains(self) -> None:
        prompt = build_pass_two_prompt(self.taxonomy, "{}")

        self.assertIn("MUST be a top-level domain ID", prompt)
        self.assertIn('"number_theory"', prompt)
        self.assertIn("Subdomains belong only in the single `subdomain` field", prompt)

    def test_prompt_can_include_validator_feedback(self) -> None:
        prompt = build_pass_two_prompt(
            self.taxonomy,
            "{}",
            validation_feedback=["use the subdomain field instead"],
        )

        self.assertIn("CORRECTION FEEDBACK FROM THE TAXONOMY VALIDATOR", prompt)
        self.assertIn("use the subdomain field instead", prompt)

    def test_prompts_request_no_think_mode(self) -> None:
        self.assertTrue(build_pass_two_prompt(self.taxonomy, "{}").endswith("/no_think"))

    def test_json_extraction_uses_first_complete_object(self) -> None:
        raw = "Reasoning mentions {not-json}. Final answer: {\"ok\": true} trailing text"

        self.assertEqual(extract_json_text(raw), '{"ok": true}')

    def test_prompt_explains_generator_family_and_all_suggestion_categories(self) -> None:
        prompt = build_pass_two_prompt(self.taxonomy, "{}")

        self.assertIn("puzzle_family` is the generator-facing key", prompt)
        self.assertIn("families", prompt)
        self.assertIn("Do not suggest a label that already exists", prompt)

    def test_known_suggestions_are_removed_but_novel_ones_remain(self) -> None:
        suggestions = DiscoverySuggestions(
            domains=[suggestion("Math"), suggestion("quantum_puzzles")],
            subdomains=[suggestion("sequences"), suggestion("modular_arithmetic")],
            families=[suggestion("Sequence completion"), suggestion("logic_grid")],
            skills=[suggestion("Pattern recognition"), suggestion("symbolic_reasoning")],
        )

        cleaned = filter_discovery_suggestions(suggestions, self.taxonomy)

        self.assertEqual([item.name for item in cleaned.domains], ["quantum_puzzles"])
        self.assertEqual(
            [item.name for item in cleaned.subdomains], ["modular_arithmetic"]
        )
        self.assertEqual([item.name for item in cleaned.families], ["logic_grid"])
        self.assertEqual(
            [item.name for item in cleaned.skills], ["symbolic_reasoning"]
        )

    def test_novel_suggestions_route_to_taxonomy_review(self) -> None:
        classification = ClassificationResult(
            puzzle_family=label("sequence_completion"),
            primary_domain=label("math"),
            subdomain=label("arithmetic"),
            discovery_suggestions=DiscoverySuggestions(
                families=[suggestion("logic_grid")]
            ),
        )

        status, reason = route_to_review(
            classification,
            validate_classification(classification, self.taxonomy),
            taxonomy=self.taxonomy,
        )

        self.assertEqual(status, "needs_taxonomy")
        self.assertIn("new taxonomy candidate", reason or "")

    def test_out_of_taxonomy_required_label_is_valid_and_reviewable(self) -> None:
        classification = ClassificationResult(
            puzzle_family=label(
                "unknown", status="out_of_taxonomy", confidence=0.8
            ),
            primary_domain=label("math"),
            subdomain=label("arithmetic"),
            discovery_suggestions=DiscoverySuggestions(
                families=[suggestion("logic_grid")]
            ),
        )
        validation = validate_classification(classification, self.taxonomy)

        self.assertTrue(validation.is_valid)
        status, reason = route_to_review(
            classification, validation, taxonomy=self.taxonomy
        )

        self.assertEqual(status, "needs_taxonomy")
        self.assertIn("puzzle family", reason or "")

    def test_ambiguous_required_label_is_valid_but_needs_review(self) -> None:
        classification = ClassificationResult(
            puzzle_family=label("sequence_completion"),
            primary_domain=label("math", status="ambiguous"),
            subdomain=label("arithmetic"),
        )
        validation = validate_classification(classification, self.taxonomy)

        self.assertTrue(validation.is_valid)
        status, reason = route_to_review(
            classification, validation, taxonomy=self.taxonomy
        )

        self.assertEqual(status, "pending")
        self.assertIn("Ambiguous primary domain", reason or "")

    def test_optional_labels_must_be_omitted_when_unknown(self) -> None:
        classification = ClassificationResult(
            puzzle_family=label("sequence_completion"),
            primary_domain=label("math"),
            subdomain=label("arithmetic"),
            skills=[label("unknown", status="unknown")],
        )

        result = validate_classification(classification, self.taxonomy)

        self.assertFalse(result.is_valid)
        self.assertIn(
            "optional labels must be omitted when unknown", result.errors[0]
        )

    def test_low_family_confidence_requires_review(self) -> None:
        classification = ClassificationResult(
            puzzle_family=label("sequence_completion", confidence=0.6),
            primary_domain=label("math"),
            subdomain=label("arithmetic"),
        )
        validation = validate_classification(classification, self.taxonomy)

        status, reason = route_to_review(
            classification, validation, taxonomy=self.taxonomy
        )

        self.assertEqual(status, "pending")
        self.assertIn("Low puzzle family confidence", reason or "")

    def test_report_is_single_deduplicated_candidate_artifact(self) -> None:
        classification = ClassificationResult(
            puzzle_family=label("sequence_completion"),
            primary_domain=label("math"),
            subdomain=label("arithmetic"),
            discovery_suggestions=DiscoverySuggestions(
                subdomains=[suggestion("arithmetic"), suggestion("modular_arithmetic")],
                families=[suggestion("logic_grid")],
            ),
        )
        analysis = PuzzleAnalysis(
            source_image_id="puzzle_001",
            original_image_hash="hash",
            taxonomy_version=self.taxonomy.version,
            extraction_version="0.1.0",
            schema_version="0.2.0",
            model_id="test",
            prompt_version="0.3.0",
            preprocessing_version="0.1.0",
            understanding=UnderstandingResult(
                puzzle_summary="A puzzle",
                mechanism="Complete it",
            ),
            classification=classification,
        )

        with TemporaryDirectory() as temp_dir:
            records_dir = Path(temp_dir) / "records"
            report_path = Path(temp_dir) / "reports" / "taxonomy_suggestions.json"
            records_dir.mkdir()
            (records_dir / "puzzle_001.json").write_text(
                analysis.model_dump_json(), encoding="utf-8"
            )

            write_taxonomy_suggestions_report(
                records_dir, report_path, self.taxonomy
            )
            report = report_path.read_text(encoding="utf-8")

        self.assertIn('"total_candidates": 2', report)
        self.assertIn('"suggested_id": "modular_arithmetic"', report)
        self.assertIn('"suggested_id": "logic_grid"', report)
        self.assertNotIn('"suggested_id": "arithmetic"', report)


class OllamaContextTests(unittest.TestCase):
    def test_generate_sends_explicit_context_size(self) -> None:
        fake_http = FakeHTTPClient()
        client = OllamaClient(context_size=8192)
        client._client = fake_http

        client.generate(model="qwen3-vl:4b", prompt="{}")

        self.assertEqual(fake_http.payload["options"]["num_ctx"], 8192)
        self.assertEqual(fake_http.payload["options"]["num_predict"], 2048)
        self.assertFalse(fake_http.payload["think"])
        self.assertEqual(fake_http.payload["model"], "qwen3-vl:4b")

    def test_context_size_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            OllamaClient(context_size=0)

    def test_output_token_limit_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            OllamaClient(max_output_tokens=0)

    def test_batch_client_uses_configured_context_and_output_limits(self) -> None:
        config = PipelineConfig(
            context_size=1234,
            max_output_tokens=567,
            request_timeout=8,
        )
        client = build_client(config)

        try:
            self.assertEqual(client.context_size, 1234)
            self.assertEqual(client.max_output_tokens, 567)
            self.assertEqual(client.timeout, 8)
        finally:
            client.close()


class PipelineRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.taxonomy = load_taxonomy()

    def test_idempotency_requires_the_same_image_hash(self) -> None:
        classification = ClassificationResult(
            puzzle_family=label("sequence_completion"),
            primary_domain=label("math"),
            subdomain=label("arithmetic"),
        )
        record = make_analysis(
            classification, puzzle_id="puzzle_001", image_hash="hash-a"
        )

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            config = PipelineConfig(output_dir=output_dir)
            analyze_image.write_json_record(record, output_dir / "records")

            self.assertTrue(
                analyze_image._is_already_processed(
                    output_dir, "puzzle_001", "hash-a", config
                )
            )
            self.assertFalse(
                analyze_image._is_already_processed(
                    output_dir, "puzzle_001", "hash-b", config
                )
            )

    def test_pass_two_retries_structured_output_parse_failures(self) -> None:
        classification = ClassificationResult(
            puzzle_family=label("sequence_completion"),
            primary_domain=label("math"),
            subdomain=label("arithmetic"),
        )
        understanding = UnderstandingResult(
            puzzle_summary="A puzzle",
            mechanism="Complete it",
        )
        config = PipelineConfig(max_retries=2)
        calls: list[list[str] | None] = []

        def fake_run_pass_two(*args, **kwargs):
            calls.append(kwargs.get("validation_feedback"))
            if len(calls) == 1:
                raise PassTwoError("malformed JSON")
            return classification

        with (
            patch.object(analyze_image, "run_pass_two", fake_run_pass_two),
            patch.object(
                analyze_image,
                "validate_result",
                return_value=ValidationResult(),
            ),
        ):
            result, validation = analyze_image._run_pass_two_with_retries(
                client=object(),
                image=object(),
                understanding=understanding,
                taxonomy=self.taxonomy,
                config=config,
            )

        self.assertEqual(result, classification)
        self.assertTrue(validation.is_valid)
        self.assertEqual(len(calls), 2)
        self.assertIn("not valid JSON", calls[1][0])

    def test_metrics_do_not_count_repeated_failures_as_new_attempts(self) -> None:
        classification = ClassificationResult(
            puzzle_family=label("sequence_completion"),
            primary_domain=label("math"),
            subdomain=label("arithmetic"),
        )
        record = make_analysis(
            classification, puzzle_id="puzzle_001", image_hash="hash"
        )

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            records_dir = output_dir / "records"
            reports_dir = output_dir / "reports"
            records_dir.mkdir(parents=True)
            reports_dir.mkdir()
            (records_dir / "puzzle_001.json").write_text(
                record.model_dump_json(), encoding="utf-8"
            )
            (reports_dir / "errors.jsonl").write_text(
                json.dumps({"puzzle_id": "puzzle_001", "error": "timeout"})
                + "\n"
                + json.dumps({"puzzle_id": "puzzle_001", "error": "parse"})
                + "\n",
                encoding="utf-8",
            )

            metrics = compute_metrics(output_dir)

        self.assertEqual(metrics["total_attempted"], 1)
        self.assertEqual(metrics["total_records"], 1)
        self.assertEqual(metrics["total_errors"], 2)
        self.assertEqual(metrics["schema_valid_rate"], 1.0)

    def test_preprocessing_downscales_large_images_proportionally(self) -> None:
        with TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "puzzle.png"
            Image.new("RGB", (200, 120), color="white").save(image_path)

            result = preprocess_image(
                image_path,
                preprocessing_version="test",
                max_image_dimension=100,
            )

        self.assertEqual(result.original_dimensions, (200, 120))
        self.assertEqual(result.processed_dimensions, (100, 60))

    def test_preprocessing_does_not_enlarge_small_images(self) -> None:
        with TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "puzzle.png"
            Image.new("RGB", (80, 40), color="white").save(image_path)

            result = preprocess_image(
                image_path,
                preprocessing_version="test",
                max_image_dimension=100,
            )

        self.assertEqual(result.processed_dimensions, (80, 40))

    def test_verified_image_move_never_overwrites_existing_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "input"
            verified_dir = Path(temp_dir) / "verified"
            source_dir.mkdir()
            image_path = source_dir / "puzzle.jpg"
            image_path.write_bytes(b"new image")
            verified_dir.mkdir()
            (verified_dir / "puzzle.jpg").write_bytes(b"existing image")

            moved_path = move_verified_image(image_path, verified_dir)

            self.assertFalse(image_path.exists())
            self.assertEqual(
                (verified_dir / "puzzle.jpg").read_bytes(), b"existing image"
            )
            self.assertEqual(moved_path, verified_dir / "puzzle-2.jpg")
            self.assertEqual(moved_path.read_bytes(), b"new image")

    def test_batch_moves_only_approved_images(self) -> None:
        approved = make_analysis(
            ClassificationResult(
                puzzle_family=label("sequence_completion"),
                primary_domain=label("math"),
                subdomain=label("arithmetic"),
            ),
            puzzle_id="approved",
            review_status="approved",
        )
        pending = make_analysis(
            ClassificationResult(
                puzzle_family=label("sequence_completion"),
                primary_domain=label("math"),
                subdomain=label("arithmetic"),
            ),
            puzzle_id="pending",
            review_status="pending",
        )

        class FakeClient:
            def is_model_available(self, model_id: str) -> bool:
                return True

            def close(self) -> None:
                return None

        with TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / "input"
            output_dir = Path(temp_dir) / "output"
            input_dir.mkdir()
            output_dir.mkdir()
            approved_path = input_dir / "approved.png"
            pending_path = input_dir / "pending.png"
            approved_path.write_bytes(b"approved image")
            pending_path.write_bytes(b"pending image")

            argv = [
                "analyze_folder",
                "--input",
                str(input_dir),
                "--output",
                str(output_dir),
                "--move-verified",
            ]
            with (
                patch("sys.argv", argv),
                patch.object(
                    analyze_folder,
                    "list_images",
                    return_value=[approved_path, pending_path],
                ),
                patch.object(
                    analyze_folder,
                    "load_taxonomy",
                    return_value=self.taxonomy,
                ),
                patch.object(
                    analyze_folder,
                    "build_client",
                    return_value=FakeClient(),
                ),
                patch.object(
                    analyze_folder,
                    "analyze_puzzle_image",
                    side_effect=[approved, pending],
                ),
                patch.object(
                    analyze_folder,
                    "write_taxonomy_suggestions_report",
                ),
            ):
                analyze_folder.main()

            self.assertFalse(approved_path.exists())
            self.assertTrue(pending_path.exists())
            self.assertTrue((input_dir / "verified" / "approved.png").exists())
            self.assertFalse((input_dir / "verified" / "pending.png").exists())

    def test_verified_directory_cannot_be_the_input_directory(self) -> None:
        with TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / "input"
            input_dir.mkdir()
            argv = [
                "analyze_folder",
                "--input",
                str(input_dir),
                "--output",
                str(Path(temp_dir) / "output"),
                "--move-verified",
                "--verified-dir",
                str(input_dir),
            ]

            with (
                patch("sys.argv", argv),
                self.assertRaises(SystemExit),
            ):
                analyze_folder.main()


def suggestion(name: str) -> DiscoverySuggestion:
    return DiscoverySuggestion(
        name=name,
        reason="The approved taxonomy is insufficient.",
        evidence="Visible puzzle evidence.",
    )


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"model": "qwen3-vl:4b", "response": "{}"}


class FakeHTTPClient:
    def __init__(self) -> None:
        self.payload: dict = {}

    def post(self, url: str, json: dict) -> FakeResponse:
        self.payload = json
        return FakeResponse()

    def close(self) -> None:
        return None


def make_analysis(
    classification: ClassificationResult,
    *,
    puzzle_id: str = "puzzle_001",
    image_hash: str = "hash",
    review_status: str = "approved",
) -> PuzzleAnalysis:
    config = PipelineConfig()
    return PuzzleAnalysis(
        source_image_id=puzzle_id,
        original_image_hash=image_hash,
        taxonomy_version=config.taxonomy_version,
        extraction_version=config.extraction_version,
        schema_version=config.schema_version,
        model_id=config.model_id,
        context_size=config.context_size,
        max_output_tokens=config.max_output_tokens,
        max_image_dimension=config.max_image_dimension,
        prompt_version=config.prompt_version,
        preprocessing_version=config.preprocessing_version,
        understanding=UnderstandingResult(
            puzzle_summary="A puzzle",
            mechanism="Complete it",
        ),
        classification=classification,
        review_status=review_status,
    )


if __name__ == "__main__":
    unittest.main()
