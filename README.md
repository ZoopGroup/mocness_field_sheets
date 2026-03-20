# MOCNESS Field Sheet Extractor

Extract structured tow metadata from scanned MOCNESS field sheets.

This project reads tow form images, sends them to an OpenAI vision model, and writes one output file per tow:
- valid JSON -> `tow_<id>.json`
- non-JSON fallback -> `tow_<id>.txt`

## What Inputs Are Expected

Yes, your understanding is correct.

For this dataset, the tool can run with only per-tow form images:
- required: `tow_<id>_form.png` (or `.jpg` / `.jpeg`)
- optional: `tow_<id>_notes.png` (or `.jpg` / `.jpeg`)

If there are no separate notes pages, that is fine. The extractor will process only the form image for each tow.

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
MODEL=gpt-5.3
```

## Run Extraction

Python entrypoint:

```bash
source .venv/bin/activate
python main.py
```

Run-time overrides (without editing `.env`):

```bash
python main.py --model gpt-5.3 --api-key "$OPENAI_API_KEY"
python main.py --input-dir /path/to/input --output-dir /path/to/output
```

Optional TypeScript entrypoint:

```bash
uv run extract-mocness.ts
```

Both runners support model override via `MODEL` (default `gpt-5.3`).

## Convert Single PDF -> Individual PNGs

Assume your source file is named `field_sheets.pdf` and each page is one tow form.

### Option A: `pdftoppm` (recommended)

Install (Ubuntu/Debian):

```bash
sudo apt-get update && sudo apt-get install -y poppler-utils
```

Convert pages to PNG (300 DPI):

```bash
mkdir -p input
pdftoppm -png -r 300 field_sheets.pdf input/page
```

This creates files like `input/page-1.png`, `input/page-2.png`, etc.

Rename into tow format (example: page 1 -> tow_0, page 2 -> tow_1):

```bash
n=0
for f in $(ls input/page-*.png | sort -V); do
  mv "$f" "input/tow_${n}_form.png"
  n=$((n+1))
done
```

### Option B: ImageMagick

Install:

```bash
sudo apt-get update && sudo apt-get install -y imagemagick
```

Convert:

```bash
mkdir -p input
magick -density 300 field_sheets.pdf input/page-%d.png
```

Then apply the same rename loop above.

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
- model returned non-JSON; inspect file and refine prompt in `prompts/extract.json`
