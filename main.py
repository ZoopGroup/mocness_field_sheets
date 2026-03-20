import asyncio
import argparse
import os
from extract_mocness import main as extract_main

def main():
    parser = argparse.ArgumentParser(description="Run MOCNESS field sheet extraction")
    parser.add_argument("--model", help="Override model name (e.g. gpt-5.3)")
    parser.add_argument("--api-key", help="Override OPENAI_API_KEY for this run")
    parser.add_argument("--input-dir", help="Override INPUT_DIR for this run")
    parser.add_argument("--output-dir", help="Override OUTPUT_DIR for this run")
    args = parser.parse_args()

    if args.model:
        os.environ["MODEL"] = args.model
    if args.api_key:
        os.environ["OPENAI_API_KEY"] = args.api_key
    if args.input_dir:
        os.environ["INPUT_DIR"] = args.input_dir
    if args.output_dir:
        os.environ["OUTPUT_DIR"] = args.output_dir

    print("Starting MOCNESS field sheet extraction...")
    asyncio.run(extract_main())

if __name__ == "__main__":
    main()
