"""Prompt template for Store B product title generation.

Store B Title Convention
========================
Store B titles must differ from Store A titles while describing the same product
accurately. The following deterministic rules define the Store B style:

1. ATTRIBUTE ORDER (strict):
   Brand → Size Descriptor → Flavor/Variety → Product Type → Form Factor → Pack/Count → Net Weight

   Example: "Reese's King Size Peanut Butter Cups Candy - 4 Count - 2.8 OZ"

2. SPELLING OUT:
   - Use "and" instead of "&"
   - Use "Count" instead of "ct" or "CT"
   - Use "Pack" instead of "pk" or "PK"
   - Use "Ounce" or "oz" consistently (prefer "oz" for brevity)
   - Use "Piece" or "Pieces" instead of "pc" or "pcs"

3. SIZE AND WEIGHT NOTATION:
   - Always include a space before the unit: "2.4 OZ" not "2.4OZ"
   - Place net weight last, after count/pack
   - Use " - " (space-dash-space) to separate count and weight from the product name
   - UNITS MUST BE UPPERCASE: LB, OZ, CT, PK, G, KG, ML
     Examples: "10LB", "18CT", "2.4 OZ", "6 PK"

4. PRODUCT TYPE INCLUSION:
   - Always include a product type word (e.g., "Candy", "Gum", "Mints", "Candy Bar",
     "Gummy Candy", "Hard Candy", "Lollipop") when the Store A title omits it
   - Do not add a product type if one is already clearly present

5. BRAND NAME RULES (adapted from product-name-generator):
   - Always lead with the brand name exactly as given
   - Do not abbreviate brand names
   - Do not add trademark symbols
   - If the brand IS the product (M&M's, Pixy Stix, Reese's, Skittles), include it
     naturally — it does not have to be first if another order reads more naturally
   - If the brand is a generic distributor or unknown to most consumers (e.g. Boston
     America, Palmer, Herbert's Best, Nancy Adams), OMIT IT entirely — do not
     include it in the Store B title at all

6. SIZE DESCRIPTORS:
   - Words like "King Size", "Fun Size", "Snack Size", "Share Size", "Family Size"
     go immediately after the brand name, before flavor/variety

7. FLAVOR AND VARIETY:
   - Keep all flavor descriptors from the source data
   - Use title case for flavor names
   - Separate multiple flavors with "and" (not "&" or "/")

8. PACKAGING FORMATS (adapted from product-name-generator):
   - KEEP these in the title if present in source data: Changemaker, Peg Bag,
     Gift Bag, Fun Size, King Size, Snack Size, Variety Pack, Theater Box, Bulk
   - SIMPLIFY these: "Laydown Bag" → "Bag"
   - DROP generic noise: "Boxes", "Breaks" (unless they distinguish products)

9. PUNCTUATION:
   - No trailing periods
   - Use " - " (space-dash-space) as the separator before count and weight sections
   - Use commas only when listing 3+ flavors
   - Title case throughout, except unit suffixes which are UPPERCASE (LB, OZ, CT)

10. SHORTENING STRATEGIES (apply in order when title is too long):
    1. Drop redundant/noise packaging words (see DROP list above)
    2. Remove filler words: "with", "and", "the", "flavored"
    3. Abbreviate "Chocolate" to "Choc"
    4. Drop secondary flavors or modifiers (keep the primary one)
    5. Drop or abbreviate the brand name (last resort)

11. UNIT / COUNT SOURCING:
    - CRITICAL: Use the same count or unit quantity that appears in the Store A
      title. The Store A title's count (e.g. "6ct", "36ct") is the authoritative
      source for how many items are in the pack.
    - Do NOT substitute the net weight from the distributor title (e.g. "10 OZ")
      in place of Store A's count (e.g. "6ct").
    - If Store A says "6ct", Store B must end with "6 Count" (or equivalent).
    - If Store A says "10lb", Store B must end with "10 LB".
    - Only fall back to the distributor title's weight/count when Store A has no
      count or unit information at all.

12. DIFFERENTIATION FROM STORE A:
    - The reordering of attributes, expanded abbreviations, uppercase units, and
      added product type provide natural differentiation
    - Do not copy the Store A title structure or wording when possible
    - If the Store A title already follows Store B conventions closely, adjust by
      adding the product type, changing separator style, or reordering attributes
    - The generated title must be less than 75% similar to Store A

13. CONSTRAINTS:
    - Do not invent facts not present in the inputs
    - Do not add marketing language, adjectives, or SEO keywords not in the source
    - Do not remove brand, flavor, size, count, or pack information
    - Keep titles concise — aim for under 120 characters where possible
    - Do not produce a title identical or nearly identical to Store A
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
- Always put a space before units: "2.4 OZ" not "2.4OZ"
- UNIT SUFFIXES MUST BE UPPERCASE: LB, OZ, CT, PK, G, KG, ML
  Examples: "10LB", "18CT", "2.4 OZ", "6 PK"
- Use " - " (space-dash-space) to separate count/weight from the product name
- Always include a product type word (Candy, Gum, Candy Bar, Gummy Candy, Hard Candy, Lollipop, Mints, etc.) if one is not already present
- Lead with the brand name exactly as given — never abbreviate it
- If the brand IS the product (M&M's, Skittles, Reese's), include naturally
- If the brand is a generic distributor or unknown to most consumers (e.g. Boston America, Palmer, Herbert's Best, Nancy Adams), OMIT IT entirely from the title
- Place size descriptors (King Size, Fun Size, Snack Size, Share Size) right after the brand
- Keep all flavors; use title case; join multiple flavors with "and"
- KEEP these packaging formats if present: Changemaker, Peg Bag, Gift Bag, Fun Size, King Size, Snack Size, Variety Pack, Theater Box, Bulk
- SIMPLIFY: "Laydown Bag" → "Bag". DROP noise: "Boxes", "Breaks"
- Use title case throughout (except unit suffixes which are UPPERCASE); no trailing periods
- Do not copy Store A's title structure or wording when possible
- Do not invent facts not in the inputs
- Do not add marketing fluff or SEO keywords
- Do not remove any factual product attributes (brand, flavor, size, count, pack)
- CRITICAL: Use the SAME count/unit quantity from the Store A title. If Store A says "6ct", end with "6 Count". If Store A says "10lb", end with "10 LB". Do NOT replace Store A's count with the distributor's net weight.
- Only fall back to the distributor title's weight/count when Store A has no count or unit info at all
- Keep titles concise (aim for under 120 characters)
- The result MUST NOT be identical or nearly identical to the Store A title
- SHORTENING (if too long): drop noise packaging → remove filler words (with, and, the, flavored) → abbreviate Chocolate to Choc → drop secondary flavors → abbreviate brand (last resort)

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
