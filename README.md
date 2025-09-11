## MOCNESS Field Sheet Extractor

This repository contains Python code to **extract structured JSON data** from
scanned MOCNESS datasheet images (field sheets) using an LLM with vision
support (e.g. OpenAI `gpt-4o`).  

The extractor:
- Reads raw scan images (`tow_<id>_form.png` + optional `tow_<id>_notes.png`) from **local folders** or **S3 buckets**.  
- Calls the OpenAI Chat Completions API with a configurable prompt.  
- Produces structured `.json` (or `.txt` fallback if parsing fails) files, one per tow.  
- Can be run standalone or imported as a library.  
- Supports multiple image formats: `.png`, `.jpg`, `.jpeg` (case-insensitive).  
- Is designed as the first stage of a larger workflow to harvest oceanographic cruise data into a structured data lake.  

---

## Repository Layout

.
├── extract_mocness.py # Core extractor logic (S3 + local aware)
├── main.py # Simple entrypoint (runs extractor from env vars)
├── prompts/
│ └── extract.json # Prompt instructions for the model
├── .env.example # Example environment variables
└── README.md # This document


---

## Requirements

- Python 3.10+ (tested with 3.12)  
- [`uv`](https://github.com/astral-sh/uv) for virtual environment + dependency
management.  

---

## Setup with uv

Create and activate a project-local virtual environment:

```bash
# Create a venv managed by uv
uv venv

# Activate it
source .venv/bin/activate   # (Linux/macOS)
# .venv\Scripts\activate    # (Windows PowerShell)
```

Install dependencies into this venv:

```bash
uv pip install openai python-dotenv s3fs boto3
```

## Configuration

The extractor is controlled via environment variables. The easiest way is to put them in a .env file in the repo root (auto-loaded at runtime).
Required

    OPENAI_API_KEY – your OpenAI API key

    INPUT_DIR – local path or S3 prefix containing field sheet scans

    OUTPUT_DIR – local path or S3 prefix to write extracted JSON results

Optional

    MODEL – model name (default: gpt-4o)

    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION – only needed if you use s3://… paths.

Example .env

```bash

# OpenAI
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx

# Input / Output
INPUT_DIR=s3://gios-data/datasets/testing/maas_input/
OUTPUT_DIR=s3://gios-data/datasets/testing/maas_output/

# Optional model override
MODEL=gpt-4o

# AWS creds (omit if using local paths and AWS profile/role handles this)
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=xxxxxxxx
AWS_DEFAULT_REGION=us-west-2
```

File Naming Conventions

The extractor looks for files like:

    tow_<number>_form.png (required)

    tow_<number>_notes.png (optional)

Case-insensitive and supports .png, .jpg, .jpeg.

Examples:

```
tow_0_form.png
tow_0_notes.png
tow_1_form.JPG
```

Notes can use a different extension than the form.
Running the Extractor

Activate your venv if not already:

`source .venv/bin/activate`

Then run:
Local → Local

`python main.py`

S3 → S3

`python main.py`

(as long as .env contains the S3 INPUT_DIR and OUTPUT_DIR and AWS credentials)
Local → S3

INPUT_DIR=/path/to/scans OUTPUT_DIR=s3://bucket/output/ python main.py

S3 → Local

INPUT_DIR=s3://bucket/input/ OUTPUT_DIR=/tmp/output python main.py

## How It Works

    Discovery
    Scans INPUT_DIR (non-recursive) for files named tow_<id>_form.(png|jpg|jpeg).

    Prompting
    Loads prompts/extract.json and passes it along with the form (and optional notes) images as multimodal input to the LLM.

    Extraction
    Receives the model’s output.

        If valid JSON → writes as tow_<id>.json.

        If invalid JSON → writes raw response as tow_<id>.txt.

    Outputs
    Stored under OUTPUT_DIR (local path or S3 prefix).

## Library Usage

You can import and call the extractor from Python:

```py
import asyncio
from extract_mocness import run_extractor

asyncio.run(run_extractor(
    input_dir="s3://mybucket/cruise123/field_sheets",
    output_dir="s3://mybucket/cruise123/json",
    model="gpt-4o"
))
```

## Troubleshooting

- "Found 0 tows to process"
    + Ensure files are directly under INPUT_DIR (non-recursive).
    + Ensure names match tow_<id>_form.png pattern.
    + Use python check_s3_s3fs.py s3://bucket/prefix/ --list 20 to inspect.

- AssertionError: s3fs is required
    + Run `uv pip install s3fs boto3`.

- Invalid JSON output
    + The model sometimes produces non-JSON. The extractor saves it as .txt. Inspect manually and refine the prompt.

- Auth errors with S3
    + Check that your AWS credentials (env vars or IAM role) are valid.
