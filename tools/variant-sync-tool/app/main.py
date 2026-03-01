"""Variant Sync Tool — FastAPI application."""

import logging
import uuid

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

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


@app.get("/guide", response_class=HTMLResponse)
async def guide(request: Request):
    """Render the how-to-use / tech stack guide page."""
    return templates.TemplateResponse("guide.html", {"request": request})


@app.get("/changelog", response_class=HTMLResponse)
async def changelog(request: Request):
    """Render the changelog page."""
    return templates.TemplateResponse("changelog.html", {"request": request})


@app.post("/upload", response_class=HTMLResponse)
async def upload_and_process(
    request: Request,
    shopify_file: UploadFile = File(...),
    distributor_file: UploadFile = File(...),
    manufacturer_filter: str = Form(""),
    product_handle: str = Form(""),
    human_guidance: str = Form(""),
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
        })

    # Filter Shopify data to a single product handle if specified
    handle_filter = product_handle.strip().lower() or None
    if handle_filter:
        mask = shopify_df["handle"].str.strip().str.lower() == handle_filter
        if not mask.any():
            available_handles = sorted(shopify_df["handle"].str.strip().str.lower().unique())
            return templates.TemplateResponse("index.html", {
                "request": request,
                "errors": [
                    f"Handle '{handle_filter}' not found in Shopify export. "
                    f"Available handles: {', '.join(available_handles[:20])}"
                    + (" ..." if len(available_handles) > 20 else "")
                ],
            })
        shopify_df = shopify_df[mask].reset_index(drop=True)
        logger.info("Filtered to handle '%s': %d variants", handle_filter, len(shopify_df))

    # Run matching
    guidance = human_guidance.strip() or None
    try:
        match_results = await run_matching(shopify_df, distributor_df, human_guidance=guidance)
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

    # Store session data — DataFrames and match results are kept so that
    # review actions can update match_results and regenerate the output file.
    session_id = str(uuid.uuid4())
    _cleanup_sessions()
    _sessions[session_id] = {
        "output_bytes": output_bytes,
        "shopify_df": shopify_df,
        "distributor_df": distributor_df,
        "match_results": match_results,
    }

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


class ReviewAction(BaseModel):
    review_index: int
    action: str  # "approve" | "reject_add" | "reject_skip" | "reject_keep"


@app.post("/review/{session_id}")
async def resolve_review(session_id: str, body: ReviewAction):
    """Resolve a single needs-review item and regenerate the output file.

    Actions:
      - approve:      Confirm match → move to matched.
      - reject_add:   Not a match → delete Shopify variant, add distributor product.
      - reject_skip:  Not a match → delete Shopify variant, don't add distributor.
      - reject_keep:  Not a match → keep Shopify variant, add distributor product.
    """
    session = _sessions.get(session_id)
    if not session:
        return JSONResponse(
            {"error": "Session expired or not found."},
            status_code=404,
        )

    match_results = session["match_results"]
    needs_review = match_results["needs_review"]

    if body.review_index < 0 or body.review_index >= len(needs_review):
        return JSONResponse(
            {"error": "Invalid review index."},
            status_code=400,
        )

    if body.action not in ("approve", "reject_add", "reject_skip", "reject_keep"):
        return JSONResponse(
            {"error": f"Unknown action: {body.action}"},
            status_code=400,
        )

    # Pop the review item (indices shift down for subsequent items)
    review_item = needs_review.pop(body.review_index)
    shopify_idx = review_item["shopify_idx"]
    distributor_idx = review_item["distributor_idx"]

    if body.action == "approve":
        # Confirm the match — move to matched list
        review_item["match_type"] = "approved"
        review_item["confidence"] = 1.0
        match_results["matched"].append(review_item)

    elif body.action == "reject_add":
        # Not a match — delete Shopify variant, add distributor as new
        if shopify_idx is not None:
            match_results["to_delete"].append(shopify_idx)
        if distributor_idx is not None:
            match_results["to_add"].append(distributor_idx)

    elif body.action == "reject_skip":
        # Not a match — delete Shopify variant, don't add distributor
        if shopify_idx is not None:
            match_results["to_delete"].append(shopify_idx)

    elif body.action == "reject_keep":
        # Not a match — keep Shopify variant, add distributor as new
        if distributor_idx is not None:
            match_results["to_add"].append(distributor_idx)

    # Regenerate the output file with updated results
    shopify_df = session["shopify_df"]
    distributor_df = session["distributor_df"]
    session["output_bytes"] = generate_output(shopify_df, distributor_df, match_results)

    return JSONResponse({
        "ok": True,
        "counts": {
            "matched": len(match_results["matched"]),
            "to_delete": len(match_results["to_delete"]),
            "to_add": len(match_results["to_add"]),
            "needs_review": len(match_results["needs_review"]),
        },
    })
