"""
Web Search Client — Serper.dev API wrapper with usage tracking.
Provides real-time Google search results for the AI Search pipeline.
"""

import os
import json
import logging
from typing import List, Dict

import requests

from ai.usage_tracker import increment_usage, get_usage

SEARCH_API_KEY = os.getenv("SEARCH_API_KEY")
SERPER_URL = "https://google.serper.dev/search"


def search_web(query: str, num_results: int = 5, timeout: int = 15) -> List[Dict[str, str]]:
    """
    Real web search via Serper.dev. Returns list of {title, snippet, link}.
    Tracks usage count on every successful call.

    Args:
        query: Search query string
        num_results: Number of organic results to request
        timeout: Request timeout in seconds

    Returns:
        List of dicts with 'title', 'snippet', 'link' keys.
        Empty list if error or no results.
    """
    if not SEARCH_API_KEY:
        logging.error("SEARCH_API_KEY not set in .env. Web search disabled.")
        return []

    try:
        logging.info(f"🌐 Web search: '{query}' (results={num_results})")

        response = requests.post(
            SERPER_URL,
            headers={
                "X-API-KEY": SEARCH_API_KEY,
                "Content-Type": "application/json",
            },
            json={"q": query, "num": num_results},
            timeout=timeout,
        )
        response.raise_for_status()

        # Track usage on success
        increment_usage()
        data = response.json()

        organic = data.get("organic", [])
        results = []
        for item in organic[:num_results]:
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "link": item.get("link", ""),
            })

        logging.info(f"✅ Web search returned {len(results)} results for '{query}'")
        return results

    except requests.exceptions.Timeout:
        logging.error(f"❌ Serper.dev timeout after {timeout}s for query: {query}")
        return []
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else "unknown"
        logging.error(f"❌ Serper.dev HTTP {status} error: {e}")
        return []
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Serper.dev request error: {e}")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"❌ Serper.dev JSON parse error: {e}")
        return []
    except Exception as e:
        logging.exception(f"❌ Unexpected web search error: {e}")
        return []


def search_business_details(business_name: str, location: str = "", timeout: int = 15) -> List[Dict[str, str]]:
    """
    Specific search for a single business's contact details.
    Query focuses on phone, address, website, and rating.

    Example: "Prithvi Cafe Mumbai phone number address website rating"
    """
    parts = [p for p in [business_name, location, "phone number address website rating"] if p]
    query = " ".join(parts)
    return search_web(query, num_results=5, timeout=timeout)
