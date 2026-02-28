"""Generate Matrixify-compatible Excel output files."""

import io
import re

import pandas as pd

# Matrixify output columns in standard order
MATRIXIFY_COLUMNS = [
    "Command",
    "Handle",
    "Title",
    "Option1 Name",
    "Option1 Value",
    "Option2 Name",
    "Option2 Value",
    "Option3 Name",
    "Option3 Value",
    "Variant SKU",
    "Variant Price",
    "Variant Compare At Price",
    "Variant Barcode",
    "Variant Grams",
    "Variant Weight",
    "Variant Weight Unit",
    "Variant Inventory Qty",
    "Image Src",
    "Variant Image",
    "Status",
]


def _generate_handle(title: str) -> str:
    """Generate a Shopify-style handle from a product title."""
    handle = title.lower().strip()
    handle = re.sub(r"[^a-z0-9\s-]", "", handle)
    handle = re.sub(r"\s+", "-", handle)
    handle = re.sub(r"-+", "-", handle)
    return handle.strip("-")


def build_delete_row(shopify_row: pd.Series) -> dict:
    """Build a Matrixify DELETE row from a Shopify variant."""
    return {
        "Command": "DELETE",
        "Handle": shopify_row.get("handle", ""),
        "Title": shopify_row.get("title", ""),
        "Option1 Name": shopify_row.get("option1_name", ""),
        "Option1 Value": shopify_row.get("option1_value", ""),
        "Option2 Name": shopify_row.get("option2_name", ""),
        "Option2 Value": shopify_row.get("option2_value", ""),
        "Option3 Name": shopify_row.get("option3_name", ""),
        "Option3 Value": shopify_row.get("option3_value", ""),
        "Variant SKU": shopify_row.get("variant_sku", ""),
        "Variant Price": shopify_row.get("variant_price", ""),
        "Variant Compare At Price": shopify_row.get("variant_compare_at_price", ""),
        "Variant Barcode": shopify_row.get("variant_barcode", ""),
        "Variant Grams": shopify_row.get("variant_grams", ""),
        "Variant Weight": shopify_row.get("variant_weight", ""),
        "Variant Weight Unit": shopify_row.get("variant_weight_unit", ""),
        "Variant Inventory Qty": shopify_row.get("variant_inventory_qty", ""),
        "Image Src": shopify_row.get("image_src", ""),
        "Variant Image": shopify_row.get("variant_image", ""),
        "Status": shopify_row.get("status", ""),
    }


def build_new_row(
    distributor_row: pd.Series,
    existing_handles: set[str] | None = None,
) -> dict:
    """Build a Matrixify NEW/MERGE row from a distributor product.

    Uses MERGE if the parent product handle already exists in Shopify,
    otherwise uses NEW.
    """
    product_name = str(distributor_row.get("product_name", "")).strip()
    size = str(distributor_row.get("size", "")).strip()

    title = product_name
    if size and size.lower() not in product_name.lower():
        title = f"{product_name} {size}"

    handle = _generate_handle(product_name)
    command = "MERGE" if existing_handles and handle in existing_handles else "NEW"

    return {
        "Command": command,
        "Handle": handle,
        "Title": title,
        "Option1 Name": "Flavor" if distributor_row.get("flavor", "") else "",
        "Option1 Value": str(distributor_row.get("flavor", "")).strip(),
        "Option2 Name": "Size" if size else "",
        "Option2 Value": size,
        "Option3 Name": "",
        "Option3 Value": "",
        "Variant SKU": str(distributor_row.get("sku", "")).strip(),
        "Variant Price": str(distributor_row.get("price", "")).strip(),
        "Variant Compare At Price": "",
        "Variant Barcode": str(distributor_row.get("upc", "")).strip(),
        "Variant Grams": "",
        "Variant Weight": "",
        "Variant Weight Unit": "",
        "Variant Inventory Qty": "",
        "Image Src": str(distributor_row.get("image_url", "")).strip(),
        "Variant Image": "",
        "Status": "active",
    }


def build_matched_row(shopify_row: pd.Series) -> dict:
    """Build a Matrixify row for a matched variant (informational)."""
    row = build_delete_row(shopify_row)
    row["Command"] = ""
    return row


def generate_output(
    shopify_df: pd.DataFrame,
    distributor_df: pd.DataFrame,
    match_results: dict,
) -> bytes:
    """Generate a Matrixify-compatible Excel file from match results.

    Args:
        shopify_df: Parsed Shopify DataFrame.
        distributor_df: Parsed distributor DataFrame.
        match_results: Dict from matcher.run_matching().

    Returns:
        Excel file content as bytes.
    """
    rows = []

    # Collect existing Shopify handles for MERGE detection
    existing_handles = set()
    for _, row in shopify_df.iterrows():
        handle = str(row.get("handle", "")).strip().lower()
        if handle:
            existing_handles.add(handle)

    # MATCHED rows (informational)
    for match in match_results.get("matched", []):
        shopify_idx = match["shopify_idx"]
        if shopify_idx is not None and shopify_idx in shopify_df.index:
            rows.append(build_matched_row(shopify_df.loc[shopify_idx]))

    # DELETE rows
    for shopify_idx in match_results.get("to_delete", []):
        if shopify_idx in shopify_df.index:
            rows.append(build_delete_row(shopify_df.loc[shopify_idx]))

    # NEW/MERGE rows
    for dist_idx in match_results.get("to_add", []):
        if dist_idx in distributor_df.index:
            rows.append(build_new_row(distributor_df.loc[dist_idx], existing_handles))

    # REVIEW rows — include as matched but with a note
    for review in match_results.get("needs_review", []):
        shopify_idx = review["shopify_idx"]
        if shopify_idx is not None and shopify_idx in shopify_df.index:
            row = build_matched_row(shopify_df.loc[shopify_idx])
            row["Command"] = "REVIEW"
            rows.append(row)

    if not rows:
        # Empty output — create a header-only file
        output_df = pd.DataFrame(columns=MATRIXIFY_COLUMNS)
    else:
        output_df = pd.DataFrame(rows)
        # Ensure all Matrixify columns are present
        for col in MATRIXIFY_COLUMNS:
            if col not in output_df.columns:
                output_df[col] = ""
        output_df = output_df[MATRIXIFY_COLUMNS]

    # Write to Excel in memory
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        output_df.to_excel(writer, index=False, sheet_name="Products")
    buffer.seek(0)

    return buffer.getvalue()
