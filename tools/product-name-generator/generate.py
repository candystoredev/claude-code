#!/usr/bin/env python3
"""
Candy product name generator using Claude API.

Generates standardized product names in two phases:
  Phase 1 — Claude generates names WITHOUT individual package sizes.
  Phase 2 — Python detects duplicate names and inserts the package size
             to differentiate them (post-process deduplication).

Usage:
    # Test on first 50 products
    python generate.py --limit 50

    # Process all products
    python generate.py

    # Resume from where you left off
    python generate.py --resume

    # Custom input/output files
    python generate.py --input input/my_products.csv --output output/my_results.csv
"""

import argparse
import csv
import os
import re
import sys
import time
from collections import defaultdict

import anthropic

import config
from prompt_template import (
    SYSTEM_PROMPT,
    build_user_prompt,
    compute_name_budget,
    find_missing_packaging,
    get_unit_size,
    has_tubs_suffix,
)


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------

def load_csv(filepath: str) -> list[dict]:
    """Load a CSV and return a list of row dicts."""
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_completed_skus(filepath: str) -> set[str]:
    """Return Variant SKUs that already have a generated name in the output."""
    completed: set[str] = set()
    if not os.path.exists(filepath):
        return completed
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            sku = row.get("Variant SKU", "").strip()
            if sku and row.get("new_product_name", "").strip():
                completed.add(sku)
    return completed


def init_output_csv(filepath: str, fieldnames: list[str]):
    """Create the output CSV with headers (only if it doesn't already exist)."""
    if not os.path.exists(filepath):
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fieldnames).writeheader()


def append_rows(filepath: str, fieldnames: list[str], rows: list[dict]):
    """Append rows to the output CSV."""
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        for row in rows:
            writer.writerow(row)


def write_all_rows(filepath: str, fieldnames: list[str], rows: list[dict]):
    """Overwrite the output CSV with all rows (used after dedup rewrites)."""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ---------------------------------------------------------------------------
# Name generation (Phase 1)
# ---------------------------------------------------------------------------

def generate_product_name(client: anthropic.Anthropic, row: dict) -> str:
    """Generate a product name with unit size appended from CSV data.

    The model generates only the name portion.  The code appends
    " - {unit_size}" from the CSV so the model can never hallucinate it.
    """
    unit_size = get_unit_size(row)
    tubs = has_tubs_suffix(row)
    name_budget = compute_name_budget(unit_size, tubs=tubs)
    user_text = build_user_prompt(row, char_budget=name_budget)
    messages = [{"role": "user", "content": user_text}]

    max_retries = 3

    for attempt in range(max_retries):
        message = client.messages.create(
            model=config.API_MODEL,
            max_tokens=config.API_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        name_part = message.content[0].text.strip()

        # Strip any trailing dash/size the model may have added despite instructions
        if " - " in name_part:
            name_part = name_part.rsplit(" - ", 1)[0].strip()

        if len(name_part) <= name_budget:
            break

        # Too long — ask the model to shorten
        print(f"({len(name_part)} chars, retrying)", end=" ", flush=True)
        messages.append({"role": "assistant", "content": name_part})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"That is {len(name_part)} characters. "
                    f"It MUST be {name_budget} or fewer. Shorten it further."
                ),
            }
        )

    # Enforce KEEP packaging formats: if the source title has one and the
    # model dropped it, append it to the product name deterministically.
    title = row.get("Title", "")
    print(f"\n  [debug] title={title!r}")
    print(f"  [debug] name_part={name_part!r}")
    missing_fmt = find_missing_packaging(title, name_part)
    print(f"  [debug] missing_fmt={missing_fmt!r}")
    if missing_fmt:
        candidate = f"{name_part} {missing_fmt}"
        if len(candidate) <= name_budget:
            print(f"  [fix] Added missing '{missing_fmt}': {name_part} → {candidate}")
            name_part = candidate
        else:
            print(f"  [fix] '{missing_fmt}' found in title but won't fit ({len(candidate)} > {name_budget})")

    # Assemble final name: product name + unit size (+ optional Tubs suffix)
    if unit_size:
        suffix = f"{unit_size} Tubs" if tubs else unit_size
        return f"{name_part} - {suffix}"
    return name_part


# ---------------------------------------------------------------------------
# Post-process size deduplication (Phase 2)
# ---------------------------------------------------------------------------

_SIZE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(oz|g|lb|ml|kg|fl\s*oz)\b",
    re.IGNORECASE,
)


def extract_package_size(text: str) -> str:
    """Pull the first individual-package size from *text* (e.g. '7.5oz')."""
    if not text:
        return ""
    m = _SIZE_RE.search(text)
    if m:
        unit = re.sub(r"\s+", "", m.group(2).lower())  # "fl oz" → "floz"
        return f"{m.group(1)}{unit}"
    return ""


def deduplicate_names(rows: list[dict]) -> int:
    """Flag duplicate product names for review. Returns count flagged.

    Since unit sizes are now appended from CSV data, duplicates indicate
    genuinely identical products that need manual differentiation (e.g.
    inserting the individual package size to tell them apart).
    """
    # Group successful rows by their generated name
    name_groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        name = row.get("new_product_name", "").strip()
        if name and row.get("generation_status") == "success":
            name_groups[name].append(row)

    modified = 0
    for name, group in name_groups.items():
        if len(group) <= 1:
            continue  # unique — nothing to do

        for row in group:
            # Try to differentiate by inserting the individual package size
            size = ""
            for col in ("Title", "description", "description_mini_01"):
                size = extract_package_size(row.get(col, ""))
                if size:
                    break

            if not size:
                row["generation_status"] = "review: duplicate name, no size found"
                modified += 1
                continue

            if " - " not in row["new_product_name"]:
                row["generation_status"] = "review: duplicate name, missing dash"
                modified += 1
                continue

            base, suffix = row["new_product_name"].rsplit(" - ", 1)
            new_name = f"{base} {size} - {suffix}"

            if len(new_name) <= 56:
                row["new_product_name"] = new_name
                modified += 1
            else:
                row["generation_status"] = (
                    f"review: size dedup would be {len(new_name)} chars"
                )
                modified += 1

    return modified


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def resolve_api_key() -> str:
    """Return the API key from env-var or local .env file."""
    key = config.ANTHROPIC_API_KEY
    if key:
        return key
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def main():
    parser = argparse.ArgumentParser(
        description="Generate candy product names with Claude API"
    )
    parser.add_argument("--input", default=None, help="Input CSV path")
    parser.add_argument("--output", default=None, help="Output CSV path")
    parser.add_argument(
        "--limit", type=int, default=None, help="Process only first N products"
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

    # --- API key ---
    api_key = resolve_api_key()
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set.")
        print("Set it via environment variable or create a .env file:")
        print("  echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env")
        sys.exit(1)

    # --- Input ---
    if not os.path.exists(input_path):
        print(f"Error: Input file not found: {input_path}")
        print(
            f"Place your CSV in the input/ directory as '{config.DEFAULT_INPUT_FILE}'"
        )
        sys.exit(1)

    rows = load_csv(input_path)
    print(f"Loaded {len(rows)} products from {input_path}")
    if rows:
        print(f"[debug] CSV columns: {list(rows[0].keys())}")

    if args.limit:
        rows = rows[: args.limit]
        print(f"Limited to first {args.limit} products (test mode)")

    # --- Fieldnames ---
    fieldnames = list(rows[0].keys()) if rows else []
    if "new_product_name" not in fieldnames:
        fieldnames.append("new_product_name")
    if "generation_status" not in fieldnames:
        fieldnames.append("generation_status")

    # --- Resume ---
    completed_skus: set[str] = set()
    if args.resume:
        completed_skus = load_completed_skus(output_path)
        print(f"Resuming: {len(completed_skus)} products already processed")
    else:
        init_output_csv(output_path, fieldnames)

    client = anthropic.Anthropic(api_key=api_key)

    # ===================================================================
    # Phase 1: Generate product names (without package sizes)
    # ===================================================================
    print("\n--- Phase 1: Generating product names ---")
    buffer: list[dict] = []
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
        print(f"[{i + 1}/{total}] {title[:60]}...", end=" ", flush=True)

        try:
            name = generate_product_name(client, row)
            row["new_product_name"] = name
            row["generation_status"] = "success"
            processed += 1
            print("OK")
        except anthropic.APIError as e:
            row["new_product_name"] = ""
            row["generation_status"] = f"error: {e}"
            errors += 1
            print(f"API ERROR: {e}")
        except Exception as e:
            row["new_product_name"] = ""
            row["generation_status"] = f"error: {e}"
            errors += 1
            print(f"ERROR: {e}")

        buffer.append(row)

        if len(buffer) >= config.SAVE_EVERY_N:
            append_rows(output_path, fieldnames, buffer)
            buffer = []
            print(
                f"  -- Checkpoint saved. "
                f"Processed: {processed}, Errors: {errors}, Skipped: {skipped}"
            )

        time.sleep(1.0 / config.REQUESTS_PER_SECOND)

    # Flush remaining buffer
    if buffer:
        append_rows(output_path, fieldnames, buffer)

    print(
        f"\nPhase 1 complete. "
        f"Processed: {processed}, Errors: {errors}, Skipped: {skipped}"
    )

    # ===================================================================
    # Phase 2: Post-process size deduplication
    # ===================================================================
    print("\n--- Phase 2: Size deduplication ---")

    # Reload the full output so dedup covers previously-resumed rows too
    all_rows = load_csv(output_path)
    dedup_count = deduplicate_names(all_rows)

    if dedup_count > 0:
        write_all_rows(output_path, fieldnames, all_rows)
        print(f"Modified {dedup_count} product names (inserted package size)")
    else:
        print("No duplicate names found — no size insertion needed")

    # --- Summary ---
    print("\n--- Done ---")
    print(f"Processed: {processed}")
    print(f"Skipped (already done): {skipped}")
    print(f"Errors: {errors}")
    print(f"Deduplicated: {dedup_count}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
