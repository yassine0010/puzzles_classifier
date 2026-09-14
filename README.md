# PikPok

PikPok classifies English puzzle screenshots with a local vision-language model,
then writes structured taxonomy records and review queues.

## Quick Start

### 1. Install

```bash
python -m pip install -r requirements.txt
ollama pull qwen3-vl:8b
ollama pull qwen3-vl:4b
```

### 2. Start Ollama

Run this in a separate terminal:

```bash
ollama serve
```

### 3. Classify Puzzles

Place PNG, JPG, JPEG, WEBP, BMP, or GIF files in `input_puzzles/`.

```bash
source .venv/bin/activate
python -m pikpok.scripts.analyze_folder \
    --input input_puzzles/ \
    --output classified_puzzles/ \
    --model qwen3-vl:8b
```

For a faster run:

```bash
python -m pikpok.scripts.analyze_folder \
    --input input_puzzles/ \
    --output classified_puzzles/ \
    --model qwen3-vl:4b \
    --max-image-dimension 1024
```

To process only the first image while testing:

```bash
python -m pikpok.scripts.analyze_folder \
    --input input_puzzles/ \
    --output classified_puzzles/ \
    --model qwen3-vl:4b \
    --max-image-dimension 1024 \
    --limit 1
```

## Speed And Memory

Images are proportionally downscaled before inference. Small images are never
enlarged, and the original hash and dimensions remain in the record.

| Setting | Use when |
|---|---|
| `--model qwen3-vl:4b --max-image-dimension 1024` | Fastest stable local run |
| `--model qwen3-vl:8b --max-image-dimension 1280` | Balanced default |
| `--max-image-dimension 1536` or `2048` | Small text is being missed |

The batch runner is intentionally sequential. Running several analyses at the
same time is the easiest way to exhaust RAM, so increase image detail rather
than concurrency when quality drops.

## Moving Approved Images

Add `--move-verified` to move each image whose final record has
`review_status: "approved"`:

```bash
python -m pikpok.scripts.analyze_folder \
    --input input_puzzles/ \
    --output classified_puzzles/ \
    --model qwen3-vl:4b \
    --max-image-dimension 1024 \
    --move-verified
```

Approved images move to `input_puzzles/verified/` by default. Use
`--verified-dir /path/to/folder` for another destination.

Pending, rejected, and taxonomy-gap images remain in the input folder. Existing
destination files are never overwritten; a colliding filename becomes
`puzzle-2.png`, `puzzle-3.png`, and so on.

## Useful Options

| Option | Default | Purpose |
|---|---:|---|
| `--model` | `qwen3-vl:8b` | Ollama model |
| `--input`, `-i` | `input_puzzles` | Folder containing screenshots |
| `--output`, `-o` | `classified_puzzles` | Record and report destination |
| `--max-image-dimension` | `1280` | Largest image side after downscaling |
| `--context-size` | `8192` | Ollama context window |
| `--max-output-tokens` | `2048` | Response token limit |
| `--request-timeout` | `300` | Seconds per Ollama request |
| `--limit` | none | Process at most N images |
| `--move-verified` | off | Move approved images after processing |
| `--verified-dir` | `<input>/verified` | Custom approved-image destination |

The pipeline disables visible thinking traces and retries bounded structured
output or taxonomy-correction failures before routing a record for review.

## Output

```text
classified_puzzles/
  records/
    <puzzle_id>.json
  staging/
    by_domain/
    by_family/
    by_skill/
  review/
    rejected/
    unknown_domain/
    unknown_subdomain/
    taxonomy_gap/
    low_confidence/
  reports/
    manifest.jsonl
    errors.jsonl
    metrics.json
    taxonomy_suggestions.json
```

### What Each Folder Means

- `records/`: canonical, immutable classification records.
- `staging/`: convenient views of model predictions.
- `review/`: records that need human attention.
- `reports/`: batch summaries, errors, metrics, and taxonomy candidates.

Generate metrics:

```bash
python -m pikpok.scripts.evaluate_model --output classified_puzzles/
```

Regenerate staging views:

```bash
python -m pikpok.scripts.organize_folder \
    --output classified_puzzles/ --clean
```

## Review Statuses

| Status | Meaning |
|---|---|
| `approved` | Passed validation and confidence thresholds |
| `pending` | Low confidence or ambiguous labels need review |
| `rejected` | Final result failed strict taxonomy validation |
| `needs_taxonomy` | The model proposes a label missing from the taxonomy |

`approved` means approved by the automated rules in this run, not separately
confirmed by a human reviewer.

## Classification Fields

| Field | Meaning | Later use |
|---|---|---|
| `puzzle_family` | Operation the solver performs | Primary generator key |
| `primary_domain` | Broad subject area | Content constraint |
| `subdomain` | Specific subject under the domain | Finer constraint |
| `mechanics` | Observable puzzle operations | Optional generation parameters |
| `skills` | Cognitive abilities needed | Descriptive metadata |
| `secondary_domains` | Genuine cross-domain relationships | Optional metadata |
| `discovery_suggestions` | Proposed missing labels | Human taxonomy review |

Use `unknown` when evidence is insufficient. Use `out_of_taxonomy` only when
the puzzle clearly needs a new approved label; put the proposal itself in
`discovery_suggestions`.

## Pipeline

```text
Puzzle screenshot
  -> ingestion, hashing, downscaling
  -> VLM Pass 1: puzzle understanding
  -> VLM Pass 2: taxonomy classification
  -> schema and taxonomy validation
  -> confidence-based review routing
  -> immutable record, staging views, reports
```

The taxonomy report is deduplicated and contains only candidates that are not
already approved. Repeated model suggestions already present in the taxonomy
are removed before records are written.

## Project Structure

```text
pikpok/
  ingestion/    # Image loading, hashing, preprocessing
  schemas/      # Pydantic models
  taxonomy/     # Taxonomy YAML, loader, validator
  vlm/          # Ollama client, prompts, model passes
  pipeline/     # Analysis, validation, review routing
  review/       # Review queue and taxonomy gap tracking
  scripts/      # CLI entry points
```

## Tests

```bash
.venv/bin/python -m unittest discover -v
```

## Taxonomy

The current taxonomy is version `0.1.0`. It defines 8 domains, 12 skills, and 8
puzzle families. See `pikpok/taxonomy/taxonomy.yaml` for the full definitions.
