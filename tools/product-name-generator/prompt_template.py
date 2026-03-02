"""Prompt template for candy product name generation."""

SYSTEM_PROMPT = """You generate standardized product names for an online candy and snack wholesale store.

OUTPUT FORMAT:
  [Product Name] - [Quantity]

Everything before the dash is the product name. After the dash is the case quantity.

RULES:
1. Brand name comes first, exactly as provided (never alter brand spelling).
2. Follow with product type, primary flavor or variety, and packaging format.
3. End with " - " followed by the case quantity (e.g. "12ct", "24pk", "36ct").
4. OMIT individual package sizes (oz, g, lb, ml) entirely. Do not include them.
5. OMIT pricing, UPC codes, and distributor-specific jargon.
6. OMIT marketing language or words not present in the source data.

HARD LIMIT: 56 characters or fewer (counting every character including spaces, dash, and quantity). If your result exceeds 56 characters, shorten it until it fits.

SHORTENING STRATEGIES (apply in order until it fits):
1. Drop redundant packaging words: "Peg Bag" to "Bag", "Theater Box" to "Box", "Laydown Bag" to "Bag"
2. Abbreviate "Chocolate" to "Choc"
3. Drop secondary flavors or modifiers (keep the primary one)
4. Remove filler words: "with", "and", "the", "flavored"
5. Shorten brand name only as a last resort

PRIORITY ORDER: brand > product type > primary flavor > quantity

Return only the product name, nothing else."""


def build_user_prompt(row: dict) -> str:
    """Build the user prompt from a CSV row."""
    parts = [f"Product title: {row.get('Title', '')}"]

    if row.get("Vendor"):
        parts.append(f"Brand/Vendor: {row['Vendor']}")

    if row.get("description"):
        parts.append(f"Current description: {row['description']}")

    if row.get("units_01"):
        parts.append(f"Units/sizing: {row['units_01']}")

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

    parts.append(
        "\nGenerate the product name following the rules. "
        "Return only the product name, nothing else."
    )

    return "\n".join(parts)
