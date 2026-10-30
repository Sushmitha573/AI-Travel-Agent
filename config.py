"""Central configuration for the AI Travel Agent.

All secrets are read from environment variables (or a local .env file).
Nothing secret is ever hard-coded in this project.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load variables from AI_Travel_Agent/.env (if the file exists).
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Gemini settings
# ---------------------------------------------------------------------------
# "gemini-2.5-flash" is a stable Gemini model name. Google retires and adds
# models over time, so you can override it in .env with GEMINI_MODEL=...
DEFAULT_MODEL = "gemini-2.5-flash"

# Network timeout for one Gemini request, in seconds.
REQUEST_TIMEOUT_SECONDS = 90

# How many times the agent may ask the AI to shorten a plan that is too costly.
MAX_REVISIONS = 2

# ---------------------------------------------------------------------------
# Weather (Open-Meteo: free, documented, no API key needed)
# ---------------------------------------------------------------------------
WEATHER_TIMEOUT_SECONDS = 10

# ---------------------------------------------------------------------------
# Form options
# ---------------------------------------------------------------------------
TRAVEL_TYPES = ["Solo", "Family", "Friends", "Couple"]
TRAVEL_STYLES = ["Adventure", "Relaxation", "Cultural", "Food", "Nature"]
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

MAX_DAYS = 14
MAX_TRAVELERS = 20
MIN_BUDGET_INR = 1000


def get_api_key() -> str:
    """Return the Gemini API key (empty string if it is not configured).

    Read at call time so that editing .env and restarting is enough.
    """
    return os.getenv("GEMINI_API_KEY", "").strip()


def get_model_name() -> str:
    """Return the Gemini model name to use."""
    return os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_MODEL


def api_key_is_placeholder(key: str) -> bool:
    """True if the key is empty or still the placeholder from .env.example."""
    return (not key) or key.lower().startswith("your_gemini_api_key")
