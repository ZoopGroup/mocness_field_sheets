import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator


def main():
    parser = argparse.ArgumentParser(description="Validate extracted tow JSON files against schema")
    parser.add_argument("--schema", default="schemas/mocness_tow.schema.json", help="Path to JSON schema")
    parser.add_argument("--dir", default="output", help="Directory containing tow_*.json files")
    args = parser.parse_args()

    schema_path = Path(args.schema)
    data_dir = Path(args.dir)

    schema = json.loads(schema_path.read_text())
    validator = Draft202012Validator(schema)

    files = sorted(data_dir.glob("tow_*.json"))
    if not files:
        raise SystemExit(f"No JSON files found in {data_dir}")

    failed = 0
    for file in files:
        payload = json.loads(file.read_text())
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        if errors:
            failed += 1
            print(f"FAIL {file}")
            for err in errors:
                path = ".".join(str(p) for p in err.path) if err.path else "<root>"
                print(f"  - {path}: {err.message}")
        else:
            print(f"PASS {file}")

    if failed:
        raise SystemExit(f"Validation failed for {failed} file(s)")

    print("All files passed schema validation")


if __name__ == "__main__":
    main()