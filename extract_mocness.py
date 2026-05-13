import os
import json
import asyncio
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

CANONICAL_HEADER_KEYS = [
    "cruise",
    "tow_moc_number",
    "file_name",
    "date",
    "local_date",
    "gmt_date",
    "date_unresolved",
    "date_unresolved_reason",
    "location",
    "day_night",
    "direction",
    "sea_state",
    "wind_speed",
    "local_time_from",
    "local_time_to",
    "gmt_time_from",
    "gmt_time_to",
    "net_condition",
    "net_mesh",
    "net_size",
    "net_type",
    "sog",
    "operator",
    "start_lat",
    "start_long",
    "end_lat",
    "end_long",
]

CANONICAL_NET_KEYS = [
    "net_number",
    "time_open_local",
    "time_close_local",
    "time_close_gmt",
    "target_depth_m",
    "depth_max_m",
    "depth_min_m",
    "depth_m",
    "lat",
    "lon",
    "angle",
    "flow_counts",
    "volume_filtered",
    "mwo_net",
    "winch_speed",
    "notes_table",
    "notes_notes_page",
    "notes",
]


def _clean_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _to_hhmm(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    m = re.match(r"^(\d{1,2}):(\d{1,2})(?::\d{1,2})?$", s)
    if m:
        h, mm = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mm <= 59:
            return f"{h:02d}:{mm:02d}"

    m = re.match(r"^(\d{1,2})(\d{2})$", s)
    if m:
        h, mm = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mm <= 59:
            return f"{h:02d}:{mm:02d}"

    return None


def _extract_numeric(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _count_time_tokens(value) -> int:
    if value is None:
        return 0
    s = str(value).strip()
    if not s:
        return 0
    return len(re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", s))


def _coerce_null(value):
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "null", "none", "na", "n/a", "unreadable"}:
        return None
    return value


def _pick_first(source: dict, candidates: list[str]):
    for key in candidates:
        if key in source:
            v = _coerce_null(source.get(key))
            if v is not None:
                return v
    return None


def _normalize_header(raw_header: dict):
    hk = {_clean_key(k): v for k, v in (raw_header or {}).items()}

    start_latlong = _pick_first(hk, ["start_lat_long", "start_latlong"])
    end_latlong = _pick_first(hk, ["end_lat_long", "end_latlong"])

    start_lat = _pick_first(hk, ["start_lat", "lat_start", "startlatitude"])
    start_long = _pick_first(hk, ["start_long", "start_lon", "lon_start", "long_start", "startlongitude"])
    end_lat = _pick_first(hk, ["end_lat", "lat_end", "endlatitude"])
    end_long = _pick_first(hk, ["end_long", "end_lon", "lon_end", "long_end", "endlongitude"])

    if (start_lat is None or start_long is None) and isinstance(start_latlong, str):
        parts = [p.strip() for p in re.split(r"[,;]", start_latlong) if p.strip()]
        if len(parts) >= 2:
            start_lat = start_lat or parts[0]
            start_long = start_long or parts[1]

    if (end_lat is None or end_long is None) and isinstance(end_latlong, str):
        parts = [p.strip() for p in re.split(r"[,;]", end_latlong) if p.strip()]
        if len(parts) >= 2:
            end_lat = end_lat or parts[0]
            end_long = end_long or parts[1]

    local_date = _coerce_null(_pick_first(hk, ["local_date", "date_local"]))
    gmt_date = _coerce_null(_pick_first(hk, ["gmt_date", "date_gmt"]))
    plain_date = _coerce_null(_pick_first(hk, ["date"]))

    # Resolve canonical date from local_date / gmt_date / plain date
    resolved_date = plain_date
    date_unresolved = _pick_first(hk, ["date_unresolved"])
    date_unresolved_reason = _coerce_null(_pick_first(hk, ["date_unresolved_reason", "date_flag", "date_notes"]))

    if local_date is not None or gmt_date is not None:
        if local_date is not None and gmt_date is not None:
            if str(local_date).strip() == str(gmt_date).strip():
                resolved_date = resolved_date or local_date
            else:
                # Conflicting dates: preserve both, do not pick one
                resolved_date = None
                date_unresolved = True
                if date_unresolved_reason is None:
                    date_unresolved_reason = (
                        f"Conflicting local date '{local_date}' and GMT date '{gmt_date}'; "
                        "unable to determine canonical date without additional context."
                    )
        else:
            resolved_date = resolved_date or local_date or gmt_date

    normalized = {
        "cruise": _pick_first(hk, ["cruise"]),
        "tow_moc_number": _pick_first(hk, ["tow_moc_number", "tow_moc", "tow_moc_num", "tow_moc_", "tow_mocno", "tow_moc_number_"]),
        "file_name": _pick_first(hk, ["file_name", "filename"]),
        "date": resolved_date,
        "local_date": local_date,
        "gmt_date": gmt_date,
        "date_unresolved": date_unresolved,
        "date_unresolved_reason": date_unresolved_reason,
        "location": _pick_first(hk, ["location"]),
        "day_night": _pick_first(hk, ["day_night", "d_n", "dn"]),
        "direction": _pick_first(hk, ["direction"]),
        "sea_state": _pick_first(hk, ["sea_state"]),
        "wind_speed": _pick_first(hk, ["wind_speed"]),
        "local_time_from": _to_hhmm(_pick_first(hk, ["local_time_from", "local_from"])),
        "local_time_to": _to_hhmm(_pick_first(hk, ["local_time_to", "local_to"])),
        "gmt_time_from": _to_hhmm(_pick_first(hk, ["gmt_time_from", "gmt_from"])),
        "gmt_time_to": _to_hhmm(_pick_first(hk, ["gmt_time_to", "gmt_to"])),
        "net_condition": _pick_first(hk, ["net_condition"]),
        "net_mesh": _pick_first(hk, ["net_mesh"]),
        "net_size": _pick_first(hk, ["net_size"]),
        "net_type": _pick_first(hk, ["net_type", "type"]),
        "sog": _pick_first(hk, ["sog"]),
        "operator": _pick_first(hk, ["operator"]),
        "start_lat": _coerce_null(start_lat),
        "start_long": _coerce_null(start_long),
        "end_lat": _coerce_null(end_lat),
        "end_long": _coerce_null(end_long),
    }

    for key in CANONICAL_HEADER_KEYS:
        normalized.setdefault(key, None)

    if normalized["date"] is None and normalized["date_unresolved"] is None:
        normalized["date_unresolved"] = True
        if normalized["date_unresolved_reason"] is None:
            normalized["date_unresolved_reason"] = "missing_or_unreadable"

    # Ensure boolean type where the model returned a string
    du = normalized["date_unresolved"]
    if isinstance(du, str):
        normalized["date_unresolved"] = du.strip().lower() not in {"false", "0", ""}

    return normalized


def _normalize_net_row(row: dict):
    rk = {_clean_key(k): v for k, v in (row or {}).items()}

    net_number = _pick_first(rk, ["net_number", "net", "net_no", "net_num"])
    if net_number is not None:
        net_number = str(net_number).strip()
        if not re.match(r"^\d+$", net_number):
            m = re.search(r"(\d+)", net_number)
            net_number = m.group(1) if m else None

    notes_table = _pick_first(rk, ["notes_table", "notes", "table_notes"])
    notes_notes_page = _pick_first(rk, ["notes_notes_page", "notes_page", "notes_from_notes_page"])

    # Preserve duplicates exactly as requested.
    if notes_table and notes_notes_page:
        merged_notes = f"{notes_table}; {notes_notes_page}"
    else:
        merged_notes = notes_table if notes_table is not None else notes_notes_page

    raw_time_open = _pick_first(rk, ["time_open_local", "time_open", "time_local_open"])
    raw_time_close_local = _pick_first(rk, ["time_close_local", "time_local", "time_close"])
    raw_time_close_gmt = _pick_first(rk, ["time_close_gmt", "time_gmt"])

    # Some forms include two stacked times per cell (often local+GMT) with no explicit row labels.
    # In that case, avoid guessing and null row-level times.
    dual_time_ambiguous = (
        _count_time_tokens(raw_time_open) >= 2
        or _count_time_tokens(raw_time_close_local) >= 2
        or _count_time_tokens(raw_time_close_gmt) >= 2
    )

    normalized = {
        "net_number": _coerce_null(net_number),
        "time_open_local": None if dual_time_ambiguous else _to_hhmm(raw_time_open),
        "time_close_local": None if dual_time_ambiguous else _to_hhmm(raw_time_close_local),
        "time_close_gmt": None if dual_time_ambiguous else _to_hhmm(raw_time_close_gmt),
        "target_depth_m": _pick_first(rk, ["target_depth_m", "target_depth"]),
        "depth_max_m": _pick_first(rk, ["depth_max_m", "depth_max", "depthmax_m", "depth_max_m_"]),
        "depth_min_m": _pick_first(rk, ["depth_min_m", "depth_min", "depthmin_m", "depth_min_m_"]),
        "depth_m": _pick_first(rk, ["depth_m", "depth"]),
        "lat": _pick_first(rk, ["lat"]),
        "lon": _pick_first(rk, ["lon", "long"]),
        "angle": _pick_first(rk, ["angle"]),
        "flow_counts": _pick_first(rk, ["flow_counts", "flow_count"]),
        "volume_filtered": _pick_first(rk, ["volume_filtered"]),
        "mwo_net": _pick_first(rk, ["mwo_net"]),
        "winch_speed": _pick_first(rk, ["winch_speed"]),
        "notes_table": _coerce_null(notes_table),
        "notes_notes_page": _coerce_null(notes_notes_page),
        "notes": _coerce_null(merged_notes),
    }

    for key in CANONICAL_NET_KEYS:
        normalized.setdefault(key, None)

    if dual_time_ambiguous:
        normalized["_dual_time_ambiguous"] = True

    return normalized


def _normalize_result(raw: dict, tow_id: str):
    if not isinstance(raw, dict):
        return {
            "schema_version": "2.0",
            "tow_id": str(tow_id),
            "header": {k: None for k in CANONICAL_HEADER_KEYS},
            "form_comments": None,
            "net_tows": [],
            "quality": {
                "field_confidence": {},
                "uncertain_fields": ["root"],
                "notes": ["model_output_not_object"],
            },
        }

    root = {_clean_key(k): v for k, v in raw.items()}
    header = _normalize_header(root.get("header") if isinstance(root.get("header"), dict) else root)

    net_rows = root.get("net_tows")
    if not isinstance(net_rows, list):
        net_rows = root.get("net_rows") if isinstance(root.get("net_rows"), list) else []

    normalized_rows = [_normalize_net_row(row) for row in net_rows if isinstance(row, dict)]
    # Keep all rows unless net number is missing.
    normalized_rows = [row for row in normalized_rows if row.get("net_number") is not None]

    quality = root.get("quality") if isinstance(root.get("quality"), dict) else {}
    raw_field_confidence = quality.get("field_confidence") if isinstance(quality.get("field_confidence"), dict) else {}
    field_confidence = {}
    for key, value in raw_field_confidence.items():
        if isinstance(value, (int, float)) and 0 <= value <= 1:
            field_confidence[str(key)] = float(value)
    uncertain_fields = quality.get("uncertain_fields") if isinstance(quality.get("uncertain_fields"), list) else []
    notes = quality.get("notes") if isinstance(quality.get("notes"), list) else []

    # If depth_m is outside the [depth_min_m, depth_max_m] interval in multiple rows,
    # this usually indicates a form variant where only depth min/max exists and depth_m
    # was incorrectly inferred from another column.
    rows_with_depth_range = 0
    rows_depth_m_outside_range = 0
    for row in normalized_rows:
        depth_m = _extract_numeric(row.get("depth_m"))
        depth_min = _extract_numeric(row.get("depth_min_m"))
        depth_max = _extract_numeric(row.get("depth_max_m"))
        if depth_m is None or depth_min is None or depth_max is None:
            continue
        rows_with_depth_range += 1
        lo = min(depth_min, depth_max)
        hi = max(depth_min, depth_max)
        if not (lo <= depth_m <= hi):
            rows_depth_m_outside_range += 1

    null_all_depth_m = (
        rows_with_depth_range >= 3
        and rows_depth_m_outside_range / rows_with_depth_range >= 0.6
    )

    if null_all_depth_m:
        for row in normalized_rows:
            if row.get("depth_m") is not None:
                row["depth_m"] = None
        uncertain_fields.append("net_tows[*].depth_m")
        notes.append(
            "Detected form variant without reliable Depth (m) column; depth_m was nulled to avoid cross-column misread."
        )

    if any(row.get("_dual_time_ambiguous") for row in normalized_rows):
        uncertain_fields.extend([
            "net_tows[*].time_open_local",
            "net_tows[*].time_close_local",
            "net_tows[*].time_close_gmt",
        ])
        notes.append(
            "Detected rows with multiple time values in a single time cell; row-level times were nulled as ambiguous."
        )

    for row in normalized_rows:
        row.pop("_dual_time_ambiguous", None)

    # keep quality lists de-duplicated while preserving order
    uncertain_fields = list(dict.fromkeys(str(x) for x in uncertain_fields))
    notes = list(dict.fromkeys(str(x) for x in notes))

    return {
        "schema_version": "2.0",
        "tow_id": str(root.get("tow_id") or tow_id),
        "header": header,
        "form_comments": _coerce_null(_pick_first(root, ["form_comments", "comments"])),
        "net_tows": normalized_rows,
        "quality": {
            "field_confidence": field_confidence,
            "uncertain_fields": uncertain_fields,
            "notes": notes,
        },
    }

async def run_extractor(
    input_dir: str,
    output_dir: str,
    model: str = "gpt-4.1",
    api_key: str | None = None,
    tow_ids: list[str] | None = None,
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

    if tow_ids:
        allowed = {str(int(t)) for t in tow_ids}
        form_entries = [entry for entry in form_entries if str(int(entry[0])) in allowed]

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
            parsed = None
            result_text = ""
            json_error = None

            # Retry once on malformed JSON output.
            for attempt in (1, 2):
                retry_hint = ""
                if attempt == 2:
                    retry_hint = (
                        "\n\nIMPORTANT: Your previous response was truncated or malformed JSON. "
                        "Return COMPLETE JSON only, with all brackets and quotes closed."
                    )

                call_messages = messages
                if retry_hint:
                    call_messages = [
                        {"role": "system", "content": "You are a document parser for MOCNESS oceanographic tows."},
                        {"role": "user", "content": user_content + [{"type": "text", "text": retry_hint}]},
                    ]

                resp = client.chat.completions.create(
                    model=model,
                    temperature=0,
                    messages=call_messages,
                    max_tokens=6000 if attempt == 2 else 4000,
                    response_format={"type": "json_object"},
                )
                if delay_after_call:
                    await asyncio.sleep(delay_after_call)

                result_text = (resp.choices[0].message.content or "").strip()

                try:
                    parsed = json.loads(result_text)
                    json_error = None
                    break
                except json.JSONDecodeError as e:
                    json_error = e

            if parsed is not None:
                normalized = _normalize_result(parsed, tow_id=tow_id)
                write_text(out_json, json.dumps(normalized, indent=2))
                txt_fallback = out_json.replace(".json", ".txt")
                if os.path.exists(txt_fallback):
                    os.remove(txt_fallback)
            else:
                write_text(out_json.replace(".json", ".txt"), result_text)
                if json_error is not None:
                    print(f"⚠️  Tow {tow_id} saved as .txt after retry: {json_error}")

            print(f"✅ Processed tow {tow_id}")

        except Exception as e:
            print(f"❌ Error processing tow {tow_id}: {e}")

# ---------- Backwards-compatible CLI entrypoint ----------
async def _main_from_env():
    input_dir = os.getenv("INPUT_DIR", "input")
    output_dir = os.getenv("OUTPUT_DIR", "output")
    model = os.getenv("MODEL", "gpt-4.1")
    tow_ids_env = os.getenv("TOW_IDS")
    tow_ids = None
    if tow_ids_env:
        tow_ids = [tok.strip() for tok in tow_ids_env.split(",") if tok.strip()]
    await run_extractor(input_dir=input_dir, output_dir=output_dir, model=model, tow_ids=tow_ids)

if __name__ == "__main__":
    asyncio.run(_main_from_env())

# --- Backwards compatibility alias for main.py ---
# Allows: from extract_mocness import main
main = _main_from_env

