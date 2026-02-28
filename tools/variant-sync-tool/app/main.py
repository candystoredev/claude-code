"""Variant Sync Tool — FastAPI application."""

import logging
import uuid

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import MAX_UPLOAD_SIZE_MB
from app.matcher import run_matching
from app.output import generate_output
from app.parser import (
    get_detection_status,
    parse_distributor_file,
    parse_shopify_file,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Variant Sync Tool")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# In-memory store for session results (stateless per-request, keyed by session ID)
_sessions: dict[str, dict] = {}
MAX_SESSIONS = 50


def _cleanup_sessions():
    """Evict oldest sessions if over limit."""
    while len(_sessions) > MAX_SESSIONS:
        oldest_key = next(iter(_sessions))
        del _sessions[oldest_key]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the upload form."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload", response_class=HTMLResponse)
async def upload_and_process(
    request: Request,
    shopify_file: UploadFile = File(...),
    distributor_file: UploadFile = File(...),
    manufacturer_filter: str = Form(""),
):
    """Handle file uploads, parse, match, and render results."""
    errors = []

    # Validate file types
    for f, label in [(shopify_file, "Shopify"), (distributor_file, "Distributor")]:
        if not f.filename:
            errors.append(f"{label} file is required.")
            continue
        ext = f.filename.lower().rsplit(".", 1)[-1] if "." in f.filename else ""
        if ext not in ("xlsx", "xls", "csv"):
            errors.append(f"{label} file must be .xlsx, .xls, or .csv (got .{ext})")

    if errors:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "errors": errors,
        })

    # Read file contents
    try:
        shopify_bytes = await shopify_file.read()
        distributor_bytes = await distributor_file.read()
    except Exception as e:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "errors": [f"Error reading files: {e}"],
        })

    # Check file sizes
    max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    for content, label in [(shopify_bytes, "Shopify"), (distributor_bytes, "Distributor")]:
        if len(content) > max_bytes:
            errors.append(f"{label} file exceeds {MAX_UPLOAD_SIZE_MB}MB limit.")

    if errors:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "errors": errors,
        })

    # Parse files
    try:
        shopify_df = parse_shopify_file(shopify_bytes, shopify_file.filename)
    except Exception as e:
        logger.exception("Failed to parse Shopify file")
        return templates.TemplateResponse("index.html", {
            "request": request,
            "errors": [f"Failed to parse Shopify file: {e}"],
        })

    try:
        distributor_df, mappings, confidence = parse_distributor_file(
            distributor_bytes,
            distributor_file.filename,
            manufacturer_filter=manufacturer_filter.strip() or None,
        )
    except Exception as e:
        logger.exception("Failed to parse distributor file")
        return templates.TemplateResponse("index.html", {
            "request": request,
            "errors": [f"Failed to parse distributor file: {e}"],
        })

    detection_status = get_detection_status(confidence)

    # Check if column mapping is needed
    if not detection_status["has_required"]:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "errors": [
                "Could not auto-detect required columns in the distributor file. "
                f"Missing: {', '.join(detection_status['missing'])}. "
                "Please ensure your file has columns for: product name, and ideally "
                "flavor, size, SKU, UPC, and price."
            ],
            "detection_status": detection_status,
            "distributor_columns": list(confidence.keys()),
        })

    # Run matching
    try:
        match_results = await run_matching(shopify_df, distributor_df)
    except Exception as e:
        logger.exception("Matching failed")
        return templates.TemplateResponse("index.html", {
            "request": request,
            "errors": [f"Matching failed: {e}"],
        })

    # Generate output file
    try:
        output_bytes = generate_output(shopify_df, distributor_df, match_results)
    except Exception as e:
        logger.exception("Output generation failed")
        return templates.TemplateResponse("index.html", {
            "request": request,
            "errors": [f"Output generation failed: {e}"],
        })

    # Store only the output file bytes for download — avoid holding
    # DataFrames in memory across requests.
    session_id = str(uuid.uuid4())
    _cleanup_sessions()
    _sessions[session_id] = {"output_bytes": output_bytes}

    # Build display data for results
    matched_display = []
    for m in match_results["matched"]:
        s_idx = m["shopify_idx"]
        d_idx = m["distributor_idx"]
        matched_display.append({
            "shopify_label": shopify_df.loc[s_idx, "_display_label"] if s_idx in shopify_df.index else "",
            "distributor_label": distributor_df.loc[d_idx, "_display_label"] if d_idx is not None and d_idx in distributor_df.index else "",
            "match_type": m["match_type"],
            "confidence": m["confidence"],
        })

    delete_display = []
    for idx in match_results["to_delete"]:
        if idx in shopify_df.index:
            delete_display.append({
                "label": shopify_df.loc[idx, "_display_label"],
                "sku": shopify_df.loc[idx, "variant_sku"],
            })

    add_display = []
    for idx in match_results["to_add"]:
        if idx in distributor_df.index:
            add_display.append({
                "label": distributor_df.loc[idx, "_display_label"],
                "sku": distributor_df.loc[idx, "sku"],
            })

    review_display = []
    for r in match_results["needs_review"]:
        s_idx = r["shopify_idx"]
        d_idx = r["distributor_idx"]
        review_display.append({
            "shopify_label": shopify_df.loc[s_idx, "_display_label"] if s_idx in shopify_df.index else "",
            "distributor_label": distributor_df.loc[d_idx, "_display_label"] if d_idx is not None and d_idx in distributor_df.index else "",
            "confidence": r["confidence"],
            "reasoning": r["reasoning"],
        })

    return templates.TemplateResponse("results.html", {
        "request": request,
        "session_id": session_id,
        "matched": matched_display,
        "to_delete": delete_display,
        "to_add": add_display,
        "needs_review": review_display,
        "claude_unavailable": match_results["claude_unavailable"],
        "detection_status": detection_status,
        "mappings": mappings,
        "counts": {
            "matched": len(match_results["matched"]),
            "to_delete": len(match_results["to_delete"]),
            "to_add": len(match_results["to_add"]),
            "needs_review": len(match_results["needs_review"]),
            "shopify_total": len(shopify_df),
            "distributor_total": len(distributor_df),
        },
    })


@app.get("/download/{session_id}")
async def download_output(session_id: str):
    """Download the generated Matrixify output file."""
    session = _sessions.get(session_id)
    if not session:
        return Response(
            content="Session expired or not found. Please run the sync again.",
            status_code=404,
        )

    return Response(
        content=session["output_bytes"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=variant-sync-output.xlsx",
        },
    )
