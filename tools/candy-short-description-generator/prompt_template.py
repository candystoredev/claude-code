"""Prompt template for candy short product description generation."""

SYSTEM_PROMPT = """You are a product copywriter for an online candy store. You write short,
punchy product descriptions that help customers quickly understand what they're buying.

TODO: New ruleset for short descriptions will be provided.

For now, generate a brief 1-2 sentence product summary that captures the essential details:
brand, product type, quantity, and key selling point.

Do not invent details not present in the provided information or image."""


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
        "\nWrite a short product description following the rules. Return only the description text, nothing else."
    )

    return "\n".join(parts)
