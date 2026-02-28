"""Configuration for Variant Sync Tool."""

import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
API_MODEL = "claude-sonnet-4-5-20250514"
API_MAX_TOKENS = 4096

MAX_CLAUDE_BATCH_SIZE = int(os.environ.get("MAX_CLAUDE_BATCH_SIZE", "10"))
MATCH_AUTO_THRESHOLD = float(os.environ.get("MATCH_AUTO_THRESHOLD", "0.85"))
MATCH_REVIEW_THRESHOLD = float(os.environ.get("MATCH_REVIEW_THRESHOLD", "0.50"))

MAX_UPLOAD_SIZE_MB = 50
