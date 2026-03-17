"""Prompt templates for Shopify product categorization."""

import json
import re


SYSTEM_PROMPT_TEMPLATE = """You are a product categorizer for {store_name}, a Shopify-based online candy store.

Your task: Given product data, assign each product to the correct Custom Collections.

## Rules:
- ONLY use collection handles from the list below — never invent new ones
- Assign ALL relevant collections for each product (typically 2-6 collections)
- Consider these dimensions when categorizing:
  - Candy TYPE (chocolate-candy, gummy-candy, hard-candy, lollipops-suckers, etc.)
  - Sub-type (chocolate-coins-coin-candy, foil-wrapped-chocolate-candy, etc.)
  - BRAND/VENDOR — match vendor name to brand collections (e.g., Gerrit Verburg → gerrit-j-verburg)
  - COLOR — match foil color or candy color mentioned in the title (blue-candy, red-candy, etc.)
  - FLAVOR — match flavors mentioned (cherry-candy, lemon-candy, strawberry-candy, etc.)
  - OCCASION — only if clearly relevant (hearts → valentines-day-candy, "It's a Boy/Girl" → baby-showers)
  - SHAPE — if mentioned (ball-shaped-candy, heart-shaped-candy, star-shaped-candy, etc.)
  - PACKAGING — individually-wrapped-candy, bagged-candy, etc.
- Do NOT assign "show-all-products" or "frontpage"
- When in doubt about a marginal match, leave it out — precision over recall

## Available Collections (handle → display name):
{collections}

## Response Format:
Return ONLY valid JSON. Map each product handle to its collection handles array:
{{"product-handle-1": ["collection-a", "collection-b"], "product-handle-2": ["collection-c"]}}"""


def load_collections_for_prompt(collections: dict[str, str]) -> str:
    """Format the collections dict as a readable list for the system prompt."""
    lines = []
    for handle, title in sorted(collections.items()):
        if handle in ("show-all-products", "frontpage"):
            continue
        lines.append(f"  {handle} → {title}")
    return "\n".join(lines)


def build_system_prompt(collections: dict[str, str], store_name: str = "CandyStore.com") -> str:
    """Build the full system prompt with the collections list embedded."""
    collections_text = load_collections_for_prompt(collections)
    return SYSTEM_PROMPT_TEMPLATE.format(collections=collections_text, store_name=store_name)


def strip_html(html: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_user_prompt(products: list[dict]) -> str:
    """Build the user prompt for a batch of products.

    Each product dict should have: handle, title, body_html, vendor
    """
    parts = [f"Categorize these {len(products)} products:\n"]

    for p in products:
        handle = p.get("handle", "")
        title = p.get("title", "")
        vendor = p.get("vendor", "")
        body_text = strip_html(p.get("body_html", ""))

        entry = f"- Handle: {handle}\n  Title: {title}\n  Vendor: {vendor}"
        # Only include body text if it adds info beyond the title
        if body_text and body_text.lower() != title.lower():
            # Truncate long descriptions to save tokens
            if len(body_text) > 300:
                body_text = body_text[:300] + "..."
            entry += f"\n  Description: {body_text}"
        parts.append(entry)

    parts.append(
        "\nReturn the JSON mapping each product handle to its collection handles."
    )
    return "\n\n".join(parts)
