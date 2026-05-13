import argparse
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Seed golden examples from existing extraction output")
    parser.add_argument("--source-dir", default="output", help="Directory containing tow_*.json")
    parser.add_argument("--target-dir", default="examples/golden", help="Directory to write seeded golden files")
    parser.add_argument("--tow-ids", nargs="+", required=True, help="Tow IDs to seed, e.g. 2 10 14")
    args = parser.parse_args()

    source = Path(args.source_dir)
    target = Path(args.target_dir)
    target.mkdir(parents=True, exist_ok=True)

    for tow_id in args.tow_ids:
        src_file = source / f"tow_{tow_id}.json"
        dst_file = target / f"tow_{tow_id}.json"
        if not src_file.exists():
            print(f"SKIP missing source {src_file}")
            continue
        shutil.copy2(src_file, dst_file)
        print(f"SEEDED {dst_file}")


if __name__ == "__main__":
    main()