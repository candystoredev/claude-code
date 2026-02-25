"""Configuration for Shopify product categorization tool."""

import os

# Claude API settings
API_MODEL = "claude-haiku-4-5-20251001"  # Haiku: ~10x cheaper than Sonnet, fast enough for categorization
API_MAX_TOKENS = 4096

# Rate limiting
REQUESTS_PER_SECOND = 1

# Batch settings
BATCH_SIZE = 20  # Products per API call (higher = fewer calls = cheaper)
SAVE_EVERY_N = 5  # Save progress every N batches

# File paths
TOOL_DIR = os.path.dirname(__file__)
INPUT_DIR = os.path.join(TOOL_DIR, "input")
OUTPUT_DIR = os.path.join(TOOL_DIR, "output")
COLLECTIONS_FILE = os.path.join(TOOL_DIR, "collections.json")

# Default file names (can be overridden via CLI)
DEFAULT_INPUT_FILE = "products.xlsx"
DEFAULT_OUTPUT_FILE = "products_categorized.csv"

# API key - read from environment variable
# Set via: export ANTHROPIC_API_KEY="your-key-here"
# Or place in a .env file in this directory
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
