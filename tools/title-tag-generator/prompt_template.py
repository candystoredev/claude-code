"""Prompt template for candy product title tag generation."""

SYSTEM_PROMPT = """You shorten product names for an online candy store.

Rules:
- Shorten the product name so that it is a maximum of 56 characters long
- Preserve the most important identifying information: brand, product type, flavor, and quantity
- Do not add any new words or information that is not in the original title
- Return only the shortened title tag text, nothing else"""


def build_user_prompt(row: dict) -> str:
    """Build the text portion of the user prompt from a CSV row."""
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
        "\nWrite a title tag following the rules. Return only the title tag text, nothing else."
    )

    return "\n".join(parts)
