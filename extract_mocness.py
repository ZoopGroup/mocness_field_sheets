import os
import json
import asyncio
import time
from pathlib import Path
import re
import base64
from dotenv import load_dotenv

# NEW: optional S3 support
from typing import List
try:
    import s3fs
    _fs = s3fs.S3FileSystem(anon=False)
except Exception:
    _fs = None

# OpenAI client (unchanged behavior)
from openai import OpenAI

# Load environment variables from .env file (if present)
load_dotenv()

# ---------- S3/Local helpers ----------
def _is_s3(path: str) -> bool:
    return isinstance(path, str) and path.startswith("s3://")

def _normalize_path(path: str) -> str:
    """Expand ~ and environment variables for local paths only."""
    if _is_s3(path):
        return path
    return os.path.expandvars(os.path.expanduser(path))

def _require_s3fs():
    if _fs is None:
        raise RuntimeError("s3fs is required to use s3:// paths. Install with: pip install s3fs boto3")

def ls_dir(path: str) -> List[str]:
    """
    List *immediate children* (non-recursive) under a directory/prefix.
    Returns names relative to `path` (no leading slash).
    """
    if _is_s3(path):
        _require_s3fs()
        # s3fs.ls accepts 's3://bucket/prefix/' but returns 'bucket/prefix/child'
        prefix_with_scheme = path.rstrip("/") + "/"
        prefix_no_scheme = prefix_with_scheme.replace("s3://", "")
        items = _fs.ls(prefix_with_scheme)
        out = []
        for p in items:
            # Only trim items that belong to this exact prefix
            if p.startswith(prefix_no_scheme):
                rel = p[len(prefix_no_scheme):]
                if rel and "/" not in rel:  # non-recursive: keep only top-level children
                    out.append(rel)
        return out
    else:
        # Local, non-recursive top-level file names
        return [name for name in os.listdir(path) if os.path.isfile(os.path.join(path, name))]

def exists(path: str) -> bool:
    if _is_s3(path):
        _require_s3fs()
        return _fs.exists(path)
    return os.path.exists(path)

def read_bytes(path: str) -> bytes:
    if _is_s3(path):
        _require_s3fs()
        with _fs.open(path, "rb") as f:
            return f.read()
    with open(path, "rb") as f:
        return f.read()

def makedirs(path: str):
    if _is_s3(path):
        # S3 is key-based; no-op for "directories"
        return
    Path(path).mkdir(parents=True, exist_ok=True)

def write_text(path: str, text: str):
    if _is_s3(path):
        _require_s3fs()
        with _fs.open(path, "w") as f:
            f.write(text)
        return
    Path(os.path.dirname(path) or ".").mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(text)

def encode_image_any(path: str) -> str:
    """Encode an image (local or S3) to base64 string for model input."""
    return base64.b64encode(read_bytes(path)).decode("utf-8")

def _mime_for_ext(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    # default png
    return "image/png"

# ---------- Core extractor (importable) ----------
ALLOWED_EXTS = ("png", "jpg", "jpeg")  # case-insensitive

async def run_extractor(
    input_dir: str,
    output_dir: str,
    model: str = "gpt-5.3",
    api_key: str | None = None,
    prompt_path: str = "prompts/extract.json",
    delay_after_call: float = 1.0,
):
    """
    Read tow_*_form.(png|jpg|jpeg) + optional *_notes.* from input_dir (local or S3; non-recursive),
    call the model, and write tow_###.json (or .txt) to output_dir.
    """
    openai_api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY environment variable is required")

    input_dir = _normalize_path(input_dir)
    output_dir = _normalize_path(output_dir)

    client = OpenAI(api_key=openai_api_key)

    # Load prompt (still local file path; easy to S3-ify later if needed)
    with open(prompt_path, "r") as f:
        prompt = f.read()

    makedirs(output_dir)
    files = ls_dir(input_dir)

    # Case-insensitive match for forms at top level, allow multiple extensions
    form_re = re.compile(r"^tow_(\d+)_form\.(png|jpg|jpeg)$", re.IGNORECASE)

    form_entries = []
    for name in files:
        m = form_re.match(name)
        if m:
            tow_id = m.group(1)
            form_ext = m.group(2)  # actual extension found
            form_entries.append((tow_id, name, form_ext))

    print(f"Found {len(form_entries)} form images")

    for tow_id, form_name, form_ext in sorted(form_entries, key=lambda t: int(t[0])):
        form_path = f"{input_dir.rstrip('/')}/{form_name}"

        # Notes may share extension or be a different allowed one; look for any that exists
        base_notes = re.sub(r"(?i)_form\.(png|jpg|jpeg)$", "_notes", form_name)
        notes_name = None
        # Prefer same ext as form first, then others
        try_exts = [form_ext] + [e for e in ALLOWED_EXTS if e.lower() != form_ext.lower()]
        for ext in try_exts:
            candidate = f"{base_notes}.{ext}"
            candidate_path = f"{input_dir.rstrip('/')}/{candidate}"
            if exists(candidate_path):
                notes_name = candidate
                break

        notes_path = f"{input_dir.rstrip('/')}/{notes_name}" if notes_name else None
        out_json = f"{output_dir.rstrip('/')}/tow_{tow_id}.json"

        if not exists(form_path):
            print(f"⚠️  Form file not found for tow {tow_id}: {form_name}")
            continue

        # Build messages with correct MIME types per file
        form_mime = _mime_for_ext(form_ext)
        user_content = [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": f"data:{form_mime};base64,{encode_image_any(form_path)}"}},
        ]

        if notes_path:
            # get ext from filename
            notes_ext = notes_path.rsplit(".", 1)[-1]
            notes_mime = _mime_for_ext(notes_ext)
            user_content.append(
                {"type": "image_url",
                 "image_url": {"url": f"data:{notes_mime};base64,{encode_image_any(notes_path)}"}}
            )

        messages = [
            {"role": "system", "content": "You are a document parser for MOCNESS oceanographic tows."},
            {"role": "user", "content": user_content},
        ]

        try:
            resp = client.chat.completions.create(
                model=model, temperature=0, messages=messages, max_tokens=4000
            )
            if delay_after_call:
                await asyncio.sleep(delay_after_call)

            result_text = (resp.choices[0].message.content or "").strip()

            # If it's valid JSON, pretty-write; else dump as .txt
            try:
                parsed = json.loads(result_text)
                write_text(out_json, json.dumps(parsed, indent=2))
            except json.JSONDecodeError:
                write_text(out_json.replace(".json", ".txt"), result_text)

            print(f"✅ Processed tow {tow_id}")

        except Exception as e:
            print(f"❌ Error processing tow {tow_id}: {e}")

# ---------- Backwards-compatible CLI entrypoint ----------
async def _main_from_env():
    input_dir = os.getenv("INPUT_DIR", "input")
    output_dir = os.getenv("OUTPUT_DIR", "output")
    model = os.getenv("MODEL", "gpt-5.3")
    await run_extractor(input_dir=input_dir, output_dir=output_dir, model=model)

if __name__ == "__main__":
    asyncio.run(_main_from_env())

# --- Backwards compatibility alias for main.py ---
# Allows: from extract_mocness import main
main = _main_from_env

