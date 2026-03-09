"""Prompt template for Store B product title generation.

Store B Title Convention
========================
Store B titles must differ from Store A titles while describing the same product
accurately. The following deterministic rules define the Store B style:

1. ATTRIBUTE ORDER (strict):
   Brand → Size Descriptor → Flavor/Variety → Product Type → Form Factor → Pack/Count → Net Weight

   Example: "Reese's King Size Peanut Butter Cups Candy - 4 Count - 2.8 oz"

2. SPELLING OUT:
   - Use "and" instead of "&"
   - Use "Count" instead of "ct" or "CT"
   - Use "Pack" instead of "pk" or "PK"
   - Use "Ounce" or "oz" consistently (prefer "oz" for brevity)
   - Use "Piece" or "Pieces" instead of "pc" or "pcs"

3. SIZE AND WEIGHT NOTATION:
   - Always include a space before the unit: "2.4 oz" not "2.4oz"
   - Place net weight last, after count/pack
   - Use " - " (space-dash-space) to separate count and weight from the product name

4. PRODUCT TYPE INCLUSION:
   - Always include a product type word (e.g., "Candy", "Gum", "Mints", "Candy Bar",
     "Gummy Candy", "Hard Candy", "Lollipop") when the Store A title omits it
   - Do not add a product type if one is already clearly present

5. BRAND NAME:
   - Always lead with the brand name exactly as given
   - Do not abbreviate brand names
   - Do not add trademark symbols

6. SIZE DESCRIPTORS:
   - Words like "King Size", "Fun Size", "Snack Size", "Share Size", "Family Size"
     go immediately after the brand name, before flavor/variety

7. FLAVOR AND VARIETY:
   - Keep all flavor descriptors from the source data
   - Use title case for flavor names
   - Separate multiple flavors with "and" (not "&" or "/")

8. PUNCTUATION:
   - No trailing periods
   - Use " - " (space-dash-space) as the separator before count and weight sections
   - Use commas only when listing 3+ flavors
   - No excessive capitalization (use title case throughout)

9. DIFFERENTIATION FROM STORE A:
   - The reordering of attributes, expanded abbreviations, and added product type
     provide natural differentiation
   - Do not copy the Store A title structure even if it already follows some rules
   - If the Store A title already follows Store B conventions closely, adjust by
     adding the product type or changing the separator style

10. CONSTRAINTS:
    - Do not invent facts not present in the inputs
    - Do not add marketing language, adjectives, or SEO keywords not in the source
    - Do not remove brand, flavor, size, count, or pack information
    - Keep titles concise — aim for under 120 characters where possible
    - Do not produce a title identical to Store A
"""

SYSTEM_PROMPT = """You generate product titles for Store B, an online candy and snack retailer.

You will receive two inputs for each product:
1. The distributor's original product title (the canonical source of truth for product facts)
2. The product title currently used on Store A (a competing store)

Your job: produce a new title for Store B that follows the Store B Title Convention below.

STORE B TITLE CONVENTION:

ATTRIBUTE ORDER (strict):
  Brand → Size Descriptor → Flavor/Variety → Product Type → Form Factor → Pack/Count → Net Weight

RULES:
- Use "and" instead of "&"
- Spell out "Count" not "ct", "Pack" not "pk", "Pieces" not "pcs"
- Always put a space before units: "2.4 oz" not "2.4oz"
- Use " - " (space-dash-space) to separate count/weight from the product name
- Always include a product type word (Candy, Gum, Candy Bar, Gummy Candy, Hard Candy, Lollipop, Mints, etc.) if one is not already present
- Lead with the brand name exactly as given — never abbreviate it
- Place size descriptors (King Size, Fun Size, Snack Size, Share Size) right after the brand
- Keep all flavors; use title case; join multiple flavors with "and"
- Use title case throughout; no trailing periods
- Do not copy Store A's title structure or wording when possible
- Do not invent facts not in the inputs
- Do not add marketing fluff or SEO keywords
- Do not remove any factual product attributes (brand, flavor, size, count, pack)
- Keep titles concise (aim for under 120 characters)
- The result MUST NOT be identical to the Store A title

Return ONLY the Store B title text. No quotes, no explanation, nothing else."""


def build_user_prompt(row: dict) -> str:
    """Build the text portion of the user prompt from a CSV row.

    Expected CSV columns:
      - distributor_title: the distributor's original product title
      - store_a_title: the title currently used on Store A
    """
    distributor_title = (row.get("distributor_title") or "").strip()
    store_a_title = (row.get("store_a_title") or "").strip()

    parts = []

    if distributor_title:
        parts.append(f"Distributor title: {distributor_title}")
    if store_a_title:
        parts.append(f"Store A title: {store_a_title}")

    # Pass through any additional context columns if present
    if row.get("brand"):
        parts.append(f"Brand: {row['brand']}")

    if row.get("flavor"):
        parts.append(f"Flavor: {row['flavor']}")

    if row.get("size"):
        parts.append(f"Size/Weight: {row['size']}")

    if row.get("count"):
        parts.append(f"Count/Pack: {row['count']}")

    if row.get("product_type"):
        parts.append(f"Product type: {row['product_type']}")

    parts.append(
        "\nGenerate the Store B title following the convention. Return only the title text."
    )

    return "\n".join(parts)
