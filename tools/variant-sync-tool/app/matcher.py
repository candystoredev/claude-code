"""Matching logic for syncing Shopify variants with distributor products.

Two-pass approach:
  Pass 1 — Deterministic matching: option-value-in-name, SKU, barcode.
  Pass 2 — Claude API fallback for unresolved records.

Matching is scoped per Shopify product (handle group).  Before matching,
distributor rows are filtered to only those whose unit size (parsed from
price_inner / price_case columns) matches the Shopify product's title size.
"""

import json
import logging
import re
import unicodedata

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


def strip_accents(text: str) -> str:
    """Remove accent marks from characters (e.g. 'ñ' -> 'n')."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_text(text: str) -> str:
    """Lowercase, strip accents, strip punctuation, collapse whitespace."""
    text = strip_accents(str(text)).lower().strip()
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
    """Extract size/weight pattern from a product title string.

    Returns a normalized size like '10lb' or '' if none found.
    """
    title = str(title).lower()
    match = re.search(
        r"(\d+\.?\d*)\s*"
        r"(lb|lbs|pound|pounds|oz|ounce|ounces|g|gram|grams|"
        r"kg|kilogram|kilograms|ml|milliliter|l|liter|"
        r"fl\s*oz|ct|count|pc|piece|pk|pack)\b",
        title,
    )
    if match:
        return normalize_size_value(normalize_units(match.group(0)))
    return ""


def normalize_size_value(size_str: str) -> str:
    """Normalize a size string so '10.00lb' and '10lb' compare equal.

    Strips trailing decimal zeros from the numeric portion.
    """
    size_str = normalize_units(size_str)
    m = re.match(r"(\d+\.?\d*)(.*)", size_str)
    if m:
        try:
            num = float(m.group(1))
            num_str = str(int(num)) if num == int(num) else f"{num:g}"
            return f"{num_str}{m.group(2)}"
        except ValueError:
            pass
    return size_str


def parse_size_from_price_field(price_text: str) -> str:
    """Extract unit size from a distributor price field.

    Handles formats like '5.00lb @ $25.47/bag' or '10.00lb @ $50.00/case'.
    Returns a normalized size like '5lb' or '' if none found.
    """
    text = str(price_text).lower().strip()
    match = re.match(
        r"(\d+\.?\d*)\s*"
        r"(lb|lbs|pound|pounds|oz|ounce|ounces|g|gram|grams|"
        r"kg|kilogram|kilograms|ml|milliliter|l|liter|"
        r"fl\s*oz|ct|count|pc|piece|pk|pack)\b",
        text,
    )
    if match:
        return normalize_size_value(normalize_units(match.group(0)))
    return ""


def normalize_sku(sku: str) -> str:
    """Normalize a SKU for comparison.

    Strips the common ND-style prefix (ND-, NDD-, NDDD-, etc.) that
    appears on Shopify SKUs but not on distributor SKUs (or vice versa).
    """
    text = str(sku).lower().strip()
    # Strip ND+ prefix (e.g. 'ND-12345' -> '12345')
    text = re.sub(r"^n+d+-", "", text)
    return re.sub(r"[^a-z0-9]", "", text)


def normalize_barcode(barcode: str) -> str:
    """Normalize a barcode/UPC — strip non-digits, remove leading zeros."""
    digits = re.sub(r"[^0-9]", "", str(barcode).strip())
    return digits.lstrip("0") if digits else ""


# --- Size filtering ---

def get_distributor_sizes(row: pd.Series) -> set[str]:
    """Get all unit sizes a distributor product is offered in.

    Parses sizes from price_inner, price_case, size, and product_name.
    """
    sizes: set[str] = set()

    for field in ("price_inner", "price_case"):
        s = parse_size_from_price_field(row.get(field, ""))
        if s:
            sizes.add(s)

    # Fallback: explicit size column
    size_val = normalize_units(str(row.get("size", "")).strip())
    if size_val:
        s = normalize_size_value(size_val)
        if s:
            sizes.add(s)

    # Fallback: extract from product name
    name_size = extract_size_from_title(row.get("product_name", ""))
    if name_size:
        sizes.add(name_size)

    return sizes


def filter_distributor_by_size(
    distributor_df: pd.DataFrame,
    target_size: str,
    exclude: set[int] | None = None,
) -> pd.DataFrame:
    """Filter distributor rows to those matching the target unit size.

    If target_size is empty, returns all rows (minus excluded indices).
    """
    if exclude is None:
        exclude = set()

    mask = ~distributor_df.index.isin(exclude)

    if not target_size:
        return distributor_df[mask]

    def row_matches_size(row: pd.Series) -> bool:
        return target_size in get_distributor_sizes(row)

    size_mask = distributor_df.apply(row_matches_size, axis=1)
    return distributor_df[mask & size_mask]


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
        self.match_type = match_type
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

def _option_matches_name(option_value: str, distributor_name: str) -> bool:
    """Check if a Shopify option value matches a distributor product name.

    Handles accent differences (Piña ↔ Pina) and compound words
    (Passionfruit ↔ Passion Fruit) by trying both substring matching
    and space-collapsed matching.
    """
    opt = normalize_text(option_value)
    name = normalize_text(distributor_name)

    if not opt or not name:
        return False

    # Direct substring match
    if opt in name:
        return True

    # Space-collapsed match (handles "Passion Fruit" vs "Passionfruit")
    opt_collapsed = opt.replace(" ", "")
    name_collapsed = name.replace(" ", "")
    if opt_collapsed in name_collapsed:
        return True

    return False


def match_by_option_in_name(
    shopify_df: pd.DataFrame,
    distributor_df: pd.DataFrame,
) -> list[MatchResult]:
    """Match by checking if Shopify option value appears in distributor name.

    This is the primary matching strategy for flavor/color variants.
    For example, Shopify Option1 Value = "Bubble Gum" matches distributor
    Name = "JELLY BELLY BUBBLE GUM JELLY BEANS".

    Uses optimal assignment: when multiple Shopify options compete for the
    same distributor row (e.g. "Lemon" and "Lemon Lime" both match
    "JELLY BELLY LEMON LIME JELLY BEANS"), the more specific match wins
    (longer option text = higher specificity).
    """
    # Phase 1: Build all candidate edges with scores.
    # candidates[s_idx] = [(d_idx, score), ...] sorted by score descending
    candidates: dict[int, list[tuple[int, float]]] = {}

    for s_idx, s_row in shopify_df.iterrows():
        option_val = str(s_row.get("option1_value", "")).strip()
        if not option_val or option_val.lower() in ("default title", ""):
            continue

        opt_len = len(normalize_text(option_val).replace(" ", ""))
        edges: list[tuple[int, float]] = []

        for d_idx, d_row in distributor_df.iterrows():
            name = str(d_row.get("product_name", "")).strip()
            if not name:
                continue

            if _option_matches_name(option_val, name):
                name_len = len(normalize_text(name).replace(" ", ""))
                score = opt_len / name_len if name_len else 0.0
                edges.append((d_idx, score))

        if edges:
            edges.sort(key=lambda x: -x[1])
            candidates[s_idx] = edges

    # Phase 2: Resolve conflicts — when multiple Shopify variants want the
    # same distributor row, the one with the longer (more specific) option
    # text gets priority.  Losers fall back to their next-best candidate.
    claimed_dist: dict[int, int] = {}    # d_idx -> s_idx that claimed it
    assignments: dict[int, int] = {}      # s_idx -> d_idx

    # Process Shopify variants in order of specificity (longest option first)
    # so more specific options claim their best match before shorter ones.
    specificity_order = sorted(
        candidates.keys(),
        key=lambda s: len(normalize_text(
            str(shopify_df.loc[s].get("option1_value", ""))
        ).replace(" ", "")),
        reverse=True,
    )

    for s_idx in specificity_order:
        for d_idx, _score in candidates[s_idx]:
            if d_idx not in claimed_dist:
                claimed_dist[d_idx] = s_idx
                assignments[s_idx] = d_idx
                break

    matches = []
    for s_idx, d_idx in assignments.items():
        option_val = str(shopify_df.loc[s_idx].get("option1_value", "")).strip()
        matches.append(MatchResult(
            shopify_idx=s_idx,
            distributor_idx=d_idx,
            match_type="name",
            confidence=0.95,
            reasoning=f"Option '{option_val}' found in distributor name",
        ))

    return matches


def match_by_sku(shopify_df: pd.DataFrame, distributor_df: pd.DataFrame) -> list[MatchResult]:
    """Match variants by normalized SKU (with ND-prefix stripping)."""
    matches = []

    dist_skus: dict[str, int] = {}
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

    dist_barcodes: dict[str, int] = {}
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


def deterministic_match(
    shopify_df: pd.DataFrame,
    distributor_df: pd.DataFrame,
) -> tuple[list[MatchResult], set[int], set[int]]:
    """Run all deterministic matching passes.

    Priority order:
      1. SKU match (exact identifier — most reliable)
      2. Barcode match (exact identifier, only fires if UPC columns available)
      3. Option value in distributor name (fuzzy — used for flavor/color)

    SKU/barcode run first so they claim rows before name matching, preventing
    ambiguous name matches (e.g. "Lemon" stealing the "Sunkist Lemon" row
    that should go to "Lemon - Sunkist" via SKU).

    Returns:
        Tuple of (matches, unmatched_shopify_indices, unmatched_distributor_indices).
    """
    matched_shopify: set[int] = set()
    matched_distributor: set[int] = set()
    all_matches: list[MatchResult] = []

    for match_fn in [match_by_sku, match_by_barcode, match_by_option_in_name]:
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

SYSTEM_PROMPT = """You are a product matching assistant for a candy/supplement/consumer goods distributor.

Given a Shopify variant record and a list of candidate distributor products, identify the best match based on flavor/color name.

The Shopify variant has an option value (typically a flavor or color like "Bubble Gum" or "Very Cherry").
The distributor products have names that embed the flavor/color (like "JELLY BELLY BUBBLE GUM JELLY BEANS").

Your job: find the distributor product whose name best matches the Shopify variant's flavor/color option.

Return ONLY valid JSON with this exact structure:
{
  "match_index": <index of best match from candidates list, or null if no match>,
  "confidence": <float 0.0-1.0>,
  "reasoning": "<brief explanation>"
}

Rules:
- Focus on matching the flavor/color/variety — the option value should appear (possibly abbreviated or respelled) in the distributor product name
- Handle different naming conventions: "Choc PB" = "Chocolate Peanut Butter", "Straw" = "Strawberry"
- Handle accent differences: "Piña Colada" = "Pina Colada"
- Handle compound words: "Passionfruit" = "Passion Fruit"
- SKU can be a supporting clue but is NOT reliable on its own (distributors change SKUs)
- If no candidate is a reasonable match, return match_index: null with low confidence
- Be conservative — only return high confidence (>0.85) for clear matches"""


def _build_claude_prompt(shopify_row: pd.Series, candidates: pd.DataFrame) -> str:
    """Build the user prompt for Claude matching."""
    shopify_info = {
        "title": str(shopify_row.get("title", "")),
        "option1": str(shopify_row.get("option1_value", "")),
        "option2": str(shopify_row.get("option2_value", "")),
        "sku": str(shopify_row.get("variant_sku", "")),
    }

    candidate_list = []
    for i, (_, row) in enumerate(candidates.iterrows()):
        candidate_list.append({
            "index": i,
            "product_name": str(row.get("product_name", "")),
            "sku": str(row.get("sku", "")),
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
    """Use Claude API to match remaining unresolved records."""
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
    """Run the full matching pipeline, scoped per Shopify product (handle).

    For each Shopify product handle:
      1. Extract the unit size from the product title.
      2. Filter distributor rows to those offered in that unit size.
      3. Run deterministic matching (option-in-name, SKU, barcode).
      4. Run Claude fallback for any remaining unmatched variants.

    Returns a dict with categorized results:
      - matched: high-confidence matches
      - to_delete: Shopify variants with no distributor match
      - to_add: distributor products with no Shopify match
      - needs_review: low-confidence Claude matches
      - claude_unavailable: True if Claude API was not available
    """
    all_matched: list[MatchResult] = []
    all_to_delete: set[int] = set()
    all_needs_review: list[MatchResult] = []
    global_matched_distributor: set[int] = set()
    in_scope_distributor: set[int] = set()  # distributor rows that matched at least one product's unit size
    claude_unavailable = False

    # Group Shopify variants by handle (each handle = one product)
    handles = shopify_df.groupby("handle", sort=False)

    for handle, group in handles:
        # Extract unit size from the product title (same for all rows in group)
        title = str(group.iloc[0]["title"])
        target_size = extract_size_from_title(title)

        # Filter distributor rows to matching unit size
        filtered_dist = filter_distributor_by_size(
            distributor_df, target_size, exclude=global_matched_distributor
        )

        if filtered_dist.empty:
            # No distributor products match this size — all variants are deletions
            all_to_delete.update(group.index.tolist())
            continue

        # Track which distributor rows are in scope for at least one product
        in_scope_distributor.update(filtered_dist.index.tolist())

        # Pass 1: Deterministic matching within this handle group
        det_matches, unmatched_shopify, unmatched_dist = deterministic_match(
            group, filtered_dist
        )

        for m in det_matches:
            all_matched.append(m)
            if m.distributor_idx is not None:
                global_matched_distributor.add(m.distributor_idx)

        # Pass 2: Claude fallback for unmatched variants in this group
        if unmatched_shopify and unmatched_dist:
            if not ANTHROPIC_API_KEY:
                claude_unavailable = True
                claude_results = _fallback_unmatched(unmatched_shopify)
            else:
                claude_results = await claude_match_batch(
                    group, filtered_dist, unmatched_shopify, unmatched_dist
                )
                unmatched_claude = [r for r in claude_results if r.match_type == "unmatched"]
                if unmatched_claude and all(
                    r.reasoning.startswith("Claude API") for r in unmatched_claude
                ):
                    claude_unavailable = True

            for r in claude_results:
                if r.match_type == "claude" and r.confidence >= MATCH_AUTO_THRESHOLD:
                    all_matched.append(r)
                    if r.distributor_idx is not None:
                        global_matched_distributor.add(r.distributor_idx)
                elif r.match_type == "claude" and r.confidence >= MATCH_REVIEW_THRESHOLD:
                    all_needs_review.append(r)
                    if r.distributor_idx is not None:
                        global_matched_distributor.add(r.distributor_idx)
                else:
                    all_to_delete.add(r.shopify_idx)
        elif unmatched_shopify:
            all_to_delete.update(unmatched_shopify)

    # Safety net: don't flag a Shopify variant for deletion if its SKU
    # exists anywhere in the distributor data — that means the product is
    # still offered, we just failed to match it via name/Claude.
    dist_sku_set: set[str] = set()
    for _, row in distributor_df.iterrows():
        sku = normalize_sku(row.get("sku", ""))
        if sku:
            dist_sku_set.add(sku)

    safe_to_delete: list[int] = []
    rescued_to_review: list[MatchResult] = []
    for s_idx in all_to_delete:
        shopify_sku = normalize_sku(shopify_df.loc[s_idx].get("variant_sku", ""))
        if shopify_sku and shopify_sku in dist_sku_set:
            # SKU still exists in distributor data — don't delete, flag for review
            rescued_to_review.append(MatchResult(
                shopify_idx=s_idx,
                match_type="review",
                confidence=0.0,
                reasoning="SKU found in distributor data but name match failed — needs manual review",
            ))
        else:
            safe_to_delete.append(s_idx)

    all_needs_review.extend(rescued_to_review)

    # Distributor products not matched to any Shopify variant.
    # Only suggest additions from rows whose unit size matched at least one
    # Shopify product — otherwise we'd suggest completely unrelated products
    # (e.g. 8ct window decals for a 10lb candy product).
    all_matched_dist = {m.distributor_idx for m in all_matched if m.distributor_idx is not None}
    all_matched_dist |= global_matched_distributor
    to_add_indices = in_scope_distributor - all_matched_dist

    return {
        "matched": [m.to_dict() for m in all_matched],
        "to_delete": safe_to_delete,
        "to_add": list(to_add_indices),
        "needs_review": [r.to_dict() for r in all_needs_review],
        "claude_unavailable": claude_unavailable,
    }
