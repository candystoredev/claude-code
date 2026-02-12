"""Configuration for candy description generator."""

import os

# Claude API settings
API_MODEL = "claude-sonnet-4-20250514"
API_MAX_TOKENS = 300

# Rate limiting
REQUESTS_PER_SECOND = 1  # Conservative: 1 req/sec (~80 min for 5000 products)

# Batch / checkpoint settings
SAVE_EVERY_N = 10  # Save progress every N products

# File paths
INPUT_DIR = os.path.join(os.path.dirname(__file__), "input")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# Default file names (can be overridden via CLI)
DEFAULT_INPUT_FILE = "products.csv"
DEFAULT_OUTPUT_FILE = "products_with_descriptions.csv"

# API key - read from environment variable
# Set via: export ANTHROPIC_API_KEY="your-key-here"
# Or place in a .env file in this directory
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
