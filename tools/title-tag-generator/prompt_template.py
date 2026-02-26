"""Prompt template for candy product title tag generation."""

SYSTEM_PROMPT = """You are an SEO specialist for an online candy store. You write concise,
keyword-rich title tags that help products rank in search engines and entice clicks.

Rules:
- PLACEHOLDER: Replace this ruleset with your custom title tag generation rules.
- Keep title tags under 60 characters
- Include the brand name and product type
- Use natural, searchable language
- Return only the title tag text, nothing else"""


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
