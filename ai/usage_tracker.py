"""
Usage Tracker — Serper API quota tracking.
Tracks monthly search API usage in a JSON file.
Auto-resets when the month changes.
"""

import json
import os
from datetime import datetime
from threading import Lock

USAGE_FILE = os.path.join(os.path.dirname(__file__), "usage_data.json")
_lock = Lock()


def _load_usage() -> dict:
    """Load usage data from file. Returns {month, count} dict."""
    current_month = datetime.now().strftime("%Y-%m")
    
    if not os.path.exists(USAGE_FILE):
        return {"month": current_month, "count": 0}
    
    try:
        with open(USAGE_FILE, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"month": current_month, "count": 0}
    
    # Auto-reset if month changed
    if data.get("month") != current_month:
        data = {"month": current_month, "count": 0}
    
    return data


def _save_usage(data: dict):
    """Save usage data to file."""
    try:
        with open(USAGE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        import logging
        logging.warning(f"Failed to save usage data: {e}")


def increment_usage():
    """Increment the search API usage counter by 1. Thread-safe."""
    with _lock:
        data = _load_usage()
        data["count"] += 1
        _save_usage(data)


def get_usage() -> dict:
    """
    Return current usage stats as a dict.
    
    Returns:
        {
            "used": int,       # searches used this month
            "limit": int,      # monthly limit
            "remaining": int,  # searches remaining
            "month": str,      # current month (YYYY-MM)
        }
    """
    with _lock:
        data = _load_usage()
        limit = int(os.getenv("SEARCH_API_MONTHLY_LIMIT", 2500))
        return {
            "used": data["count"],
            "limit": limit,
            "remaining": max(0, limit - data["count"]),
            "month": data["month"],
        }
