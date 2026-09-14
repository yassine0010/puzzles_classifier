# PikPok — VLM Puzzle Classification System

Local, VLM-based classification of English puzzle screenshots into a structured
taxonomy of domains, subdomains, puzzle families, and skills.

## Quick Start

### Prerequisites

```bash
# Install Ollama
brew install ollama

# Start the server
ollama serve

# Pull the models
ollama pull qwen3-vl:8b    # evaluation model
ollama pull qwen3-vl:4b    # development model (faster)
```

### Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Classify a Folder of Puzzles

```bash
python -m pikpok.scripts.analyze_folder \
    --input input_puzzles/ \
    --output classified_puzzles/ \
    --model qwen3-vl:8b
```

### Run Faster Without Extra Memory Pressure

For a faster local run, use the 4B model and cap the image dimension:

```bash
python -m pikpok.scripts.analyze_folder \
    --input input_puzzles/ \
    --output classified_puzzles/ \
    --model qwen3-vl:4b \
    --max-image-dimension 1024
```

The default is `qwen3-vl:8b` with `--max-image-dimension 1280`, which is the
balanced quality/speed setting. Large images are proportionally downscaled
before inference; they are never enlarged, and the original image hash and
dimensions remain in the record. Keep the batch runner sequential rather than
starting multiple analyses at once, because parallel VLM calls are the easiest
way to exhaust RAM.

If small puzzle text is being missed, retry that puzzle with
`--max-image-dimension 1536` or `2048` instead of increasing concurrency.

### Move Approved Images

Add `--move-verified` to move images whose final record has
`review_status: "approved"` into `input_puzzles/verified/`:

```bash
python -m pikpok.scripts.analyze_folder \
    --input input_puzzles/ \
    --output classified_puzzles/ \
    --model qwen3-vl:4b \
    --max-image-dimension 1024 \
    --move-verified
```

Use `--verified-dir /path/to/folder` for a custom destination. Existing
destination files are never overwritten; a colliding filename is saved as
`puzzle-2.png`, `puzzle-3.png`, and so on. Pending, rejected, and
taxonomy-gap puzzles remain in the input folder for review.

### Evaluate Results

```bash
python -m pikpok.scripts.evaluate_model --output classified_puzzles/
```

### Regenerate Views

```bash
python -m pikpok.scripts.organize_folder --output classified_puzzles/ --clean
```

## How To Test Any New Puzzle

Follow these simple steps whenever you have a new puzzle screenshot (PNG, JPG, or JPEG) to test:

### 1. Place the Image into the Input Folder

```bash
mkdir -p input_puzzles
cp /path/to/your/image.png input_puzzles/
```

### 2. Ensure Ollama is Running

```bash
# In a separate terminal or background process:
ollama serve

# Verify model is available (qwen3-vl:4b or qwen3-vl:8b)
ollama list
```

### 3. Run the Classification Pipeline

```bash
source .venv/bin/activate

python -m pikpok.scripts.analyze_folder \
    --input input_puzzles/ \
    --output classified_puzzles/ \
    --model qwen3-vl:4b
```

> **Tip**: Use `--limit 1` if you only want to process the first image in the folder for a quick test.

The pipeline requests an 8,192-token Ollama context, disables unnecessary
thinking traces, caps each response at 2,048 tokens, and uses a 300-second
request timeout by default. If a larger taxonomy or model needs more room, use
`--context-size 16384 --max-output-tokens 4096 --request-timeout 600`.

### 4. Inspect the Results

- **Complete JSON Record**:
  ```bash
  cat classified_puzzles/records/<image_name>.json
  ```
  Contains image hashes, visual understanding (Pass 1), taxonomy classification (Pass 2), confidence scores, and review status.

- **Staging Folder Views**:
  Explore categorized predictions organized by taxonomy dimensions:
  - `classified_puzzles/staging/by_domain/<domain>/<subdomain>/`
  - `classified_puzzles/staging/by_family/<puzzle_family>/`
  - `classified_puzzles/staging/by_skill/<skill>/`

- **Review Queue**:
  Check if the puzzle was flagged for human review (low confidence, unknown labels, or validation issues):
  - `classified_puzzles/review/rejected/`
  - `classified_puzzles/review/low_confidence/`
  - `classified_puzzles/review/taxonomy_gap/`

- **Reports**:
  - `classified_puzzles/reports/manifest.jsonl` — Full batch manifest.
  - `classified_puzzles/reports/taxonomy_suggestions.json` — One deduplicated report of genuinely new taxonomy candidates.
  - `classified_puzzles/reports/errors.jsonl` — Any processing errors encountered.

## Project Structure

```
pikpok/
  taxonomy/           # Taxonomy YAML, loader, validator, versioning
  schemas/            # Pydantic models (understanding, classification, analysis)
  ingestion/          # Image loading, hashing, preprocessing
  vlm/                # Ollama client, prompts, Pass 1 & 2 execution
  pipeline/           # End-to-end analysis, validation, review routing
  review/             # Review queue, corrections, taxonomy gap tracking
  scripts/            # CLI entry points for batch processing
```

## Output Structure

```
classified_puzzles/
  records/            # One immutable JSON record per puzzle
  staging/            # Model predictions (not approved ground truth)
    by_domain/
    by_family/
    by_skill/
  review/             # Items needing human attention
    rejected/         # Failed strict taxonomy validation
    unknown_domain/   # Unidentified domain
    unknown_subdomain/ # Identified domain but unrecognized subdomain
    taxonomy_gap/     # Model identified a gap in the taxonomy
    low_confidence/   # Confidence < threshold (0.70)
  reports/            # Manifest, errors, metrics, and one taxonomy suggestions report
```

## How to Classify a Puzzle

The classification has different jobs. Do not treat every field as a puzzle
type or as a generator strategy.

| Field | Meaning | How it should be used later |
|---|---|---|
| `puzzle_family` | The operation the solver must perform | The primary generator key |
| `primary_domain` | Broad subject area | A content constraint or filter |
| `subdomain` | Specific subject under the primary domain | A finer content constraint |
| `mechanics` | Observable operations used by the puzzle | Optional generation parameters |
| `skills` | Cognitive abilities required to solve it | Descriptive metadata |
| `secondary_domains` | Genuine cross-domain relationships | Optional metadata only |
| `discovery_suggestions` | Proposed labels missing from the taxonomy | Human taxonomy review only |

### Recommended Decision Process

```text
What does the solver have to do?
        ↓
Choose one puzzle_family
        ↓
What subject does it use?
        ↓
Choose primary_domain + matching subdomain
        ↓
What solving abilities are required?
        ↓
Add skills as optional tags
        ↓
Does an approved label genuinely not fit?
        ↓
Add a taxonomy suggestion for human review
```

`puzzle_family` is the generator-facing classification key. A future
generator should dispatch on `classification.puzzle_family.id`, then use the
domain, subdomain, and mechanics as constraints. It should not need to read
every skill or discovery suggestion to decide what kind of puzzle to create.

### Approved Puzzle Families

| Family | Use when the puzzle asks the solver to… |
|---|---|
| `sequence_completion` | Complete a numerical or symbolic sequence |
| `arrangement` | Order or arrange items under constraints |
| `assignment` | Match entities to properties or slots |
| `path_finding` | Find a route through a graph or grid |
| `transformation` | Apply or identify a visual transformation |
| `spatial_matching` | Match shapes, positions, or spatial relationships |
| `word_manipulation` | Transform or rearrange words |
| `code_execution` | Trace or predict program behavior |

Examples:

```text
sequence_completion
  domain: math
  subdomain: sequences
  skills: pattern_recognition, numerical_reasoning

path_finding
  domain: graph_theory
  subdomain: shortest_path
  skills: spatial_reasoning, algorithmic_thinking

assignment
  domain: logic
  subdomain: assignment
  skills: logical_reasoning
```

Use `unknown` when the screenshot does not provide enough evidence. Use
`out_of_taxonomy` only when the puzzle clearly needs a new label. New domains,
subdomains, families, and skills belong in the matching
`discovery_suggestions` list; they are not approved classification labels.

### Taxonomy Suggestions

The canonical standalone report is:

```text
classified_puzzles/reports/taxonomy_suggestions.json
```

It is deduplicated and contains only suggestions that are not already in the
approved taxonomy. Each candidate includes its category, proposed ID, parent
domain when relevant, occurrence count, affected puzzle IDs, and evidence.

Genuine model suggestions remain inside each canonical record under
`classification.discovery_suggestions` for provenance. Suggestions that merely
repeat an approved label are removed before the record is written. The
pipeline no longer creates a separate `discovery_suggestions.jsonl` file.

### Output Responsibilities

```text
records/   = canonical per-puzzle classifications
staging/   = convenient views grouped by family, domain, or skill
reports/   = summaries and the single taxonomy_suggestions.json report
review/    = records requiring human action
```

### Review Queue & Rejection Analysis (Example: `unnamed.png`)

When a puzzle is evaluated, it goes through automated taxonomy validation before entering `staging/`. If it violates taxonomy hierarchy or validation rules, it is routed to `review/` rather than silently polluting production datasets.

For example, in [`classified_puzzles/review/rejected/unnamed.json`](classified_puzzles/review/rejected/unnamed.json):

```json
{
  "classification": {
    "puzzle_family": { "id": "sequence_completion", "confidence": 0.95 },
    "primary_domain": { "id": "math", "confidence": 0.95 },
    "subdomain": { "id": "arithmetic", "confidence": 0.95 },
    "secondary_domains": [
      { "id": "number_theory", "confidence": 0.7 },
      { "id": "sequences", "confidence": 0.8 }
    ],
    "skills": [
      { "id": "pattern_recognition", "confidence": 0.9 },
      { "id": "numerical_reasoning", "confidence": 0.9 }
    ]
  },
  "review_status": "rejected",
  "review_reason": "Unknown secondary domain: 'number_theory'; Unknown secondary domain: 'sequences'"
}
```

#### Why Is This Puzzle Considered Rejected?

1. **Taxonomy Hierarchy**:
   The taxonomy defines 8 approved canonical domains: `math`, `logic`, `graph_theory`, `geometry`, `probability`, `algorithms`, `programming`, and `word_puzzles`. Both `number_theory` and `sequences` are **subdomains** under `math`, not top-level domains.

2. **Hierarchy Misplacement by Model**:
   The VLM correctly recognized the arithmetic grid as `primary_domain: "math"` and `subdomain: "arithmetic"`, but it placed two math subdomains (`number_theory` and `sequences`) into `secondary_domains`. The schema requires `secondary_domains` to only contain approved top-level domain IDs (such as `geometry` or `logic`).

3. **Strict Validation Gate**:
   [`pikpok/taxonomy/validator.py`](pikpok/taxonomy/validator.py) checks every assigned ID against the approved taxonomy. Because `number_theory` and `sequences` are not registered top-level domains, the validator produced two errors:
   - `Unknown secondary domain: 'number_theory'`
   - `Unknown secondary domain: 'sequences'`

4. **Safety Action**:
   Because of these validation errors, [`route_review.py`](pikpok/pipeline/route_review.py) flagged the record with `review_status: "rejected"` and created a link in `classified_puzzles/review/rejected/` for human review or correction. This ensures that invalid taxonomy IDs are never silently accepted as approved ground truth.

For the complete approved taxonomy, see
`pikpok/taxonomy/taxonomy.yaml`.

## Architecture

```
Puzzle Screenshot
    ↓
Image Ingestion & Hashing
    ↓
VLM Pass 1: Puzzle Understanding
    ↓
VLM Pass 2: Taxonomy Classification
    ↓
Schema + Taxonomy Validation
    ↓
Confidence-Based Review Routing
    ↓
Immutable JSON Record + Staging Views
```

## Taxonomy

The taxonomy (v0.1.0) defines:
- **8 domains**: math, logic, graph_theory, geometry, probability, algorithms, programming, word_puzzles
- **12 skills**: pattern_recognition, logical_reasoning, spatial_reasoning, etc.
- **8 puzzle families**: sequence_completion, path_finding, transformation, etc.

See `pikpok/taxonomy/taxonomy.yaml` for the full definition.
