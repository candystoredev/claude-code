#!/usr/bin/env python3
"""
Candy product description generator using Claude API with image analysis.

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
    """Load already-processed Variant SKUs from the output CSV."""
    completed = set()
    if not os.path.exists(filepath):
        return completed
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = row.get("Variant SKU", "").strip()
            if sku and row.get("new_description", "").strip():
                completed.add(sku)
    return completed


def get_image_media_type(url: str) -> str:
    """Guess media type from URL extension."""
    lower = url.lower().split("?")[0]
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


def generate_description(client: anthropic.Anthropic, row: dict) -> str:
    """Call Claude API with image + text prompt for a single product."""
    user_text = build_user_prompt(row)
    image_url = (row.get("Image Src") or "").strip()

    content = []

    if image_url:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": image_url,
                },
            }
        )

    content.append({"type": "text", "text": user_text})

    message = client.messages.create(
        model=config.API_MODEL,
        max_tokens=config.API_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )

    return message.content[0].text.strip()


def init_output_csv(filepath: str, fieldnames: list[str]):
    """Create the output CSV with headers if it doesn't exist."""
    if not os.path.exists(filepath):
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()


def append_rows(filepath: str, fieldnames: list[str], rows: list[dict]):
    """Append processed rows to the output CSV."""
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        for row in rows:
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Generate candy product descriptions with Claude API")
    parser.add_argument("--input", default=None, help="Input CSV path (default: input/products.csv)")
    parser.add_argument("--output", default=None, help="Output CSV path (default: output/products_with_descriptions.csv)")
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N products (for testing)")
    parser.add_argument("--resume", action="store_true", help="Resume from previous run, skipping already-processed SKUs")
    args = parser.parse_args()

    input_path = args.input or os.path.join(config.INPUT_DIR, config.DEFAULT_INPUT_FILE)
    output_path = args.output or os.path.join(config.OUTPUT_DIR, config.DEFAULT_OUTPUT_FILE)

    # Validate API key
    api_key = config.ANTHROPIC_API_KEY
    if not api_key:
        # Try loading from .env file in project directory
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
        print('  echo \'ANTHROPIC_API_KEY=sk-ant-...\' > .env')
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

    # Determine output fieldnames
    fieldnames = list(rows[0].keys()) if rows else []
    if "new_description" not in fieldnames:
        fieldnames.append("new_description")
    if "generation_status" not in fieldnames:
        fieldnames.append("generation_status")

    # Handle resume
    completed_skus = set()
    if args.resume:
        completed_skus = load_completed_skus(output_path)
        print(f"Resuming: {len(completed_skus)} products already processed")
    else:
        # Fresh run - initialize output file
        init_output_csv(output_path, fieldnames)

    client = anthropic.Anthropic(api_key=api_key)

    # Process products
    buffer = []
    processed = 0
    skipped = 0
    errors = 0
    total = len(rows)

    for i, row in enumerate(rows):
        sku = (row.get("Variant SKU") or "").strip()

        if sku in completed_skus:
            skipped += 1
            continue

        title = row.get("Title", "Unknown")
        print(f"[{i + 1}/{total}] Processing: {title[:60]}...", end=" ", flush=True)

        try:
            description = generate_description(client, row)
            row["new_description"] = description
            row["generation_status"] = "success"
            processed += 1
            print("OK")
        except anthropic.APIError as e:
            row["new_description"] = ""
            row["generation_status"] = f"error: {e}"
            errors += 1
            print(f"API ERROR: {e}")
        except Exception as e:
            row["new_description"] = ""
            row["generation_status"] = f"error: {e}"
            errors += 1
            print(f"ERROR: {e}")

        buffer.append(row)

        # Checkpoint: save every N products
        if len(buffer) >= config.SAVE_EVERY_N:
            append_rows(output_path, fieldnames, buffer)
            buffer = []
            print(f"  -- Checkpoint saved. Processed: {processed}, Errors: {errors}, Skipped: {skipped}")

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
