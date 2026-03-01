"""Parse and normalize Shopify (Matrixify) and distributor files."""

import io
import re

import pandas as pd


# --- Shopify / Matrixify column mappings ---

SHOPIFY_COLUMNS = {
    "handle": "Handle",
    "title": "Title",
    "option1_name": "Option1 Name",
    "option1_value": "Option1 Value",
    "option2_name": "Option2 Name",
    "option2_value": "Option2 Value",
    "option3_name": "Option3 Name",
    "option3_value": "Option3 Value",
    "variant_sku": "Variant SKU",
    "variant_price": "Variant Price",
    "variant_barcode": "Variant Barcode",
    "status": "Status",
    "variant_compare_at_price": "Variant Compare At Price",
    "image_src": "Image Src",
    "variant_image": "Variant Image",
    "variant_grams": "Variant Grams",
    "variant_inventory_qty": "Variant Inventory Qty",
    "variant_weight": "Variant Weight",
    "variant_weight_unit": "Variant Weight Unit",
}

# Patterns used to auto-detect distributor columns.
# Order matters: fields listed earlier claim columns first, preventing
# later fields from using them.  Within each field the patterns are in
# priority order (earlier pattern → higher confidence score).
DISTRIBUTOR_FIELD_PATTERNS = {
    "product_name": [
        r"product[\s_-]*name",
        r"^name$",
        r"item[\s_-]*name",
        r"product[\s_-]*title",
        r"description",
        r"item[\s_-]*description",
    ],
    "flavor": [
        r"flavou?r",
        r"variety",
        r"scent",
        r"option[\s_-]*1",
        r"variant",
    ],
    "size": [
        r"size",
        r"weight",
        r"unit[\s_-]*size",
        r"net[\s_-]*weight",
        r"pack[\s_-]*size",
        r"option[\s_-]*2",
    ],
    # price_inner and price_case must come before generic "price" so they
    # claim their columns first; otherwise "price" would grab them.
    "price_inner": [
        r"price[\s_-]*inner",
        r"inner[\s_-]*price",
    ],
    "price_case": [
        r"price[\s_-]*case",
        r"case[\s_-]*price",
    ],
    "price": [
        r"price",
        r"cost",
        r"msrp",
        r"retail",
        r"wholesale",
        r"unit[\s_-]*price",
    ],
    "sku": [
        r"sku",
        r"item[\s_-]*number",
        r"item[\s_-]*#",
        r"item[\s_-]*no",
        r"product[\s_-]*code",
        r"catalog[\s_-]*#",
    ],
    "manufacturer": [
        r"manufacturer",
        r"brand",
        r"vendor",
        r"maker",
        r"company",
    ],
}


def read_file(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Read an uploaded file (Excel or CSV) into a DataFrame."""
    buffer = io.BytesIO(file_bytes)
    lower = filename.lower()

    if lower.endswith(".xlsx"):
        df = pd.read_excel(buffer, engine="openpyxl")
    elif lower.endswith(".xls"):
        # openpyxl doesn't support legacy .xls — let pandas pick the engine
        df = pd.read_excel(buffer)
    elif lower.endswith(".csv"):
        buffer_text = io.StringIO(file_bytes.decode("utf-8-sig"))
        df = pd.read_csv(buffer_text)
    else:
        raise ValueError(f"Unsupported file type: {filename}. Use .xlsx, .xls, or .csv")

    # Drop fully empty rows
    df = df.dropna(how="all").reset_index(drop=True)
    return df


def parse_shopify_file(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Parse a Shopify/Matrixify export file and normalize columns.

    Returns a DataFrame with standardized internal column names.
    """
    df = read_file(file_bytes, filename)
    original_cols = list(df.columns)

    # Build reverse lookup: lowercase original -> original column name
    col_map = {c.strip().lower(): c for c in original_cols}

    result = pd.DataFrame()
    result["_original_index"] = df.index

    for internal_name, matrixify_name in SHOPIFY_COLUMNS.items():
        lookup = matrixify_name.strip().lower()
        if lookup in col_map:
            result[internal_name] = df[col_map[lookup]].fillna("").astype(str)
        else:
            result[internal_name] = ""

    # Build a composite label for display
    result["_display_label"] = result.apply(_build_shopify_label, axis=1)

    return result


def _build_shopify_label(row: pd.Series) -> str:
    """Build a human-readable label for a Shopify variant."""
    parts = []
    title = str(row.get("title", "")).strip()
    if title:
        parts.append(title)

    for opt_key in ["option1_value", "option2_value", "option3_value"]:
        val = str(row.get(opt_key, "")).strip()
        if val and val.lower() not in ("default title", ""):
            parts.append(val)

    sku = str(row.get("variant_sku", "")).strip()
    if sku:
        parts.append(f"[{sku}]")

    return " / ".join(parts) if parts else "(unknown variant)"


def auto_detect_columns(df: pd.DataFrame) -> tuple[dict[str, str], dict[str, float]]:
    """Auto-detect distributor column mappings.

    Returns a tuple of ({field_name: detected_column_name}, {field_name: confidence}).
    """
    columns = list(df.columns)
    mappings: dict[str, str] = {}
    confidence: dict[str, float] = {}
    claimed_columns: set[str] = set()

    for field, patterns in DISTRIBUTOR_FIELD_PATTERNS.items():
        best_match = None
        best_score = 0

        for col in columns:
            if col in claimed_columns:
                continue
            col_lower = str(col).strip().lower()
            for i, pattern in enumerate(patterns):
                if re.search(pattern, col_lower, re.IGNORECASE):
                    # Earlier patterns = higher confidence
                    score = len(patterns) - i
                    if score > best_score:
                        best_score = score
                        best_match = col

        if best_match:
            mappings[field] = best_match
            confidence[field] = min(1.0, best_score / len(patterns))
            claimed_columns.add(best_match)

    return mappings, confidence


def parse_distributor_file(
    file_bytes: bytes,
    filename: str,
    column_mappings: dict | None = None,
    manufacturer_filter: str | None = None,
) -> tuple[pd.DataFrame, dict, dict]:
    """Parse a distributor offerings file.

    Args:
        file_bytes: Raw file content.
        filename: Original filename for format detection.
        column_mappings: Optional pre-specified column mappings.
        manufacturer_filter: Optional manufacturer name to filter by.

    Returns:
        Tuple of (normalized DataFrame, final mappings used, detection confidence).
    """
    df = read_file(file_bytes, filename)

    if column_mappings:
        mappings = column_mappings
        confidence = {k: 1.0 for k in column_mappings}
    else:
        mappings, confidence = auto_detect_columns(df)

    result = pd.DataFrame()
    result["_original_index"] = df.index

    for field in DISTRIBUTOR_FIELD_PATTERNS:
        if field in mappings and mappings[field] in df.columns:
            result[field] = df[mappings[field]].fillna("").astype(str)
        else:
            result[field] = ""

    # Apply manufacturer filter if provided
    if manufacturer_filter and "manufacturer" in mappings:
        filter_lower = manufacturer_filter.strip().lower()
        mask = result["manufacturer"].str.lower().str.contains(filter_lower, na=False)
        result = result[mask].reset_index(drop=True)

    # Build display label
    result["_display_label"] = result.apply(_build_distributor_label, axis=1)

    return result, mappings, confidence


def _build_distributor_label(row: pd.Series) -> str:
    """Build a human-readable label for a distributor product."""
    parts = []

    name = str(row.get("product_name", "")).strip()
    if name:
        parts.append(name)

    flavor = str(row.get("flavor", "")).strip()
    if flavor:
        parts.append(flavor)

    size = str(row.get("size", "")).strip()
    if size:
        parts.append(size)

    sku = str(row.get("sku", "")).strip()
    if sku:
        parts.append(f"[{sku}]")

    return " / ".join(parts) if parts else "(unknown product)"


def get_detection_status(confidence: dict) -> dict:
    """Summarize auto-detection results for UI display.

    Returns a dict with 'detected', 'missing', and 'needs_review' lists.
    """
    required = ["product_name"]
    helpful = ["sku", "price", "price_inner", "price_case", "manufacturer"]

    detected = []
    missing = []
    needs_review = []

    for field in required + helpful:
        if field not in confidence:
            missing.append(field)
        elif confidence[field] < 0.5:
            needs_review.append(field)
        else:
            detected.append(field)

    return {
        "detected": detected,
        "missing": missing,
        "needs_review": needs_review,
        "is_confident": len(missing) == 0 and len(needs_review) == 0,
        "has_required": all(f in confidence for f in required),
    }
