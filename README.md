# MOCNESS Field Sheet Extractor

Extract structured tow metadata from scanned MOCNESS field sheets.

This project reads tow form images, sends them to an OpenAI vision model, then
normalizes output into a fixed canonical schema.

One output file is written per tow:
- valid JSON -> `tow_<id>.json`
- non-JSON fallback -> `tow_<id>.txt`

Canonical schema:
- `schemas/mocness_tow.schema.json`

## What Inputs Are Expected

For this dataset, the tool can run with only per-tow form images:
- required: `tow_<id>_form.png` (or `.jpg` / `.jpeg`)
- optional: `tow_<id>_notes.png` (or `.jpg` / `.jpeg`)

If there are no separate notes pages, that is fine. The extractor will process
only the form image for each tow.

Important behavior:
- input scan is non-recursive (files must be directly inside `INPUT_DIR`)
- file names are matched case-insensitively

## Quick Primer (Start Here)

1. Set up Python environment and dependencies.
2. Convert your single PDF into one PNG per tow page.
3. Rename each page to `tow_<id>_form.png`.
4. Configure `.env`.
5. Run extractor.
6. Review output JSON/TXT files.

## Setup

Requirements:
- Python 3.12+
- `uv`

Create env and install packages:

```bash
uv venv
source .venv/bin/activate
uv sync
```

If you prefer explicit install:

```bash
uv pip install openai python-dotenv s3fs boto3
```

## Configure Environment

Copy template and edit values:

```bash
cp .env.example .env
```

Minimum `.env` values:

```bash
OPENAI_API_KEY=sk-...
INPUT_DIR=input
OUTPUT_DIR=output
MODEL=gpt-4.1
```

## Run Extraction

If you already activated `.venv` during setup, you can run directly:

Python entrypoint:

```bash
python main.py
```

If your shell is not currently in the virtual environment, run:

```bash
source .venv/bin/activate
python main.py
```

Run-time overrides (without editing `.env`):

```bash
python main.py --model gpt-4.1 --api-key "$OPENAI_API_KEY"
python main.py --input-dir /path/to/input --output-dir /path/to/output
python main.py --input-dir hypoxia25 --output-dir output/hypoxia25b --tow-ids 11
```

### Extract A Single Tow

Use `--tow-ids` to process only specific tow IDs from the input directory.

Example (Tow 11 only):

```bash
uv run main.py --input-dir hypoxia25 --output-dir output/hypoxia25b --tow-ids 11
```

Example (multiple specific tows):

```bash
uv run main.py --input-dir hypoxia25 --output-dir output/hypoxia25b --tow-ids 8 11 14
```

This scans all files in `--input-dir`, but only runs extraction for the specified
tow IDs. Outputs are written to `--output-dir` as `tow_<id>.json` (or `.txt`
fallback if JSON parsing fails after one automatic retry).

Recommended uv command:

```bash
uv run main.py
```

Model override is supported via `MODEL` (default `gpt-4.1`).

## Validate Output JSON

Install or update dependencies first:

```bash
uv sync
```

Validate extracted outputs against the canonical schema:

```bash
uv run validate_outputs.py --dir output
```

## Golden Example Workflow

After generating initial outputs, seed candidate golden examples:

```bash
uv run seed_golden_examples.py --source-dir output --target-dir examples/golden --tow-ids 2 10 13 14 16
```

Then manually review and correct those files in `examples/golden`.

## Re-Run Golden Calibration (Investigator Workflow)

Use this when another investigator wants to re-run calibration on a shared tow
set and compare with canonical goldens.

Note on extraction accuracy:
- calibration reruns primarily compare outputs across runs/timepoints
- extraction accuracy improvements currently live in the extractor/prompt pipeline:
  - `extract_mocness.py` normalization and deterministic coercion logic
  - `prompts/extract.json` extraction instructions and ambiguity handling rules
  - `schemas/mocness_tow.schema.json` structural constraints validated post-extraction

Run end-to-end calibration:

```bash
uv run rerun_golden_calibration.py \
  --input-dir hypoxia25 \
  --tow-ids 2 10 13 14 16 \
  --run-label investigator_ab \
  --output-dir output/calibration
```

Run calibration on all tows currently present in the output directory:

```bash
uv run rerun_golden_calibration.py \
  --input-dir hypoxia25 \
  --tow-ids all \
  --run-label investigator_ab_all \
  --output-dir output/calibration \
  --skip-extract
```

Run calibration on all tows and diff non-golden tows against a fallback
reference directory:

```bash
uv run rerun_golden_calibration.py \
  --input-dir hypoxia25 \
  --tow-ids all \
  --run-label investigator_ab_all \
  --output-dir output/calibration \
  --skip-extract \
  --fallback-reference-dir output/hypoxia25
```

What this does:
- runs extraction for the selected tow set
- validates outputs against `schemas/mocness_tow.schema.json`
- writes candidate files to `/tmp/mocness_field_sheets/golden_candidates/<run_label>_<timestamp>/` by default
- writes a diff report to `/tmp/mocness_field_sheets/reports/calibration/<run_label>_<timestamp>.md` by default
- for tows without canonical goldens, can optionally diff against `--fallback-reference-dir`

Optional overrides for persistent storage:
- `--candidate-root-dir examples/golden_candidates`
- `--report-root-dir reports/calibration`

If extraction already exists and you only want validate/copy/diff:

```bash
uv run rerun_golden_calibration.py \
  --input-dir hypoxia25 \
  --tow-ids 2 10 13 14 16 \
  --run-label investigator_ab \
  --output-dir output/calibration \
  --skip-extract
```

## Field Dictionary Starter

Use this starter to evolve label/synonym mapping as new form variants appear:

- `docs/field_dictionary.md`

## Convert Single PDF -> Individual PNGs

Assume your source file is named `field_sheets.pdf` and each page is one tow
form.

### `pdftoppm`

Install (Ubuntu/Debian):

```bash
sudo apt-get update && sudo apt-get install -y poppler-utils
```

Convert pages to PNG (300 DPI):

```bash
pdftoppm -png -r 300 field_sheets.pdf page
```

This creates files like `page-1.png`, `page-2.png`, etc.

Rename into tow format sensu:
> `page-1.png` -> `tow_0_form.png`
> `page-2.png` -> `tow_0_notes.png`


```bash
n=0
for f in $(ls input/page-*.png | sort -V); do
  mv "$f" "input/tow_${n}_form.png"
  n=$((n+1))
done
```

## File Naming Rules

Required form page per tow:
- `tow_0_form.png`
- `tow_1_form.png`
- `tow_2_form.png`

Optional notes page per tow:
- `tow_0_notes.png`
- `tow_1_notes.png`

Notes can be omitted entirely.

## Output

Output directory receives one file per tow:
- `tow_<id>.json` when parse is valid JSON
- `tow_<id>.txt` when model output is not valid JSON

## Troubleshooting

`Found 0 form images`:
- verify files are directly in `INPUT_DIR`
- verify names match `tow_<id>_form.(png|jpg|jpeg)`

S3 path errors:
- install `s3fs` + `boto3`
- verify AWS credentials/role

Unexpected `.txt` output:
- model returned non-JSON; inspect file and refine prompt in
  `prompts/extract.json`