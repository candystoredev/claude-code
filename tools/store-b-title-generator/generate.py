#!/usr/bin/env python3
"""
Store B product title generator using Claude API.

Takes a CSV with distributor titles and Store A titles, then generates
differentiated Store B titles following a consistent convention.

Usage:
    # Test on first 50 products
    python generate.py --limit 50

    # Process all products
    python generate.py

    # Resume from where you left off (auto-detected from output file)
    python generate.py --resume

    # Custom input/output files
    python generate.py --input input/my_products.csv --output output/my_results.csv
"""

import argparse
import csv
import os
import sys
import time

import anthropic

import config
from prompt_template import SYSTEM_PROMPT, build_user_prompt


def load_input_csv(filepath: str) -> list[dict]:
    """Load the input CSV and return list of row dicts."""
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def load_completed_skus(filepath: str) -> set[str]:
    """Load already-processed SKUs from the output CSV."""
    completed = set()
    if not os.path.exists(filepath):
        return completed
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = row.get("sku", "").strip()
            if sku and row.get("store_b_title", "").strip():
                completed.add(sku)
    return completed


def generate_store_b_title(client: anthropic.Anthropic, row: dict) -> str:
    """Call Claude API to generate a Store B title for a single product."""
    user_text = build_user_prompt(row)

    content = [{"type": "text", "text": user_text}]
    messages = [{"role": "user", "content": content}]

    store_a_title = (row.get("store_a_title") or "").strip()

    max_retries = 3

    for attempt in range(max_retries):
        message = client.messages.create(
            model=config.API_MODEL,
            max_tokens=config.API_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
        )

        result = message.content[0].text.strip()

        # Validate: must not be identical to Store A title
        if result.lower() != store_a_title.lower():
            return result

        # Too similar — ask the model to differentiate more
        print("(too similar to Store A, retrying)", end=" ", flush=True)
        messages.append({"role": "assistant", "content": result})
        messages.append(
            {
                "role": "user",
                "content": (
                    "That title is identical to the Store A title. "
                    "Rewrite it following the Store B convention so the attribute order, "
                    "separators, and phrasing are clearly different from Store A. "
                    "Return only the title text."
                ),
            }
        )

    return result


def init_output_csv(filepath: str, fieldnames: list[str]):
    """Create the output CSV with headers if it doesn't exist."""
    if not os.path.exists(filepath):
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()


def append_rows(filepath: str, fieldnames: list[str], rows: list[dict]):
    """Append processed rows to the output CSV."""
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        for row in rows:
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(
        description="Generate Store B product titles with Claude API"
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Input CSV path (default: input/products.csv)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV path (default: output/products_with_store_b_titles.csv)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N products (for testing)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from previous run, skipping already-processed SKUs",
    )
    args = parser.parse_args()

    input_path = args.input or os.path.join(
        config.INPUT_DIR, config.DEFAULT_INPUT_FILE
    )
    output_path = args.output or os.path.join(
        config.OUTPUT_DIR, config.DEFAULT_OUTPUT_FILE
    )

    # Validate API key
    api_key = config.ANTHROPIC_API_KEY
    if not api_key:
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ANTHROPIC_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set.")
        print("Set it via environment variable or create a .env file in this directory:")
        print("  echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env")
        sys.exit(1)

    # Load input
    if not os.path.exists(input_path):
        print(f"Error: Input file not found: {input_path}")
        print(f"Place your CSV in the input/ directory as '{config.DEFAULT_INPUT_FILE}'")
        sys.exit(1)

    rows = load_input_csv(input_path)
    print(f"Loaded {len(rows)} products from {input_path}")

    if args.limit:
        rows = rows[: args.limit]
        print(f"Limited to first {args.limit} products (test mode)")

    # Determine output fieldnames (filter None keys from trailing CSV commas)
    fieldnames = [k for k in rows[0].keys() if k is not None] if rows else []
    if "store_b_title" not in fieldnames:
        fieldnames.append("store_b_title")
    if "generation_status" not in fieldnames:
        fieldnames.append("generation_status")

    # Handle resume
    completed_skus = set()
    if args.resume:
        completed_skus = load_completed_skus(output_path)
        print(f"Resuming: {len(completed_skus)} products already processed")
    else:
        init_output_csv(output_path, fieldnames)

    client = anthropic.Anthropic(api_key=api_key)

    # Process products
    buffer = []
    processed = 0
    skipped = 0
    errors = 0
    total = len(rows)

    for i, row in enumerate(rows):
        sku = (row.get("sku") or "").strip()

        if sku in completed_skus:
            skipped += 1
            continue

        distributor_title = row.get("distributor_title", "Unknown")
        print(
            f"[{i + 1}/{total}] Processing: {distributor_title[:60]}...",
            end=" ",
            flush=True,
        )

        try:
            store_b_title = generate_store_b_title(client, row)
            row["store_b_title"] = store_b_title
            row["generation_status"] = "success"
            processed += 1
            print("OK")
        except anthropic.APIError as e:
            row["store_b_title"] = ""
            row["generation_status"] = f"error: {e}"
            errors += 1
            print(f"API ERROR: {e}")
        except Exception as e:
            row["store_b_title"] = ""
            row["generation_status"] = f"error: {e}"
            errors += 1
            print(f"ERROR: {e}")

        buffer.append(row)

        # Checkpoint: save every N products
        if len(buffer) >= config.SAVE_EVERY_N:
            append_rows(output_path, fieldnames, buffer)
            buffer = []
            print(
                f"  -- Checkpoint saved. Processed: {processed}, "
                f"Errors: {errors}, Skipped: {skipped}"
            )

        # Rate limiting
        time.sleep(1.0 / config.REQUESTS_PER_SECOND)

    # Flush remaining buffer
    if buffer:
        append_rows(output_path, fieldnames, buffer)

    print("\n--- Done ---")
    print(f"Processed: {processed}")
    print(f"Skipped (already done): {skipped}")
    print(f"Errors: {errors}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
