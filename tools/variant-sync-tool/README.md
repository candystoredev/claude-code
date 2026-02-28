# Variant Sync Tool

A lightweight internal tool for syncing Shopify product variants with a distributor/manufacturer product offerings list, using Matrixify-format files as both input and output.

## What it does

1. **Upload** your Shopify export (Matrixify format) and a distributor offerings file
2. **Match** variants automatically using SKU, barcode, and fuzzy name/flavor/size matching
3. **Review** results: matched pairs, variants to delete, variants to add, and flagged low-confidence matches
4. **Download** a single Matrixify-ready Excel file with `DELETE`, `NEW`, `MERGE`, and `REVIEW` commands

## How to run locally

```bash
# Clone and navigate to the tool
cd tools/variant-sync-tool

# Create a virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Run the development server
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000 in your browser.

## How to deploy

### Railway

1. Connect your GitHub repo to Railway
2. Set the root directory to `tools/variant-sync-tool`
3. Railway will auto-detect the `Dockerfile` or `nixpacks.toml`
4. Set environment variables in Railway dashboard:
   - `ANTHROPIC_API_KEY` (or configure via Doppler)
   - `PORT` (Railway sets this automatically)

### Render

1. Create a new Web Service on Render
2. Point to this repo, set root directory to `tools/variant-sync-tool`
3. Use the Dockerfile or set build command: `pip install -r requirements.txt`
4. Set start command: `gunicorn app.main:app --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT`
5. Add `ANTHROPIC_API_KEY` as an environment variable

## Column mapping expectations

### Shopify / Matrixify export

The tool expects standard Matrixify column names:
- `Handle`, `Title`
- `Option1 Name`, `Option1 Value`, `Option2 Name`, `Option2 Value`
- `Variant SKU`, `Variant Price`, `Variant Barcode`
- `Status`, `Image Src`

### Distributor file

The tool auto-detects columns by matching common patterns:

| Field | Example column names detected |
|-------|-------------------------------|
| Product name | `Product Name`, `Item Name`, `Description` |
| Flavor/variety | `Flavor`, `Variety`, `Scent` |
| Size/weight | `Size`, `Weight`, `Net Weight`, `Pack Size` |
| Price | `Price`, `Cost`, `MSRP`, `Wholesale` |
| SKU | `SKU`, `Item Number`, `Product Code` |
| UPC/barcode | `UPC`, `Barcode`, `EAN`, `GTIN` |
| Image URL | `Image`, `Image URL`, `Photo` |
| Manufacturer | `Manufacturer`, `Brand`, `Vendor` |

If auto-detection fails for required fields, an error message will indicate which columns could not be mapped.

## How to interpret the output file

The downloaded Excel file contains these `Command` values:

| Command | Meaning |
|---------|---------|
| *(blank)* | Matched variant — no action needed (informational) |
| `DELETE` | Variant exists in Shopify but not in distributor list — remove it |
| `NEW` | Product exists in distributor list but not in Shopify — create it |
| `MERGE` | Variant is new but the parent product handle already exists — add as variant |
| `REVIEW` | Low-confidence match flagged for manual verification |

Import this file directly into Shopify via Matrixify. Review `DELETE` and `REVIEW` rows before importing.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | *(required)* | API key for Claude fuzzy matching |
| `MAX_CLAUDE_BATCH_SIZE` | `10` | Max distributor candidates per Claude API call |
| `MATCH_AUTO_THRESHOLD` | `0.85` | Confidence threshold for auto-matching |
| `MATCH_REVIEW_THRESHOLD` | `0.50` | Confidence threshold for flagging review |

## Stack

- Python 3.12+
- FastAPI + Jinja2 + HTMX
- pandas + openpyxl
- Anthropic Python SDK (Claude claude-sonnet-4-5)
