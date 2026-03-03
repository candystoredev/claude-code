# Product Name Generator — Specification

This document is the single source of truth for how product names are generated.
All prompt templates and generation logic must follow these rules.

## Output Format

```
[Product Name] - [Unit Size]
[Product Name] - [Unit Size] Tubs      (when source data contains "Tubs")
```

Everything before the dash is the product name. After the dash is the unit size
pulled directly from the CSV data (never model-generated). When the source data
contains "Tubs", the code appends " Tubs" after the unit size automatically.

**Hard limit: 56 characters** (counting every character including spaces, dash,
unit size, and any suffix like " Tubs").

## Casing

- Output must always be **Title Case** (capitalize the first letter of each word).
- Input data is often ALL CAPS — always convert to Title Case.
- Brand names should use their standard casing (e.g. "M&M's", not "M&m's").

## Brand / Vendor Name Rules

The brand name is **NOT automatically placed at the beginning**. Apply these rules:

1. **Brand IS the product** — If the brand name is needed to identify what the
   product actually is, include it. Place it where it reads naturally.
   - "Pixy Stix" → the brand IS the product; include it.
   - "M&M's" → the brand IS the product; include it.
   - Example: `Yellow M&M's Candy - 10lb`
   - Example: `Pixy Stix Assorted Powder Candy - 85ct`

2. **Brand is well-known and adds value** — If the brand is widely recognized
   in the candy industry and helps a customer identify the product, it may be
   included (typically after the product description).
   - Example: `Peanut Butter Cups Reese's - 36ct`

3. **Brand is a generic distributor / unknown** — If the brand doesn't help
   describe the product and isn't a household name, **omit it entirely**.
   - "Boston America" is a distributor — omit.
   - "Palmer" — not needed to describe "Choco Fluff Pumpkins".
   - Example: `Gummy Rudolph Strawberry - 9ct` (no "Boston America")
   - Example: `Choco Fluff Pumpkins - 9lb` (no "Palmer")

## Unit Size

- The unit size is **always pulled from the data** — specifically the
  `Distributor Unit Size` column in the CSV.
- The model must **never generate or guess** the unit size.
- The code appends ` - {unit_size}` to whatever name the model returns.
- The model's character budget is therefore `56 - len(" - ") - len(unit_size)`.

## Packaging Formats — Keep vs Drop

Some packaging formats distinguish different products and **must be kept**. Others
are redundant noise and should be dropped or simplified.

**KEEP in product name** (these differentiate products — include before the dash):
- Changemaker
- Peg Bag
- Gift Bag
- Fun Size
- King Size
- Snack Size
- Variety Pack
- Theater Box
- Bulk

**KEEP after unit size** (placed after the dash + unit size by the system):
- Tubs — appears as `- 12ct Tubs`, NOT in the product name portion.
  The code detects "Tubs" from the source data and appends it automatically.
  The model must **not** include "Tubs" in its output.

**DROP or simplify** (redundant noise):
- "Laydown Bag" → "Bag"
- "Boxes", "Breaks" (generic, adds nothing)

**Rule of thumb:** if the packaging term tells the customer what they're getting
(e.g. a Changemaker vs a bag of Pixy Stix are different products), keep it.

## Shortening Strategies

When the product name portion exceeds its character budget, apply these in order:

1. Drop redundant/noise packaging words (see DROP list above)
2. Remove filler words: "with", "and", "the", "flavored"
3. Abbreviate "Chocolate" to "Choc"
4. Drop secondary flavors or modifiers (keep the primary one)
5. Drop or abbreviate the brand name (last resort)

## Priority Order (what to preserve)

1. Product type (what it IS — gummy, taffy, chocolate, etc.)
2. Packaging format from the KEEP list (Changemaker, Peg Bag, Theater Box, etc.)
3. Primary flavor / variety / distinguishing feature
4. Brand name (only when it meets inclusion rules above)
5. Quantity / case count

## What to Omit

- Individual package sizes (oz, g, ml) — unless that IS the unit size in the data
- Pricing, UPC codes, distributor-specific jargon
- Marketing language or words not present in the source data
- ALL CAPS formatting from source data

## CSV Column Mapping

| CSV Column             | Purpose                                    |
|------------------------|--------------------------------------------|
| Title                  | Original product title (often ALL CAPS)    |
| Vendor                 | Brand/vendor name                          |
| Distributor Unit Size  | Unit size to append after the dash         |
| Variant SKU            | Unique identifier for tracking completion  |
| description            | Product description                        |
| description_mini_01–04 | Additional detail fields                   |
| certifications         | Product certifications                     |
| nutritional_claims     | Health/nutrition claims                    |
| occasion               | Occasion context                           |

## Examples

| Input Title                                        | Vendor         | Unit Size | Output                                  |
|----------------------------------------------------|----------------|-----------|-----------------------------------------|
| TAFFY TOWN SALT WATER TAFFY RED LICORICE SWIRLS   | TAFFY TOWN     | 2.5lb     | Red Licorice Swirls Taffy Town - 2.5lb  |
| GUMMY RUDOLPH 3.88 OZ                             | BOSTON AMERICA  | 9ct       | Gummy Rudolph Strawberry - 9ct          |
| CHOCO FLUFF PUMPKINS 9 LB                         | PALMER         | 9lb       | Choco Fluff Pumpkins - 9lb              |
| PIXY STIX ASSORTED CHANGEMAKER 0.42 OZ            | PIXY STIX      | 85ct      | Pixy Stix Assorted Changemaker - 85ct   |
| HERBERT'S BEST SPOOKY GUMMI EYEZ 1.3 OZ           | HERBERT'S BEST | 7ct       | Spooky Gummy Eyes Halloween - 7ct       |
| M&M'S YELLOW 10 LB                                | M&M'S          | 10lb      | Yellow M&M's Candy - 10lb               |
