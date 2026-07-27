"""
AI Search Service — Core pipeline.
1. Serper web search
2. DeepSeek batch extraction (with fallback from titles)
3. Enrichment for contact details
"""
import uuid
import json
import re
import time as _time
import threading
import logging
from copy import deepcopy

import requests
from ai.web_search_client import search_web, SEARCH_API_KEY
from ai.deepseek_client import DEFAULT_AI_FIELDS, DEEPSEEK_API_KEY, DEEPSEEK_API_URL
from ai.usage_tracker import get_usage


# ─── Shared constants ────────────────────────────────────────

SKIP_DOMAINS = [
    'facebook.com', 'twitter.com', 'instagram.com', 'linkedin.com',
    'youtube.com', 'pinterest.com', 'reddit.com', 'quora.com',
    'wikipedia.org', 'justdial.com', 'sulekha.com', 'yellowpages',
    'indiamart', 'zomato.com', 'swiggy.com', 'tripadvisor',
    'booking.com', 'timesofindia', 'hindustantimes', 'cntraveller',
    'theworlds50best', 'google.com/maps', 'maps.google',
]

# ─── Streaming Job Store ──────────────────────────────────────
STREAM_JOBS = {}
STREAM_JOB_LOCK = threading.Lock()


# ─── GUARANTEED FALLBACK: Extract from Serper titles ─────────
# No DeepSeek needed - works with regex on search result titles.
# This ensures the AI panel ALWAYS returns something.

def _extract_businesses_from_titles(raw_results, keyword, location, result_count):
    """Extract business names from Serper titles using regex.
    Filters out social media, directories, and article pages."""
    if not raw_results:
        return []
    
    ARTICLE_PATS = [
        r'top\s+\d+', r'best\s+\d+', r'\d+\s+best', r'list of',
        r'ultimate guide', r'how to', r'reviews? of',
    ]
    
    businesses = []
    for result in raw_results:
        if len(businesses) >= result_count:
            break
        title = (result.get('title') or '').strip()
        link = (result.get('link') or '').strip()
        if not title or len(title) < 5:
            continue
        # Skip non-business domains
        if any(d in link.lower() for d in SKIP_DOMAINS):
            continue
        # Skip article/listicle titles
        if any(re.search(p, title, re.IGNORECASE) for p in ARTICLE_PATS):
            continue
        # Extract name - keep everything before separators
        name = title
        for sep in [' | ', ' - ', ' — ', ' – ', ' |', '|']:
            if sep in name:
                first = name.split(sep)[0].strip()
                if keyword.lower() in first.lower() or len(first) < 30:
                    name = first
                    break
        # Remove parentheticals
        name = re.sub(r'\s*\([^)]*\)\s*', ' ', name).strip()
        # Remove trailing location words
        name = re.sub(r'\s+in\s+\w+(?:\s+\w+)?$', '', name, flags=re.IGNORECASE).strip()
        if len(name) < 3 or len(name) > 80:
            continue
        businesses.append({
            'name': name,
            'address': '',
            'email': '',
            'phone_number': '',
            'website': link,
        })
    
    logging.info(f"  [FALLBACK] {len(businesses)} businesses from titles")
    return businesses[:result_count]


# ─── DeepSeek batch extraction (with fallback) ────────────────

def extract_all_businesses_at_once(raw_results, keyword, location, result_count):
    """Try DeepSeek extraction first, fallback to title extraction if it fails."""
    if not raw_results:
        return []
    
    businesses = []
    
    # Attempt DeepSeek extraction
    if DEEPSEEK_API_KEY:
        try:
            context = "\n\n".join([
                f"[{i+1}] Title: {r.get('title','')}\nSnippet: {r.get('snippet','')}\nLink: {r.get('link','')}"
                for i, r in enumerate(raw_results)
            ])
            loc = f" in {location}" if location else ""
            prompt = (
                f"Below are {len(raw_results)} search results for '{keyword}{loc}'. "
                f"Find exactly {result_count} GENUINE businesses. "
                f"Return ONLY a JSON array with objects having keys: name, address, email, phone_number, website. "
                f"Leave empty string for unknown fields. Do NOT fabricate data.\n\n{context}"
            )
            resp = requests.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-v4-flash",
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": f"Extract {result_count} businesses from the above results."}
                    ],
                    "temperature": 0.1,
                    "max_tokens": min(8000, max(4000, result_count * 400)),
                },
                timeout=min(60, max(30, result_count * 3)),
            )
            resp.raise_for_status()
            text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            if text:
                text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.IGNORECASE).strip()
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    parsed = [parsed]
                for b in parsed:
                    if isinstance(b, dict) and b.get("name"):
                        entry = {f: (b.get(f, "") or "") for f in DEFAULT_AI_FIELDS}
                        businesses.append(entry)
                logging.info(f"  [DeepSeek] {len(businesses)}/{len(parsed)} businesses")
        except Exception as e:
            logging.warning(f"  [DeepSeek] Failed: {e}")
    
    # Fallback: fill remaining slots from titles
    if len(businesses) < result_count:
        existing = {b['name'].lower().strip() for b in businesses if b.get('name')}
        fallback = _extract_businesses_from_titles(raw_results, keyword, location, result_count)
        for fb in fallback:
            if fb['name'].lower().strip() not in existing:
                businesses.append(fb)
                existing.add(fb['name'].lower().strip())
    
    return businesses[:result_count]


# ─── LIGHTWEIGHT ENRICHMENT (regex-based, no DeepSeek) ─────

# Phone regex patterns (Indian & international formats)
_PHONE_PATTERNS = [
    # +91-XXXXXXXXXX or +91 XXXXXXXXXX or +91XXXXXXXXXX
    r'\+?91[-\s]?[6-9]\d{9}',
    # 0XXXXXXXXXX
    r'0[6-9]\d{9}',
    # XXXX-XXX-XXX (landline with STD code)
    r'\d{3,5}[-\s]?\d{3}[-\s]?\d{4}',
    # 1800 toll-free numbers
    r'1[8]00[-\s]?\d{3}[-\s]?\d{4}',
    # International: +1 (XXX) XXX-XXXX, +44 XXXX XXXXXX, etc.
    r'\+\d{1,3}[-\s]?\(?\d+\)?[-\s]?\d+[-\s]?\d+[-\s]?\d+',
    # Plain 10-digit mobile starting with 6-9
    r'(?<![\d])[6-9]\d{9}(?![\d])',
]

_EMAIL_PATTERN = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'


def _extract_phone_via_regex(text: str) -> str:
    """Extract first phone number from text using regex patterns."""
    for pat in _PHONE_PATTERNS:
        m = re.search(pat, text)
        if m:
            phone = m.group(0).strip()
            # Clean up common noise
            phone = phone.rstrip('.,;:)!}')
            if len(phone) >= 10:
                return phone
    return ""


def _extract_email_via_regex(text: str) -> str:
    """Extract first email address from text using regex."""
    m = re.search(_EMAIL_PATTERN, text)
    if m:
        return m.group(0).strip().rstrip('.,;:)!}')
    return ""


def _light_enrich_from_snippets(businesses, raw_results):
    """Fill missing phone/email/address/website fields by scanning
    ALREADY-FETCHED search result snippets with regex.
    Zero API calls, instant speed."""
    if not businesses or not raw_results:
        return businesses
    
    # Build a big text blob from all search snippets
    all_text = " ".join([
        f"{r.get('title','')} {r.get('snippet','')}"
        for r in raw_results
    ])
    
    # ─── Extract phones & emails ───
    phones = []
    for pat in _PHONE_PATTERNS:
        phones.extend(re.findall(pat, all_text))
    emails = re.findall(_EMAIL_PATTERN, all_text)
    
    # Deduplicate phones
    seen_phones = set()
    unique_phones = []
    for p in phones:
        cleaned = p.rstrip('.,;:)!}').strip()
        if cleaned not in seen_phones and len(cleaned) >= 10:
            seen_phones.add(cleaned)
            unique_phones.append(cleaned)
    phones = unique_phones
    emails = [e.rstrip('.,;:)!}').strip() for e in emails if len(e) > 5]
    
    phone_idx = 0
    email_idx = 0
    
    # ─── Also match websites from search result links ───
    # Build a lookup: business name (lower) → best matching link from raw_results
    biz_name_lower = {b['name'].lower().strip(): b for b in businesses if b.get('name')}
    
    for r in raw_results:
        title = (r.get('title') or '').strip()
        link = (r.get('link') or '').strip()
        snippet = (r.get('snippet') or '').strip()
        if not link:
            continue
        # Skip if link is from a directory/database site
        link_lower = link.lower()
        if any(d in link_lower for d in SKIP_DOMAINS):
            continue
        
        # Check if this result matches any business
        title_lower = title.lower()
        snippet_lower = snippet.lower()
        for biz_name, biz in biz_name_lower.items():
            # Match if business name appears in title or snippet
            words = biz_name.split()
            # Use first 3 significant words for better matching
            match_words = [w for w in words if len(w) > 2][:3]
            if not match_words:
                continue
            if all(w in title_lower or w in snippet_lower for w in match_words):
                # Fill website from link (only if better than existing)
                existing = biz.get("website", "")
                if not existing or any(d in existing.lower() for d in SKIP_DOMAINS):
                    biz["website"] = link
                # Try to extract address from snippet
                if not biz.get("address"):
                    addr = _extract_address_via_regex(title + " " + snippet)
                    if addr:
                        biz["address"] = addr
    
    # ─── Fill remaining missing phones/emails sequentially ───
    for biz in businesses:
        if not biz.get("phone_number") and phone_idx < len(phones):
            biz["phone_number"] = phones[phone_idx]
            phone_idx += 1
        if not biz.get("email") and email_idx < len(emails):
            biz["email"] = emails[email_idx]
            email_idx += 1
    
    found = sum(1 for b in businesses if b.get("phone_number") or b.get("email") or b.get("website") or b.get("address"))
    if found:
        logging.info(f"  [REGEX] Enriched {found}/{len(businesses)} businesses from snippets")
    return businesses


def _extract_address_via_regex(text: str) -> str:
    """Extract address/location from text using heuristic patterns.
    Returns empty string if no convincing address found."""
    # Words that are NOT valid addresses (time words, etc.)
    SKIP_ADDR = {'monday','tuesday','wednesday','thursday','friday','saturday','sunday',
                 'today','tomorrow','yesterday','open','close','hours','phone','email',
                 'website','contact','booking','order','home','menu','review','photos'}
    
    pats = [
        # "located at X, Y" or "located in X, Y"
        r'(?:locat(?:ed|ion)?\s+(?:at|in|near)\s+)([A-Z][A-Za-z][A-Za-z\s,.-]+?)(?:\.|\s*\||\s*\n|\s*-\s|$)',
        # "address: X" (must include a number or comma)
        r'(?:address[\s:]*(?:is\s+)?)([A-Za-z][A-Za-z\s,./0-9#-]+?(?:,\s*[A-Za-z\s]+|[0-9]+[A-Za-z\s]*))(?:\.|\s*\||\s*\n|$)',
    ]
    for pat in pats:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            addr = m.group(1).strip().rstrip('.,;')
            first_word = addr.split()[0].lower().strip(',') if addr.split() else ''
            if 8 < len(addr) < 120 and first_word not in SKIP_ADDR:
                return addr
    
    # Look for specific area/city patterns: "Area, City" format
    # Must have a comma separating two proper nouns
    area_pat = r'([A-Za-z][a-zA-Z]+(?:\s+[A-Za-z][a-zA-Z]+)?,\s*[A-Za-z][a-zA-Z]+(?:\s+[A-Za-z][a-zA-Z]+)?)'
    matches = re.findall(area_pat, text)
    for m in matches:
        addr = m.strip()
        # Skip if it looks like a date or time reference
        words = addr.lower().split(',')
        first_part = words[0].strip() if words else ''
        if first_part in SKIP_ADDR or len(first_part) < 3:
            continue
        if 6 < len(addr) < 100:
            return addr
    
    return ""


def _light_enrich_from_web(businesses, location, max_businesses=20):
    """For businesses still missing data, do ONE targeted
    web search per business but extract via regex (no DeepSeek).
    Searches for phone, email, address, and website.
    Adds ~2s per business instead of ~15s."""
    if not businesses:
        return businesses
    
    searched_count = 0
    for idx, biz in enumerate(businesses):
        if searched_count >= max_businesses:
            break
        name = biz.get("name", "")
        if not name:
            continue
        # Skip if all fields are already filled
        if biz.get("phone_number") and biz.get("email") and biz.get("address") and biz.get("website"):
            continue
        
        loc = f" {location}" if location else ""
        details = search_web(f"{name}{loc} contact address phone website", num_results=4, timeout=8)
        if details:
            text = " ".join([f"{r.get('title','')} {r.get('snippet','')}" for r in details])
            
            if not biz.get("phone_number"):
                phone = _extract_phone_via_regex(text)
                if phone:
                    biz["phone_number"] = phone
            if not biz.get("email"):
                email = _extract_email_via_regex(text)
                if email:
                    biz["email"] = email
            if not biz.get("address"):
                addr = _extract_address_via_regex(text)
                if addr:
                    biz["address"] = addr
            if not biz.get("website"):
                # Take the first search result link that isn't a known directory site
                for r in details:
                    link = (r.get('link') or '').strip()
                    if link and not any(d in link.lower() for d in SKIP_DOMAINS):
                        biz["website"] = link
                        break
            # Also try to overwrite existing bad website
            existing_web = biz.get("website", "")
            if existing_web and any(d in existing_web.lower() for d in SKIP_DOMAINS):
                for r in details:
                    link = (r.get('link') or '').strip()
                    if link and not any(d in link.lower() for d in SKIP_DOMAINS):
                        biz["website"] = link
                        break
            searched_count += 1
        # Minimal delay between calls
        if idx < len(businesses) - 1:
            _time.sleep(0.2)
    
    if searched_count:
        logging.info(f"  [WEB-REGEX] Searched {searched_count} businesses for missing data")
    return businesses


# ─── Streaming helpers ────────────────────────────────────────

def _process_stream_job(job_id, raw_results, keyword, location, total_count):
    try:
        with STREAM_JOB_LOCK:
            STREAM_JOBS[job_id]["message"] = "Extracting businesses..."
        business_list = extract_all_businesses_at_once(raw_results, keyword, location, total_count)
        if not business_list:
            with STREAM_JOB_LOCK:
                STREAM_JOBS[job_id].update({"status": "complete", "message": "No businesses found."})
            return
        with STREAM_JOB_LOCK:
            STREAM_JOBS[job_id].update({
                "status": "complete", "results": business_list,
                "total_count": len(business_list), "current_count": len(business_list),
                "message": f"{len(business_list)} results loaded."
            })
    except Exception as e:
        with STREAM_JOB_LOCK:
            STREAM_JOBS[job_id].update({"status": "error", "error": str(e)})


# ─── Non-business query detection ────────────────────────────

# Keywords that indicate a business/supplier related query
_BUSINESS_KEYWORDS = {
    'cafe', 'cafes', 'restaurant', 'restaurants', 'hotel', 'hotels', 'shop', 'shops',
    'store', 'stores', 'company', 'companies', 'supplier', 'suppliers', 'dealer', 'dealers',
    'business', 'businesses', 'service', 'services', 'clinic', 'clinic', 'hospital',
    'school', 'college', 'institute', 'agency', 'agencies', 'manufacturer', 'manufacturers',
    'wholesaler', 'wholesalers', 'retailer', 'retailers', 'distributor', 'distributors',
    'vendor', 'vendors', 'contractor', 'contractors', 'producer', 'producers',
    'bakery', 'salon', 'gym', 'pharmacy', 'lab', 'factory', 'plant', 'office',
    'address', 'phone', 'contact', 'email', 'website',
}

# Words that clearly indicate a NON-business query
_NON_BUSINESS_TRIGGERS = {
    'weather', 'news', 'sports', 'movie', 'song', 'music', 'film', 'video',
    'recipe', 'cricket', 'football', 'love', 'relationship', 'politics',
    'game', 'play', 'dance', 'sing', 'poem', 'story', 'joke', 'funny',
    'who is', 'what is', 'how to', 'why is', 'define', 'meaning',
    'translate', 'capital of', 'population of', 'president of',
    'hello', 'hi', 'how are you', 'whats up', 'good morning',
}

_REFUSAL_MESSAGE = (
    "Main sirf business/supplier-related data provide karta hoon. "
    "Mai aapko company names, addresses, phone numbers, emails, aur websites nikaal kar deta hoon. "
    "Agar aapko kisi bhi business, supplier, dealer, ya company ke baare mein data chahiye, "
    "toh aise poochhein: 'cafes in Mumbai' ya 'suppliers of steel in Delhi'. "
    "Main general questions ka answer nahi de sakta. Kripya business-related query poochhein."
)


def _is_business_query(query: str) -> bool:
    """Check if the user's query is business/supplier related."""
    q = query.lower().strip()
    
    # Check non-business triggers first
    for trigger in _NON_BUSINESS_TRIGGERS:
        if q.startswith(trigger) or trigger in q.split()[:5]:
            return False
    
    # Query is too short to be a business query
    if len(q) < 4:
        return False
    
    # Check for business keywords — must be a business-specific word, not just 'in/near/at'
    words = set(q.split())
    # 'in', 'near', 'at' are TOO generic — only count them if a location word follows
    business_specific = words - {'in', 'near', 'at', 'the', 'a', 'an', 'for', 'to', 'of', 'and', 'or'}
    # Check if ANY remaining word matches _BUSINESS_KEYWORDS
    if business_specific & _BUSINESS_KEYWORDS:
        return True
    
    # If query has location pattern (X in Y, X near Y) with a real keyword before it
    location_match = re.search(r'\b(in|near|at)\s+([A-Za-z]{2,})', q)
    if location_match:
        # Ensure there's a meaningful word BEFORE the location indicator
        before = q[:location_match.start()].strip()
        if len(before) >= 3:
            return True
    
    return False


# ─── Main pipeline ────────────────────────────────────────────

def run_ai_search(search_query, mode, result_count, keyword, location):
    """Main AI search pipeline with guaranteed fallback."""
    if not SEARCH_API_KEY:
        return {"error": "SEARCH_API_KEY not configured", "usage": get_usage(), "results": []}
    if not DEEPSEEK_API_KEY:
        return {"error": "DEEPSEEK_API_KEY not configured", "usage": get_usage(), "results": []}
    
    usage = get_usage()
    if usage["remaining"] <= 1:
        return {"error": "API quota exhausted", "usage": usage, "results": []}
    
    # Step 1: Search
    raw = search_web(search_query, num_results=max(result_count * 5, 20))
    if not raw:
        return {"results": [], "usage": get_usage()}
    
    logging.info(f"  Got {len(raw)} raw results (target={result_count})")
    
    # Step 2: Extract (DeepSeek + fallback)
    businesses = extract_all_businesses_at_once(raw, keyword, location, result_count)
    if not businesses:
        return {"results": [], "usage": get_usage()}
    
    # Step 3: Lightweight enrichment (regex from snippets + targeted web)
    # max_businesses for web enrichment matches user's requested count (capped at 20 for speed)
    enrich_count = min(max(result_count, 5), 20)
    businesses = _light_enrich_from_snippets(businesses, raw)
    businesses = _light_enrich_from_web(businesses, location, max_businesses=enrich_count)
    logging.info(f"  Done: {len(businesses)} businesses (web-enrichment target={enrich_count})")
    return {"results": businesses, "usage": get_usage()}


def handle_chat_query(user_query, mode, result_count=10):
    """Handle chat query from AI Panel.
    
    Optimized for speed: skips expensive per-business enrichment.
    Uses web search + single DeepSeek batch extraction only.
    """
    logging.info(f"[Chat] '{user_query[:60]}' count={result_count}")
    
    # Check if query is business-related BEFORE making any API calls
    if not _is_business_query(user_query):
        logging.info(f"  [REFUSAL] Non-business query: '{user_query[:60]}'")
        return {
            "type": "refusal",
            "message": _REFUSAL_MESSAGE,
            "results": [],
            "usage": get_usage(),
        }
    
    # Extract location from query
    location = ""
    m = re.search(r'\b(?:in|near|at)\s+([A-Za-z\s,.-]+)', user_query, re.IGNORECASE)
    if m:
        location = " ".join(m.group(1).strip().split()[:3])
    
    keyword = user_query.split(" in ")[0].split(" near ")[0].strip() if (" in " in user_query or " near " in user_query) else user_query
    
    # Step 1: Web search (fast, ~2-5s)
    raw = search_web(user_query, num_results=max(result_count * 5, 20))
    if not raw:
        return {"type": "search_result", "message": f"No results for '{user_query}'.",
                "results": [], "usage": get_usage()}
    
    # Step 2: DeepSeek batch extraction + guaranteed fallback (skips per-business enrichment)
    businesses = extract_all_businesses_at_once(raw, keyword, location, result_count)
    if not businesses:
        return {"type": "search_result", "message": f"No results for '{user_query}'.",
                "results": [], "usage": get_usage()}
    
    # Step 3: Lightweight enrichment (regex from snippets + targeted web)
    enrich_count = min(max(result_count, 5), 20)
    businesses = _light_enrich_from_snippets(businesses, raw)
    businesses = _light_enrich_from_web(businesses, location, max_businesses=enrich_count)
    
    msg = f"Here are {len(businesses)} results for '{user_query}':" if businesses else f"No results found."
    return {
        "type": "search_result", "message": msg,
        "results": businesses,
        "usage": get_usage(),
        "search_id": uuid.uuid4().hex[:12] if businesses else None,
    }


def get_stream_status(job_id):
    with STREAM_JOB_LOCK:
        job = STREAM_JOBS.get(job_id)
        return deepcopy(job) if job else {"status": "not_found", "error": "Job not found"}
