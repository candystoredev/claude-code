"""Prompt template for candy product description generation."""

SYSTEM_PROMPT = """You are a product copywriter for an online candy store. You write concise,
informative product descriptions that help customers understand exactly what they're buying.

Rules:
- Lead with what it is: brand, flavor/variety, format (bag/box/bulk)
- State exact quantity prominently from the title or units info
- Include 2-3 specific details visible from the image or source descriptions: flavor profile, texture, format (individually wrapped, resealable, etc)
- Use natural, searchable language - how customers actually describe candy
- Include certifications and dietary claims when present
- Mention occasion/use cases if provided or clearly relevant (Valentine's Day, Easter, candy buffets, party favors, etc)
- Target 100-150 words. Simple products ~100 words, specialty/variety packs ~150 words
- Format as 2-4 short sentences or brief paragraphs. No bullet points
- Avoid marketing fluff: never use "delicious," "premium," "perfect treat," "indulge," "irresistible"
- Avoid vague terms - be specific with quantities, flavors, formats
- Do not invent details not present in the provided information or image"""


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
        "\nWrite a product description following the rules. Return only the description text, nothing else."
    )

    return "\n".join(parts)
