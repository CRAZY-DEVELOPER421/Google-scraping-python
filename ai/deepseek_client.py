"""
Zaucto AI Client — extracts structured business data from real web search results.
Powered by DeepSeek API. Does NOT use training memory — only extracts from provided search results.
"""

import os
import json
import logging
import re
from typing import List, Dict, Optional, Any

import requests

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ─── Field sets (for main Google Maps scraper — mode-based) ──

FIELD_SETS = {
    "fast": [
        "name", "phone_number", "address", "website", "reviews_count",
        "reviews_average", "place_type", "opens_at", "store_shopping",
        "in_store_pickup", "store_delivery", "introduction",
    ],
    "deep": [
        "name", "phone_number", "address", "website", "reviews_count",
        "reviews_average", "place_type", "opens_at", "store_shopping",
        "in_store_pickup", "store_delivery", "introduction",
        "email", "instagram", "facebook", "linkedin",
    ],
    "ultra_deep": [
        "name", "phone_number", "address", "website", "reviews_count",
        "reviews_average", "place_type", "opens_at", "store_shopping",
        "in_store_pickup", "store_delivery", "introduction",
        "email", "instagram", "facebook", "linkedin", "twitter",
        "whatsapp", "youtube", "tiktok", "telegram", "pinterest", "snapchat",
    ],
}

# ─── AI Panel default fields (mode-independent — always 5) ──

DEFAULT_AI_FIELDS = ["name", "address", "email", "phone_number", "website"]


def get_fields_for_mode(mode: str, social_media_options: Optional[Dict[str, bool]] = None) -> List[str]:
    """Return the list of fields based on the scraping mode (for main scraper)."""
    if mode == "ultra_deep" and social_media_options:
        base = FIELD_SETS["fast"] + ["email"]
        all_platforms = {"instagram", "linkedin", "facebook", "twitter", "whatsapp",
                         "youtube", "tiktok", "telegram", "pinterest", "snapchat"}
        for platform, enabled in social_media_options.items():
            if enabled and platform in all_platforms and platform not in base:
                base.append(platform)
        return base
    return FIELD_SETS.get(mode, FIELD_SETS["fast"]).copy()


def get_ai_panel_fields() -> List[str]:
    """Return the fixed 5-field set for the AI Search Panel (mode-independent)."""
    return DEFAULT_AI_FIELDS.copy()


def _parse_single_json(content: str) -> Dict[str, Any]:
    """Parse DeepSeek response into a single JSON object. Returns empty dict on failure."""
    if not content:
        return {}
    cleaned = re.sub(r'^```(?:json)?\s*', '', content.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, list) and len(obj) > 0:
            return obj[0]
        return {}
    except json.JSONDecodeError:
        return {}


def extract_from_search_results(business_name: str, search_results: list, mode: Optional[str] = None, social_media_options: Optional[Dict[str, bool]] = None) -> dict:
    """
    Extract structured business data for a SINGLE business from real search results.
    For AI Panel (default): uses DEFAULT_AI_FIELDS (5 fields) — mode is ignored for field selection.
    For main scraper: pass mode to use FIELD_SETS via get_fields_for_mode().
    
    Args:
        business_name: Name of the business to extract data for
        search_results: List of {title, snippet, link} from Serper.dev
        mode: Scraping mode (fast/deep/ultra_deep) — ONLY for main scraper, ignored for AI Panel
        social_media_options: For ultra_deep mode — only include selected platforms
    
    Returns:
        Dict with all requested fields. Missing fields are empty strings.
        At minimum, {"name": business_name} is guaranteed.
    """
    if not DEEPSEEK_API_KEY:
        logging.error("DEEPSEEK_API_KEY not set. Cannot extract.")
        return {"name": business_name}

    # AI Panel always uses 5 default fields; main scraper uses mode-based fields
    if mode is not None:
        fields = get_fields_for_mode(mode, social_media_options)
    else:
        fields = DEFAULT_AI_FIELDS

    context_text = "\n\n".join([
        f"Title: {r.get('title', '')}\nSnippet: {r.get('snippet', '')}\nLink: {r.get('link', '')}"
        for r in search_results
    ])

    # Build field description based on caller (AI Panel vs main scraper)
    if mode is not None:
        field_instruction = f"Return a single JSON object with these fields: {fields}."
    else:
        field_instruction = (
            "Return a single JSON object with EXACTLY these fields: "
            "name, address, email, phone_number, website. Do not include any other fields."
        )

    system_prompt = (
        f"You are strictly a business data extraction assistant. You ONLY provide "
        f"business/location data. You NEVER answer opinions, general knowledge, or "
        f"unrelated questions. If asked anything outside business data scraping, "
        f"respond with exactly: 'Main sirf business/supplier-related data provide karta hoon. "
        f"Mai aapko company names, addresses, phone numbers, emails, aur websites nikaal kar deta hoon. "
        f"Agar aapko kisi bhi business, supplier, dealer, ya company ke baare mein data chahiye, "
        f"toh aise poochhein: cafes in Mumbai ya suppliers of steel in Delhi. "
        f"Main general questions ka answer nahi de sakta.'"
        f"\n\nBelow are REAL web search results "
        f"about the business '{business_name}'. Extract information ONLY from what "
        f"is explicitly stated. {field_instruction} "
        f"If a field is not mentioned, return empty string for it — "
        f"DO NOT guess or use outside knowledge. Return ONLY valid JSON, no other text."
        f"\n\nSEARCH RESULTS:\n{context_text}"
    )

    payload = {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Extract data for {business_name}."},
        ],
        "temperature": 0.1,
        "max_tokens": 2048,
    }

    try:
        response = requests.post(
            DEEPSEEK_API_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            logging.warning(f"DeepSeek returned no choices for '{business_name}'")
            return {"name": business_name}

        content = choices[0].get("message", {}).get("content", "")
        result = _parse_single_json(content)

        # Ensure at minimum the name is set
        if not result.get("name"):
            result["name"] = business_name

        # Fill missing fields with empty strings
        for field in fields:
            if field not in result or result[field] is None:
                result[field] = ""

        found = len([v for v in result.values() if v and str(v).strip()])
        logging.info(f"  📊 {business_name}: {found}/{len(fields)} fields extracted")
        return result

    except requests.exceptions.Timeout:
        logging.error(f"DeepSeek timeout for '{business_name}'")
        return {"name": business_name}
    except requests.exceptions.RequestException as e:
        logging.error(f"DeepSeek API error for '{business_name}': {e}")
        return {"name": business_name}
    except Exception as e:
        logging.exception(f"Unexpected error extracting '{business_name}': {e}")
        return {"name": business_name}



