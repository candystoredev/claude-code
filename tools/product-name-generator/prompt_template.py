"""Prompt template for candy product name generation.

See SPEC.md for the full specification and examples.
"""

# The model generates ONLY the product-name portion (before the dash).
# The code appends " - {unit_size}" from the CSV data afterward.
# char_budget = 56 - len(" - ") - len(unit_size)

SYSTEM_PROMPT = """You generate the product-name portion of a standardized product listing for an online candy and snack wholesale store.

IMPORTANT: You are generating ONLY the product name. Do NOT include a unit size, case count, or anything after a dash. The unit size is added separately by the system.

CASING: Always output in Title Case. Input is often ALL CAPS — convert it. Use standard brand casing where known (e.g. "M&M's", "Pixy Stix", "Reese's").

BRAND NAME RULES:
- Only include the brand/vendor name when it helps describe WHAT the product is.
- If the brand IS the product (Pixy Stix, M&M's, Reese's, Skittles, etc.), include it where it reads naturally.
- If the brand is a generic distributor or unknown to most consumers (e.g. Boston America, Palmer, Herbert's Best), OMIT IT entirely.
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
- KEEP these (they differentiate products): Changemaker, Peg Bag, Gift Bag, Fun Size, King Size, Snack Size, Variety Pack, Bulk
- DROP these (they are redundant noise): "Theater Box" → "Box", "Laydown Bag" → "Bag", "Tubs", "Boxes", "Breaks"
If a packaging term tells the customer what they're getting (e.g. a Changemaker vs a bag of Pixy Stix), keep it.

SHORTENING STRATEGIES (apply in order):
1. Drop redundant/noise packaging words (see DROP list above)
2. Remove filler words: "with", "and", "the", "flavored"
3. Abbreviate "Chocolate" to "Choc"
4. Drop secondary flavors or modifiers (keep the primary one)
5. Drop or abbreviate the brand name (last resort)

PRIORITY ORDER: product type > primary flavor > brand name

Return only the product name text. No dash, no unit size, no extra commentary."""


# Column name for unit size — matches the CSV header
UNIT_SIZE_COLUMN = "Distributor Unit Size"


def get_unit_size(row: dict) -> str:
    """Extract the unit size from the CSV row."""
    return (row.get(UNIT_SIZE_COLUMN) or "").strip()


def compute_name_budget(unit_size: str, total_limit: int = 56) -> int:
    """Return the max character count for the product-name portion."""
    if unit_size:
        # Account for " - " (3 chars) plus the unit size string
        return total_limit - 3 - len(unit_size)
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
