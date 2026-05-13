import argparse
import asyncio
import difflib
import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from extract_mocness import run_extractor


def _load_schema(schema_path: Path) -> Draft202012Validator:
    schema = json.loads(schema_path.read_text())
    return Draft202012Validator(schema)


def _validate_dir(validator: Draft202012Validator, data_dir: Path) -> list[str]:
    failures = []
    files = sorted(data_dir.glob("tow_*.json"))
    if not files:
        return [f"No JSON files found in {data_dir}"]

    for file in files:
        payload = json.loads(file.read_text())
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        if errors:
            failures.append(f"FAIL {file}")
            for err in errors:
                path = ".".join(str(p) for p in err.path) if err.path else "<root>"
                failures.append(f"  - {path}: {err.message}")
    return failures


def _copy_candidates(source_dir: Path, target_dir: Path, tow_ids: list[str]) -> tuple[list[Path], list[str]]:
    copied = []
    missing = []
    target_dir.mkdir(parents=True, exist_ok=True)

    for tow_id in tow_ids:
        src = source_dir / f"tow_{tow_id}.json"
        dst = target_dir / f"tow_{tow_id}.json"
        if not src.exists():
            missing.append(str(src))
            continue
        dst.write_text(src.read_text())
        copied.append(dst)

    return copied, missing


def _discover_tow_ids_from_output(output_dir: Path) -> list[str]:
    tow_ids = []
    for path in sorted(output_dir.glob("tow_*.json")):
        stem = path.stem
        try:
            tow_ids.append(str(int(stem.split("_", 1)[1])))
        except Exception:
            continue
    return tow_ids


def _generate_diff_report(
    copied_candidates: list[Path],
    canonical_golden_dir: Path,
    fallback_reference_dir: Path | None,
    report_path: Path,
) -> None:
    lines = [
        "# Golden Calibration Diff Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]

    for candidate in sorted(copied_candidates):
        lines.append(f"## {candidate.name}")

        canonical = canonical_golden_dir / candidate.name
        reference = canonical
        reference_label = "canonical golden"

        if not canonical.exists() and fallback_reference_dir is not None:
            fallback = fallback_reference_dir / candidate.name
            if fallback.exists():
                reference = fallback
                reference_label = "fallback reference"

        if not reference.exists():
            lines.append(f"- No reference file found in canonical or fallback dirs for {candidate.name}.")
            lines.append("")
            continue

        a = json.dumps(json.loads(reference.read_text()), indent=2, sort_keys=True).splitlines()
        b = json.dumps(json.loads(candidate.read_text()), indent=2, sort_keys=True).splitlines()

        diff = list(
            difflib.unified_diff(
                a,
                b,
                fromfile=str(reference),
                tofile=str(candidate),
                lineterm="",
            )
        )

        if not diff:
            lines.append(f"- No differences from {reference_label} file.")
            lines.append("")
            continue

        lines.append(f"- Compared against: {reference} ({reference_label})")

        lines.append("```diff")
        lines.extend(diff)
        lines.append("```")
        lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Re-run golden calibration for a set of tows: extract, validate, seed "
            "review candidates, and generate diffs against canonical goldens."
        )
    )
    parser.add_argument("--input-dir", required=True, help="Directory containing tow_<id>_form/notes images")
    parser.add_argument(
        "--tow-ids",
        nargs="+",
        required=True,
        help="Tow IDs to calibrate (e.g. 2 10 13 14 16), or use: all",
    )
    parser.add_argument("--run-label", required=True, help="Short label for this calibration run (e.g. investigator initials)")
    parser.add_argument("--output-dir", default="output/calibration", help="Where extracted JSON should be written")
    parser.add_argument("--canonical-golden-dir", default="examples/golden", help="Canonical golden directory")
    parser.add_argument(
        "--candidate-root-dir",
        default="/tmp/mocness_field_sheets/golden_candidates",
        help="Root directory for ephemeral candidate files",
    )
    parser.add_argument(
        "--report-root-dir",
        default="/tmp/mocness_field_sheets/reports/calibration",
        help="Root directory for ephemeral diff reports",
    )
    parser.add_argument(
        "--fallback-reference-dir",
        default=None,
        help="Optional fallback reference directory for non-golden tows (e.g. output/hypoxia25)",
    )
    parser.add_argument("--schema", default="schemas/mocness_tow.schema.json", help="Schema used for validation")
    parser.add_argument("--model", default="gpt-4.1", help="Model name")
    parser.add_argument("--api-key", default=None, help="Optional API key override")
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="Skip extraction and only validate/copy/diff existing output files",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    canonical_golden_dir = Path(args.canonical_golden_dir)
    candidate_root_dir = Path(args.candidate_root_dir)
    report_root_dir = Path(args.report_root_dir)
    fallback_reference_dir = Path(args.fallback_reference_dir) if args.fallback_reference_dir else None
    schema_path = Path(args.schema)

    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"{args.run_label}_{run_stamp}"
    candidate_dir = candidate_root_dir / run_name
    report_path = report_root_dir / f"{run_name}.md"

    if not args.skip_extract:
        output_dir.mkdir(parents=True, exist_ok=True)
        asyncio.run(
            run_extractor(
                input_dir=args.input_dir,
                output_dir=str(output_dir),
                model=args.model,
                api_key=args.api_key,
            )
        )

    tow_ids = args.tow_ids
    if len(tow_ids) == 1 and tow_ids[0].lower() == "all":
        tow_ids = _discover_tow_ids_from_output(output_dir)
        if not tow_ids:
            raise SystemExit(f"No tow_*.json files found in {output_dir} to resolve --tow-ids all")

    validator = _load_schema(schema_path)
    failures = _validate_dir(validator, output_dir)
    if failures:
        print("Validation failed:")
        for line in failures:
            print(line)
        raise SystemExit(1)

    copied, missing = _copy_candidates(output_dir, candidate_dir, tow_ids)
    _generate_diff_report(copied, canonical_golden_dir, fallback_reference_dir, report_path)

    print(f"Calibration candidates written to: {candidate_dir}")
    print(f"Diff report written to: {report_path}")
    if missing:
        print("Missing expected tow outputs:")
        for path in missing:
            print(f"  - {path}")


if __name__ == "__main__":
    main()