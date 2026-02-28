"""Matching logic for syncing Shopify variants with distributor products.

Two-pass approach:
  Pass 1 — Deterministic matching on SKU, barcode, or normalized flavor+size.
  Pass 2 — Claude API fallback for unresolved records.
"""

import json
import logging
import re

import pandas as pd

from app.config import (
    ANTHROPIC_API_KEY,
    API_MAX_TOKENS,
    API_MODEL,
    MATCH_AUTO_THRESHOLD,
    MATCH_REVIEW_THRESHOLD,
    MAX_CLAUDE_BATCH_SIZE,
)

logger = logging.getLogger(__name__)

# --- Normalization helpers (pure functions) ---

UNIT_SYNONYMS = {
    "pound": "lb",
    "pounds": "lb",
    "lbs": "lb",
    "ounce": "oz",
    "ounces": "oz",
    "gram": "g",
    "grams": "g",
    "kilogram": "kg",
    "kilograms": "kg",
    "kgs": "kg",
    "milliliter": "ml",
    "milliliters": "ml",
    "liter": "l",
    "liters": "l",
    "fl oz": "floz",
    "fluid ounce": "floz",
    "fluid ounces": "floz",
    "count": "ct",
    "counts": "ct",
    "piece": "pc",
    "pieces": "pc",
    "pcs": "pc",
    "pack": "pk",
    "packs": "pk",
}

FILLER_WORDS = {
    "flavor", "flavour", "scent", "variety", "size", "type",
    "style", "option", "color", "colour",
}


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = str(text).lower().strip()
    text = re.sub(r"[^\w\s.]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_units(text: str) -> str:
    """Standardize unit representations (e.g. '2.5 pounds' -> '2.5lb')."""
    text = normalize_text(text)
    for synonym, canonical in UNIT_SYNONYMS.items():
        text = re.sub(rf"\b{re.escape(synonym)}\b", canonical, text)
    # Collapse space between number and unit: "2.5 lb" -> "2.5lb"
    text = re.sub(r"(\d+\.?\d*)\s+(lb|oz|g|kg|ml|l|floz|ct|pc|pk)\b", r"\1\2", text)
    return text


def strip_filler(text: str) -> str:
    """Remove common filler words from text."""
    words = normalize_text(text).split()
    return " ".join(w for w in words if w not in FILLER_WORDS)


def extract_size_from_title(title: str) -> str:
    """Extract size/weight pattern from a product title string."""
    title = str(title).lower()
    match = re.search(
        r"(\d+\.?\d*)\s*"
        r"(lb|lbs|pound|pounds|oz|ounce|ounces|g|gram|grams|"
        r"kg|kilogram|kilograms|ml|milliliter|l|liter|"
        r"fl\s*oz|ct|count|pc|piece|pk|pack)\b",
        title,
    )
    if match:
        return normalize_units(match.group(0))
    return ""


def normalize_sku(sku: str) -> str:
    """Normalize a SKU for comparison."""
    return re.sub(r"[^a-z0-9]", "", str(sku).lower().strip())


def normalize_barcode(barcode: str) -> str:
    """Normalize a barcode/UPC — strip non-digits, remove leading zeros."""
    digits = re.sub(r"[^0-9]", "", str(barcode).strip())
    return digits.lstrip("0") if digits else ""


# --- Match result data structure ---

class MatchResult:
    """Container for a single match result."""

    def __init__(
        self,
        shopify_idx: int | None = None,
        distributor_idx: int | None = None,
        match_type: str = "unmatched",
        confidence: float = 0.0,
        reasoning: str = "",
    ):
        self.shopify_idx = shopify_idx
        self.distributor_idx = distributor_idx
        self.match_type = match_type  # "sku", "barcode", "flavor_size", "claude", "unmatched"
        self.confidence = confidence
        self.reasoning = reasoning

    def to_dict(self) -> dict:
        return {
            "shopify_idx": self.shopify_idx,
            "distributor_idx": self.distributor_idx,
            "match_type": self.match_type,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }


# --- Pass 1: Deterministic matching ---

def match_by_sku(shopify_df: pd.DataFrame, distributor_df: pd.DataFrame) -> list[MatchResult]:
    """Match variants by exact SKU."""
    matches = []

    dist_skus = {}
    for idx, row in distributor_df.iterrows():
        sku = normalize_sku(row.get("sku", ""))
        if sku:
            dist_skus[sku] = idx

    for idx, row in shopify_df.iterrows():
        sku = normalize_sku(row.get("variant_sku", ""))
        if sku and sku in dist_skus:
            matches.append(MatchResult(
                shopify_idx=idx,
                distributor_idx=dist_skus[sku],
                match_type="sku",
                confidence=1.0,
                reasoning=f"Exact SKU match: {sku}",
            ))

    return matches


def match_by_barcode(shopify_df: pd.DataFrame, distributor_df: pd.DataFrame) -> list[MatchResult]:
    """Match variants by barcode/UPC."""
    matches = []

    dist_barcodes = {}
    for idx, row in distributor_df.iterrows():
        barcode = normalize_barcode(row.get("upc", ""))
        if barcode:
            dist_barcodes[barcode] = idx

    for idx, row in shopify_df.iterrows():
        barcode = normalize_barcode(row.get("variant_barcode", ""))
        if barcode and barcode in dist_barcodes:
            matches.append(MatchResult(
                shopify_idx=idx,
                distributor_idx=dist_barcodes[barcode],
                match_type="barcode",
                confidence=1.0,
                reasoning=f"Exact barcode match: {barcode}",
            ))

    return matches


def match_by_flavor_size(
    shopify_df: pd.DataFrame,
    distributor_df: pd.DataFrame,
) -> list[MatchResult]:
    """Match by normalized flavor + size."""
    matches = []

    # Build distributor lookup keyed on (normalized_flavor, normalized_size)
    dist_lookup: dict[tuple[str, str], list[int]] = {}
    for idx, row in distributor_df.iterrows():
        flavor = strip_filler(normalize_units(row.get("flavor", "")))
        size = normalize_units(row.get("size", ""))
        product_name = normalize_units(row.get("product_name", ""))

        # Also try extracting size from product name if size field is empty
        if not size:
            size = extract_size_from_title(product_name)

        key = (flavor, size)
        if flavor and size:
            dist_lookup.setdefault(key, []).append(idx)

    for idx, row in shopify_df.iterrows():
        # Extract flavor from option values
        flavor = ""
        for opt in ["option1_value", "option2_value", "option3_value"]:
            val = str(row.get(opt, "")).strip()
            if val and val.lower() not in ("default title", ""):
                # Heuristic: if it looks like a size, skip it
                if not re.match(r"^\d+\.?\d*\s*(lb|oz|g|kg|ml|l|ct|pc|pk)", val.lower()):
                    flavor = strip_filler(normalize_units(val))
                    break

        # Extract size — check option values and title
        size = ""
        for opt in ["option1_value", "option2_value", "option3_value"]:
            val = str(row.get(opt, "")).strip()
            if re.match(r"^\d+\.?\d*\s*(lb|oz|g|kg|ml|l|ct|pc|pk)", val.lower()):
                size = normalize_units(val)
                break

        if not size:
            size = extract_size_from_title(row.get("title", ""))

        key = (flavor, size)
        if key in dist_lookup and flavor and size:
            matches.append(MatchResult(
                shopify_idx=idx,
                distributor_idx=dist_lookup[key][0],
                match_type="flavor_size",
                confidence=0.9,
                reasoning=f"Flavor+size match: flavor='{flavor}', size='{size}'",
            ))

    return matches


def deterministic_match(
    shopify_df: pd.DataFrame,
    distributor_df: pd.DataFrame,
) -> tuple[list[MatchResult], set[int], set[int]]:
    """Run all deterministic matching passes.

    Returns:
        Tuple of (matches, unmatched_shopify_indices, unmatched_distributor_indices).
    """
    matched_shopify: set[int] = set()
    matched_distributor: set[int] = set()
    all_matches: list[MatchResult] = []

    # Run matching passes in priority order
    for match_fn in [match_by_sku, match_by_barcode, match_by_flavor_size]:
        results = match_fn(shopify_df, distributor_df)
        for result in results:
            if result.shopify_idx not in matched_shopify and result.distributor_idx not in matched_distributor:
                all_matches.append(result)
                matched_shopify.add(result.shopify_idx)
                matched_distributor.add(result.distributor_idx)

    unmatched_shopify = set(shopify_df.index) - matched_shopify
    unmatched_distributor = set(distributor_df.index) - matched_distributor

    return all_matches, unmatched_shopify, unmatched_distributor


# --- Pass 2: Claude API fallback ---

SYSTEM_PROMPT = """You are a product matching assistant for a supplement/candy/consumer goods distributor.

Given a Shopify variant record and a list of candidate distributor products, identify the best match based on flavor, size, and product name.

Return ONLY valid JSON with this exact structure:
{
  "match_index": <index of best match from candidates list, or null if no match>,
  "confidence": <float 0.0-1.0>,
  "reasoning": "<brief explanation>"
}

Rules:
- Match based on product name similarity, flavor/variety, and size/weight
- The same product may use different naming conventions (e.g. "Choc Peanut Butter" vs "Chocolate PB")
- Size representations may differ (e.g. "2.5lb" vs "2.5 Pound" vs "40oz")
- If no candidate is a reasonable match, return match_index: null with low confidence
- Be conservative — only return high confidence (>0.85) for clear matches"""


def _build_claude_prompt(shopify_row: pd.Series, candidates: pd.DataFrame) -> str:
    """Build the user prompt for Claude matching."""
    shopify_info = {
        "title": str(shopify_row.get("title", "")),
        "option1": str(shopify_row.get("option1_value", "")),
        "option2": str(shopify_row.get("option2_value", "")),
        "sku": str(shopify_row.get("variant_sku", "")),
        "price": str(shopify_row.get("variant_price", "")),
    }

    candidate_list = []
    for i, (_, row) in enumerate(candidates.iterrows()):
        candidate_list.append({
            "index": i,
            "product_name": str(row.get("product_name", "")),
            "flavor": str(row.get("flavor", "")),
            "size": str(row.get("size", "")),
            "sku": str(row.get("sku", "")),
            "price": str(row.get("price", "")),
        })

    return (
        f"Shopify variant:\n{json.dumps(shopify_info, indent=2)}\n\n"
        f"Candidate distributor products:\n{json.dumps(candidate_list, indent=2)}"
    )


async def claude_match_batch(
    shopify_df: pd.DataFrame,
    distributor_df: pd.DataFrame,
    unmatched_shopify: set[int],
    unmatched_distributor: set[int],
) -> list[MatchResult]:
    """Use Claude API to match remaining unresolved records.

    Batches unmatched Shopify variants and sends each with up to
    MAX_CLAUDE_BATCH_SIZE candidate distributor products.
    """
    if not ANTHROPIC_API_KEY:
        logger.warning("No ANTHROPIC_API_KEY set — skipping Claude matching")
        return _fallback_unmatched(unmatched_shopify)

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    except Exception as e:
        logger.error("Failed to initialize Anthropic client: %s", e)
        return _fallback_unmatched(unmatched_shopify)

    distributor_candidates = distributor_df.loc[list(unmatched_distributor)]
    results: list[MatchResult] = []
    matched_distributor_indices: set[int] = set()

    for shopify_idx in unmatched_shopify:
        shopify_row = shopify_df.loc[shopify_idx]

        # Get unmatched distributor candidates (limit to batch size)
        available = distributor_candidates[
            ~distributor_candidates.index.isin(matched_distributor_indices)
        ]
        if available.empty:
            results.append(MatchResult(
                shopify_idx=shopify_idx,
                match_type="unmatched",
                confidence=0.0,
                reasoning="No remaining distributor candidates",
            ))
            continue

        batch = available.head(MAX_CLAUDE_BATCH_SIZE)
        prompt = _build_claude_prompt(shopify_row, batch)

        try:
            response = await client.messages.create(
                model=API_MODEL,
                max_tokens=API_MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = response.content[0].text.strip()
            # Extract JSON from response (handle markdown code blocks)
            json_match = re.search(r"\{[^{}]*\}", response_text, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
            else:
                parsed = json.loads(response_text)

            match_index = parsed.get("match_index")
            confidence = float(parsed.get("confidence", 0))
            reasoning = parsed.get("reasoning", "")

            if match_index is not None and 0 <= match_index < len(batch):
                dist_idx = batch.index[match_index]
                results.append(MatchResult(
                    shopify_idx=shopify_idx,
                    distributor_idx=dist_idx,
                    match_type="claude",
                    confidence=confidence,
                    reasoning=reasoning,
                ))
                if confidence >= MATCH_AUTO_THRESHOLD:
                    matched_distributor_indices.add(dist_idx)
            else:
                results.append(MatchResult(
                    shopify_idx=shopify_idx,
                    match_type="unmatched",
                    confidence=confidence,
                    reasoning=reasoning or "Claude found no match",
                ))

        except Exception as e:
            logger.error("Claude API error for shopify_idx %s: %s", shopify_idx, e)
            results.append(MatchResult(
                shopify_idx=shopify_idx,
                match_type="unmatched",
                confidence=0.0,
                reasoning=f"Claude API error: {e}",
            ))

    return results


def _fallback_unmatched(unmatched_shopify: set[int]) -> list[MatchResult]:
    """Create fallback results when Claude API is unavailable."""
    return [
        MatchResult(
            shopify_idx=idx,
            match_type="unmatched",
            confidence=0.0,
            reasoning="Claude API unavailable — flagged for manual review",
        )
        for idx in unmatched_shopify
    ]


# --- Orchestrator ---

async def run_matching(
    shopify_df: pd.DataFrame,
    distributor_df: pd.DataFrame,
) -> dict:
    """Run the full two-pass matching pipeline.

    Returns a dict with categorized results:
      - matched: high-confidence matches (deterministic + claude auto)
      - to_delete: Shopify variants with no distributor match
      - to_add: distributor products with no Shopify match
      - needs_review: low-confidence Claude matches for manual review
      - claude_unavailable: True if Claude API was not available
    """
    # Pass 1: Deterministic
    det_matches, unmatched_shopify, unmatched_distributor = deterministic_match(
        shopify_df, distributor_df
    )

    # Pass 2: Claude fallback
    claude_unavailable = False
    claude_results = []

    if unmatched_shopify and unmatched_distributor:
        if not ANTHROPIC_API_KEY:
            claude_unavailable = True
            claude_results = _fallback_unmatched(unmatched_shopify)
        else:
            claude_results = await claude_match_batch(
                shopify_df, distributor_df, unmatched_shopify, unmatched_distributor
            )
            # Check if all claude results are API errors — guard against
            # all() returning True on an empty iterable
            unmatched_claude = [r for r in claude_results if r.match_type == "unmatched"]
            if unmatched_claude and all(
                r.reasoning.startswith("Claude API") for r in unmatched_claude
            ):
                claude_unavailable = True
    elif unmatched_shopify:
        claude_results = _fallback_unmatched(unmatched_shopify)

    # Categorize results
    matched = []
    needs_review = []
    to_delete_indices = set()

    # All deterministic matches are high confidence
    for m in det_matches:
        matched.append(m)

    # Categorize Claude results
    matched_dist_from_claude: set[int] = set()
    for r in claude_results:
        if r.match_type == "claude" and r.confidence >= MATCH_AUTO_THRESHOLD:
            matched.append(r)
            if r.distributor_idx is not None:
                matched_dist_from_claude.add(r.distributor_idx)
        elif r.match_type == "claude" and r.confidence >= MATCH_REVIEW_THRESHOLD:
            needs_review.append(r)
            if r.distributor_idx is not None:
                matched_dist_from_claude.add(r.distributor_idx)
        else:
            to_delete_indices.add(r.shopify_idx)

    # Distributor products not matched at all = to_add
    all_matched_dist = {m.distributor_idx for m in matched if m.distributor_idx is not None}
    all_matched_dist |= matched_dist_from_claude
    to_add_indices = unmatched_distributor - all_matched_dist

    return {
        "matched": [m.to_dict() for m in matched],
        "to_delete": list(to_delete_indices),
        "to_add": list(to_add_indices),
        "needs_review": [r.to_dict() for r in needs_review],
        "claude_unavailable": claude_unavailable,
    }
