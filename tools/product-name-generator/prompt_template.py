"""Prompt template for candy product name generation.

See SPEC.md for the full specification and examples.
"""

import re

# The model generates ONLY the product-name portion (before the dash).
# The code appends " - {unit_size}" from the CSV data afterward.
# char_budget = 56 - len(" - ") - len(unit_size)

SYSTEM_PROMPT = """You generate the product-name portion of a standardized product listing for an online candy and snack wholesale store.

IMPORTANT: You are generating ONLY the product name. Do NOT include a unit size, case count, or anything after a dash. The unit size is added separately by the system.

CASING: Always output in Title Case. Input is often ALL CAPS — convert it. Use standard brand casing where known (e.g. "M&M's", "Pixy Stix", "Reese's").

BRAND NAME RULES:
- Only include the brand/vendor name when it helps describe WHAT the product is.
- If the brand IS the product (Pixy Stix, M&M's, Reese's, Skittles, etc.), include it where it reads naturally.
- If the brand is a generic distributor or unknown to most consumers (e.g. Boston America, Palmer, Herbert's Best, Nancy Adams), OMIT IT entirely.
- When included, the brand does NOT have to come first. Put descriptors like color or flavor before the brand if that reads more naturally (e.g. "Yellow M&M's Candy" not "M&M's Yellow Candy").

RULES:
1. Describe what the product IS: product type, primary flavor/variety, distinguishing features.
2. OMIT individual package sizes (oz, g, lb, ml) from the name.
3. OMIT pricing, UPC codes, and distributor-specific jargon.
4. OMIT marketing language or words not present in the source data.
5. Do NOT add any information that isn't in the source data.

CHARACTER LIMIT: The result must fit within the character budget provided. If it exceeds the budget, shorten it.

PACKAGING FORMATS — KEEP vs DROP:
Some packaging formats distinguish different products and MUST be kept. Others are noise.
- MUST KEEP in product name (ALWAYS include if present in source data): Changemaker, Peg Bag, Gift Bag, Fun Size, King Size, Snack Size, Variety Pack, Theater Box, Bulk
  Example: "PIXY STIX ASSORTED CHANGEMAKER 0.42 OZ" → "Pixy Stix Assorted Changemaker" (Changemaker MUST appear)
- SYSTEM-HANDLED (do NOT include in your output): "Tubs" — the system appends it after the unit size automatically.
- DROP these (redundant noise): "Laydown Bag" → "Bag", "Boxes", "Breaks"
If a packaging term is on the KEEP list and appears in the source data, it MUST appear in your output. Never drop a KEEP packaging format.

SHORTENING STRATEGIES (apply in order):
1. Drop redundant/noise packaging words (see DROP list above)
2. Remove filler words: "with", "and", "the", "flavored"
3. Abbreviate "Chocolate" to "Choc"
4. Drop secondary flavors or modifiers (keep the primary one)
5. Drop or abbreviate the brand name (last resort)

PRIORITY ORDER: product type > packaging format (Changemaker, Peg Bag, etc.) > primary flavor > brand name

Return only the product name text. No dash, no unit size, no extra commentary."""


# Column name for unit size — matches the CSV header
UNIT_SIZE_COLUMN = "Distributor Unit Size"


def get_unit_size(row: dict) -> str:
    """Extract the unit size from the CSV row."""
    return (row.get(UNIT_SIZE_COLUMN) or "").strip()


# Packaging formats that MUST appear in the product name if present in source
KEEP_PACKAGING_FORMATS = [
    "Changemaker",
    "Peg Bag",
    "Gift Bag",
    "Fun Size",
    "King Size",
    "Snack Size",
    "Variety Pack",
    "Theater Box",
    "Bulk",
]


def find_missing_packaging(title: str, name_part: str) -> str | None:
    """Return the first KEEP packaging format found in *title* but missing from *name_part*."""
    title_upper = title.upper()
    name_upper = name_part.upper()
    for fmt in KEEP_PACKAGING_FORMATS:
        if fmt.upper() in title_upper and fmt.upper() not in name_upper:
            return fmt
    return None


def has_tubs_suffix(row: dict) -> bool:
    """Check if the source data indicates a 'Tubs' packaging format."""
    title = (row.get("Title") or "").upper()
    return bool(re.search(r"\bTUBS?\b", title))


def compute_name_budget(
    unit_size: str, total_limit: int = 56, tubs: bool = False,
) -> int:
    """Return the max character count for the product-name portion."""
    if unit_size:
        # Account for " - " (3 chars) plus the unit size string
        budget = total_limit - 3 - len(unit_size)
        if tubs:
            budget -= len(" Tubs")  # 5 chars for " Tubs" suffix
        return budget
    return total_limit


def build_user_prompt(row: dict, char_budget: int | None = None) -> str:
    """Build the user prompt from a CSV row.

    If *char_budget* is provided it is included so the model knows how
    many characters it has to work with.
    """
    parts = [f"Product title: {row.get('Title', '')}"]

    if row.get("Vendor"):
        parts.append(f"Brand/Vendor: {row['Vendor']}")

    if row.get("description"):
        parts.append(f"Current description: {row['description']}")

    if row.get("certifications"):
        parts.append(f"Certifications: {row['certifications']}")

    if row.get("nutritional_claims"):
        parts.append(f"Nutritional claims: {row['nutritional_claims']}")

    if row.get("occasion"):
        parts.append(f"Occasion: {row['occasion']}")

    # Gather mini descriptions
    minis = []
    for i in range(1, 5):
        key = f"description_mini_0{i}"
        if row.get(key):
            minis.append(row[key])
    if minis:
        parts.append(f"Additional details: {' | '.join(minis)}")

    if char_budget is not None:
        parts.append(
            f"\nCharacter budget: {char_budget} characters maximum."
        )

    parts.append(
        "Generate the product name following the rules. "
        "Return only the product name, nothing else."
    )

    return "\n".join(parts)
