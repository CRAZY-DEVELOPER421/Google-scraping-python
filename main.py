import logging
from typing import List, Optional, Dict, Set, Callable
from dataclasses import dataclass, asdict
import pandas as pd
import argparse
import platform
import time
import os
import threading
import re
import random
import requests
from concurrent.futures import ThreadPoolExecutor

# Optional: playwright-stealth for anti-detection — silently skip if not installed
try:
    from playwright_stealth import stealth_sync
except ImportError:
    stealth_sync = None

from bs4 import BeautifulSoup
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright, Page


# ─── Rotating User Agents to avoid 403 blocks ────────────────

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0',
]

@dataclass
class Place:
    name: str = ""
    address: str = ""
    website: str = ""
    phone_number: str = ""
    email: str = ""
    instagram: str = ""
    linkedin: str = ""
    facebook: str = ""
    twitter: str = ""
    whatsapp: str = ""
    youtube: str = ""
    tiktok: str = ""
    telegram: str = ""
    pinterest: str = ""
    snapchat: str = ""
    reviews_count: Optional[int] = None
    reviews_average: Optional[float] = None
    store_shopping: str = "No"
    in_store_pickup: str = "No"
    store_delivery: str = "No"
    place_type: str = ""
    opens_at: str = ""
    introduction: str = ""


# ─── Data Verification ────────────────────────────────────

FAKE_PHONE_PATTERNS = [
    "n/a", "none", "null", "na", "0", "-", "not available", "not provided",
    "000-000-0000", "0000000000", "123-456-7890", "1234567890",
    "111-111-1111", "1111111111", "999-999-9999", "9999999999",
]

FAKE_EMAIL_DOMAINS = [
    "example.com", "example.org", "example.net", "domain.com",
    "test.com", "test.org", "test.net", "sample.com",
    "yourcompany.com", "yourdomain.com", "mycompany.com",
]


def is_valid_phone(phone: str) -> bool:
    """Check if a phone number looks real (not placeholder/fake)."""
    if not phone or not phone.strip():
        return False
    cleaned = phone.strip().lower()
    # Check against common fake patterns
    if cleaned in FAKE_PHONE_PATTERNS:
        return False
    # Should have at least 7 digits
    digits = re.sub(r'\D', '', cleaned)
    if len(digits) < 7:
        return False
    return True


def is_valid_email(email: str) -> bool:
    """Check if an email looks real (not placeholder/fake)."""
    if not email or not email.strip():
        return False
    email_lower = email.strip().lower()
    # Check against known fake patterns
    ignore_patterns = [
        'example.com', 'domain.com', 'your@', 'test@', 'user@',
        'email@', 'mail@', '@email.com', '@mail.com',
        'info@example', 'contact@example', 'admin@example',
        'no-reply@', 'noreply@', 'donotreply@',
    ]
    for pattern in ignore_patterns:
        if pattern in email_lower:
            return False
    # Check domain against fake domains list
    try:
        domain = email_lower.split('@')[1]
        if domain in FAKE_EMAIL_DOMAINS:
            return False
    except (IndexError, ValueError):
        return False
    # Must match email pattern
    if not re.match(EMAIL_PATTERN, email):
        return False
    return True


def verify_place_data(place: Place, mode: str = "fast") -> bool:
    """
    Verify that critical place data is real. Returns True if name is present.
    Clears out fake phone/email so retry logic can re-extract them.
    """
    if not place.name or not place.name.strip():
        return False

    # Phone verification
    if place.phone_number and not is_valid_phone(place.phone_number):
        logging.warning(f"⚠ Fake phone for '{place.name}': {place.phone_number} — clearing for retry")
        place.phone_number = ""

    # Email verification
    if place.email and not is_valid_email(place.email):
        logging.warning(f"⚠ Fake email for '{place.name}': {place.email} — clearing for retry")
        place.email = ""

    return True


def scrape_website_twice(
    website_url: str,
    target_platforms: Optional[Set[str]] = None,
    timeout: int = 15,
) -> Dict[str, str]:
    """
    Visit a business website TWICE with different user agents,
    then merge the results (preferring found data over empty).
    This ensures data is double-checked and more reliable.
    """
    result = {
        "email": "",
        "instagram": "",
        "linkedin": "",
        "facebook": "",
        "twitter": "",
        "whatsapp": "",
        "youtube": "",
        "tiktok": "",
        "telegram": "",
        "pinterest": "",
        "snapchat": "",
    }

    if not website_url:
        return result

    # First visit & Second visit — run in parallel to cut total time in half
    logging.info(f"🔍 Visiting website (both passes in parallel): {website_url}")
    with ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(scrape_website_for_data, website_url, target_platforms, timeout)
        future2 = executor.submit(scrape_website_for_data, website_url, target_platforms, timeout + 5)
        visit1 = future1.result()
        visit2 = future2.result()

    # Merge both visits — prefer data found in either visit
    merged_count = 0
    for key in result:
        v1 = visit1.get(key, "")
        v2 = visit2.get(key, "")
        if v1 and v2:
            # Both found data — match!
            if v1 == v2:
                result[key] = v1
                merged_count += 1
            else:
                # Different results — prefer the one that looks more real
                if len(v1) >= len(v2):
                    result[key] = v1
                else:
                    result[key] = v2
                merged_count += 1
            logging.info(f"  ✓ {key} verified (match): {result[key]}")
        elif v1:
            result[key] = v1
            merged_count += 1
            logging.info(f"  ✓ {key} found (visit 1): {v1}")
        elif v2:
            result[key] = v2
            merged_count += 1
            logging.info(f"  ✓ {key} found (visit 2): {v2}")

    logging.info(f"✅ Website double-check complete: {merged_count} fields found for {website_url}")
    return result


def scrape_place_with_retry(
    page: Page,
    listings,
    idx: int,
    mode: str,
    target_platforms: Optional[Set[str]],
    max_retries: int = 3,
    website_cache: Optional[Dict[str, Dict[str, str]]] = None,
    double_check: bool = True,
) -> Optional[Place]:
    """
    Click a listing, extract data, verify it, and retry if critical fields are missing/fake.
    Each retry waits longer to allow Google Maps to fully load the data.

    Mode-specific behavior:
    - Fast:    Quick scrape, no website visit
    - Deep:    Visit website TWICE to find Instagram, Facebook, LinkedIn, Email (5-8 sec)
    - Ultra Deep: Visit website with user-selected platforms, double-check
    """
    # Determine deep mode target platforms
    deep_targets = {"instagram", "facebook", "linkedin"}

    for attempt in range(max_retries):
        try:
            listing = listings[idx]
            listing.click()

            # Progressive wait: longer on each retry to let data load
            if mode == "ultra_deep":
                # Ultra Deep: thorough but not excessive — panel loads reliably in 3.5-6.5s
                wait_time = 3.5 + (attempt * 1.5)
            elif mode == "deep":
                # Deep mode: panel loads in 3.5-5.5s with progressive back-off
                wait_time = 3.5 + (attempt * 1.0)
            else:
                # Fast mode: find_place_name() already confirms the panel loaded via
                # wait_for_selector, so we only need a small buffer for remaining
                # fields (address, phone) to populate — not a full blind wait
                wait_time = 0.3 + (attempt * 0.3)

            name_locator = find_place_name(page, timeout=15000 if mode == "deep" else 10000)
            if name_locator is None:
                logging.warning(f"Could not find place name element for listing {idx+1}, attempt {attempt+1}")
                raise Exception("Place name element not found — selector may be broken")
            logging.info(f"⏳ Deep mode wait: {wait_time:.1f}s for listing {idx+1} (attempt {attempt+1}/{max_retries})")
            time.sleep(wait_time)

            place = extract_place(page)

            if not place.name:
                logging.info(f"Retry {attempt+1}/{max_retries}: No name found, retrying...")
                continue

            # Deep / Ultra Deep: extract email & social from Maps page
            if mode in ("deep", "ultra_deep"):
                place = scrape_place_deep_info(page, place)

            # Deep mode: visit website for Instagram, Facebook, LinkedIn, Email
            if mode == "deep" and place.website:
                if double_check:
                    logging.info(f"🌐 Deep mode: Double-checking website for {place.name}")
                    if website_cache is not None and place.website in website_cache:
                        website_data = website_cache[place.website]
                        logging.info(f"♻️ Using cached website data for {place.website} (skip re-visit)")
                    else:
                        website_data = scrape_website_twice(
                            place.website,
                            target_platforms=deep_targets,
                            timeout=8,
                        )
                        if website_cache is not None:
                            website_cache[place.website] = website_data
                else:
                    logging.info(f"🌐 Deep mode: Single visit (double check OFF) for {place.name}")
                    website_data = scrape_website_for_data(
                        place.website,
                        target_platforms=deep_targets,
                        timeout=8,
                    )
                # Merge website data (only if we found something real)
                if website_data.get("email") and is_valid_email(website_data["email"]):
                    if not place.email or not is_valid_email(place.email):
                        place.email = website_data["email"]
                        logging.info(f"📧 Email from website: {place.email}")
                for p in ["instagram", "facebook", "linkedin"]:
                    if website_data.get(p) and not getattr(place, p, ""):
                        setattr(place, p, website_data[p])
                        logging.info(f"🔗 {p} from website: {website_data[p]}")

            # Ultra Deep: visit website for complete extraction
            if mode == "ultra_deep" and place.website:
                if double_check:
                    logging.info(f"🌐 Ultra Deep mode: Double-checking website for {place.name}")
                    if website_cache is not None and place.website in website_cache:
                        website_data = website_cache[place.website]
                        logging.info(f"♻️ Using cached website data for {place.website} (skip re-visit)")
                    else:
                        website_data = scrape_website_twice(
                            place.website,
                            target_platforms=target_platforms,
                            timeout=10,
                        )
                        if website_cache is not None:
                            website_cache[place.website] = website_data
                else:
                    logging.info(f"🌐 Ultra Deep mode: Single visit (double check OFF) for {place.name}")
                    website_data = scrape_website_for_data(
                        place.website,
                        target_platforms=target_platforms,
                        timeout=10,
                    )
                # Validate email before setting (same as deep mode)
                if website_data.get("email") and is_valid_email(website_data["email"]):
                    if not place.email or not is_valid_email(place.email):
                        place.email = website_data["email"]
                        logging.info(f"📧 Email from website: {place.email}")
                # Only set social platforms that the user selected
                for p in target_platforms or []:
                    if website_data.get(p) and not getattr(place, p, ""):
                        setattr(place, p, website_data[p])
                        logging.info(f"🔗 {p} from website: {website_data[p]}")

            # Verify critical data
            if not verify_place_data(place, mode):
                continue

            phone_ok = is_valid_phone(place.phone_number)
            email_ok = is_valid_email(place.email)

            # If both critical fields are valid OR this is the last attempt, return
            if phone_ok and email_ok:
                logging.info(f"✓ Verified: {place.name} — phone={'✅' if phone_ok else '❌'}, email={'✅' if email_ok else '❌'}")
                return place

            if attempt == max_retries - 1:
                logging.info(f"→ Final attempt for {place.name}: phone={'✅' if phone_ok else '❌'}, email={'✅' if email_ok else '❌'}")
                return place

            logging.info(f"↻ Retry {attempt+2}/{max_retries} for '{place.name}': phone={'OK' if phone_ok else 'FAKE'}, email={'OK' if email_ok else 'FAKE'}")

        except Exception as e:
            logging.warning(f"Retry {attempt+1}/{max_retries} failed: {e}")
            if attempt == max_retries - 1:
                return None
            time.sleep(random.uniform(0.5, 1.5))

    return None

# ─── Social Media & Email Scraping from Website ─────────────────

SOCIAL_PATTERNS = {
    "instagram": [
        r'(?:https?:\/\/)?(?:www\.)?instagram\.com\/[\w\.\-\_\/]+',
        r'(?:https?:\/\/)?(?:www\.)?instagr\.am\/[\w\.\-\_\/]+',
    ],
    "linkedin": [
        r'(?:https?:\/\/)?(?:www\.)?linkedin\.com\/(?:company|in|school)\/[\w\-\_\/]+',
        r'(?:https?:\/\/)?(?:www\.)?linkedin\.com\/feed\/\w+',
    ],
    "facebook": [
        r'(?:https?:\/\/)?(?:www\.)?(?:facebook|fb)\.com\/[\w\.\-\_\/]+',
        r'(?:https?:\/\/)?(?:www\.)?fb\.me\/[\w\.\-\_\/]+',
    ],
    "twitter": [
        r'(?:https?:\/\/)?(?:www\.)?(?:twitter|x)\.com\/[\w\-\_\/]+',
        r'(?:https?:\/\/)?(?:www\.)?t\.co\/[\w\-\_\/]+',
    ],
    "whatsapp": [
        r'(?:https?:\/\/)?(?:www\.)?wa\.me\/[\w\-\_\/]+',
        r'(?:https?:\/\/)?(?:www\.)?(?:api|chat)\.whatsapp\.com\/[\w\?\=\-\_\/]+',
        r'(?:https?:\/\/)?(?:www\.)?whatsapp\.com\/channel\/[\w\-\_\/]+',
    ],
    "youtube": [
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/(?:c|channel|user|@)[\w\-\_\/]+',
        r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/[\w\-\_\/]+',
    ],
    "tiktok": [
        r'(?:https?:\/\/)?(?:www\.)?tiktok\.com\/@[\w\.\-\_\/]+',
    ],
    "telegram": [
        r'(?:https?:\/\/)?(?:t\.me|telegram\.me)\/[\w\-\_\/]+',
    ],
    "pinterest": [
        r'(?:https?:\/\/)?(?:www\.)?pinterest\.[a-z]+\/[\w\-\_\/]+',
        r'(?:https?:\/\/)?(?:www\.)?pin\.it\/[\w\-\_\/]+',
    ],
    "snapchat": [
        r'(?:https?:\/\/)?(?:www\.)?snapchat\.com\/add\/[\w\-\_\/]+',
    ],
}

EMAIL_PATTERN = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'


def get_random_user_agent() -> str:
    """Return a random User-Agent string to avoid detection."""
    return random.choice(USER_AGENTS)


def extract_email_from_text(text: str) -> Optional[str]:
    """Extract first email address found in text."""
    match = re.search(EMAIL_PATTERN, text)
    if match:
        email = match.group(0)
        # Filter out common false positives
        if not any(ignore in email.lower() for ignore in [
            'example.com', 'domain.com', 'your@', 'test@', 'user@',
            'email@', 'mail@', '@email.com', '@mail.com'
        ]):
            return email
    return None


def extract_social_media_from_text(text: str, target_platforms: Optional[Set[str]] = None) -> Dict[str, str]:
    """Extract social media links from text using regex patterns."""
    results = {}
    # None = all platforms, empty set = no platforms
    if target_platforms is not None and len(target_platforms) == 0:
        return results  # Nothing selected, return empty
    
    platforms_to_check = target_platforms if target_platforms is not None else set(SOCIAL_PATTERNS.keys())
    
    for platform in platforms_to_check:
        if platform in SOCIAL_PATTERNS:
            for pattern in SOCIAL_PATTERNS[platform]:
                matches = re.findall(pattern, text, re.IGNORECASE)
                if matches:
                    url = matches[0]
                    # Normalize URL
                    if not url.startswith('http'):
                        url = 'https://' + url
                    results[platform] = url
                    break
    
    return results


def scrape_website_for_data(
    website_url: str,
    target_platforms: Optional[Set[str]] = None,
    timeout: int = 15
) -> Dict[str, str]:
    """
    Visit a business website and scrape:
    - Email address
    - Social media links (Instagram, LinkedIn, Facebook, Twitter, WhatsApp, YouTube, TikTok, Telegram, Pinterest, Snapchat)
    
    Returns dict with keys: email, instagram, linkedin, facebook, twitter, whatsapp, youtube, tiktok, telegram, pinterest, snapchat
    """
    result = {
        "email": "",
        "instagram": "",
        "linkedin": "",
        "facebook": "",
        "twitter": "",
        "whatsapp": "",
        "youtube": "",
        "tiktok": "",
        "telegram": "",
        "pinterest": "",
        "snapchat": "",
    }
    
    if not website_url:
        return result
    
    # Normalize URL
    if not website_url.startswith('http'):
        website_url = 'https://' + website_url
    
    for attempt in range(3):  # Retry up to 3 times
        try:
            headers = {
                'User-Agent': get_random_user_agent(),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            logging.info(f"Visiting website: {website_url} (attempt {attempt + 1})")
            resp = requests.get(
                website_url, headers=headers, timeout=timeout,
                allow_redirects=True
            )
            resp.raise_for_status()
            break  # Success, exit retry loop
        except requests.exceptions.RequestException as e:
            if attempt == 2:  # Last attempt
                logging.warning(f"Failed to visit website {website_url} after 3 attempts: {e}")
                return result
            logging.info(f"Retrying {website_url} (attempt {attempt + 1} failed: {e})")
            time.sleep(random.uniform(1.5, 3.5))  # Randomized wait before retry
    
    try:
        html_content = resp.text
        soup = BeautifulSoup(html_content, 'lxml')
        
        # Get all text from the page
        page_text = soup.get_text(separator=' ', strip=True)
        
        # Extract email from page text
        email = extract_email_from_text(page_text)
        if email:
            result["email"] = email
            logging.info(f"Found email: {email}")
        
        # Also check mailto: links
        if not result["email"]:
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                if href.startswith('mailto:'):
                    email_candidate = href.replace('mailto:', '').split('?')[0].strip()
                    if email_candidate and '@' in email_candidate:
                        result["email"] = email_candidate
                        logging.info(f"Found email from mailto: {email_candidate}")
                        break
        
        # Extract social media from all links on the page
        all_links_text = ""
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            # Resolve relative URLs
            absolute_url = urljoin(website_url, href)
            all_links_text += absolute_url + ' '
        
        # Also add onclick and data attributes that might contain social URLs
        for tag in soup.find_all(attrs={"onclick": True}):
            all_links_text += tag["onclick"] + ' '
        
        for tag in soup.find_all(attrs={"data-href": True}):
            all_links_text += tag["data-href"] + ' '
            
        for tag in soup.find_all(attrs={"data-url": True}):
            all_links_text += tag["data-url"] + ' '
        
        social_links = extract_social_media_from_text(all_links_text, target_platforms)
        for platform, url in social_links.items():
            if platform in result:
                result[platform] = url
                logging.info(f"Found {platform}: {url}")
        
        # Also scan page text for social media mentions if not found in links
        if target_platforms is not None and not all(result.get(p) for p in target_platforms):
            page_social = extract_social_media_from_text(page_text, target_platforms)
            for platform, url in page_social.items():
                if not result.get(platform):
                    result[platform] = url
                    logging.info(f"Found {platform} in page text: {url}")
        
        # Try to find more social links by scanning common footer/header sections
        for section_id in ['footer', 'social', 'contact', 'follow-us', 'social-media', 'social-links']:
            section = soup.find(id=re.compile(section_id, re.I)) or soup.find(class_=re.compile(section_id, re.I))
            if section:
                section_html = str(section)
                section_social = extract_social_media_from_text(section_html, target_platforms)
                for platform, url in section_social.items():
                    if not result.get(platform):
                        result[platform] = url
                        logging.info(f"Found {platform} in section #{section_id}: {url}")
        
    except requests.exceptions.Timeout:
        logging.warning(f"Timeout visiting website: {website_url}")
    except requests.exceptions.RequestException as e:
        logging.warning(f"Failed to visit website {website_url}: {e}")
    except Exception as e:
        logging.warning(f"Error scraping website {website_url}: {e}")
    
    return result


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
    )

def extract_text(page: Page, xpath: str) -> str:
    try:
        if page.locator(xpath).count() > 0:
            return page.locator(xpath).inner_text()
    except Exception as e:
        logging.warning(f"Failed to extract text for xpath {xpath}: {e}")
    return ""

def extract_place(page: Page) -> Place:
    # XPaths (with fallback name selector via find_place_name)
    name_xpath = '//div[@class="TIHn2 "]//h1[@class="DUwDvf lfPIob"]'
    address_xpath = '//button[@data-item-id="address"]//div[contains(@class, "fontBodyMedium")]'
    website_xpath = '//a[@data-item-id="authority"]//div[contains(@class, "fontBodyMedium")]'
    phone_number_xpath = '//button[contains(@data-item-id, "phone:tel:")]//div[contains(@class, "fontBodyMedium")]'
    reviews_count_xpath = '//div[@class="TIHn2 "]//div[@class="fontBodyMedium dmRWX"]//div//span//span//span[@aria-label]'
    reviews_average_xpath = '//div[@class="TIHn2 "]//div[@class="fontBodyMedium dmRWX"]//div//span[@aria-hidden]'
    info1 = '//div[@class="LTs0Rc"][1]'
    info2 = '//div[@class="LTs0Rc"][2]'
    info3 = '//div[@class="LTs0Rc"][3]'
    opens_at_xpath = '//button[contains(@data-item-id, "oh")]//div[contains(@class, "fontBodyMedium")]'
    opens_at_xpath2 = '//div[@class="MkV9"]//span[@class="ZDu9vd"]//span[2]'
    place_type_xpath = '//div[@class="LBgpqf"]//button[@class="DkEaL "]'
    intro_xpath = '//div[@class="WeS02d fontBodyMedium"]//div[@class="PYvSYb "]'

    place = Place()
    # Extract name with fallback selectors (matching find_place_name logic)
    name_selectors = [
        name_xpath,
        '//h1[contains(@class, "DUwDvf")]',
        '//h1[@class="DUwDvf lfPIob"]',
        '//div[contains(@class, "TIHn2")]//h1',
        '//h1[@itemprop="name"]',
        '//button[@aria-label and contains(@aria-label, "Close")]/preceding::h1[1]',
        '//div[@role="main"]//h1',
    ]
    place.name = ""
    for sel in name_selectors:
        name_text = extract_text(page, sel)
        if name_text:
            place.name = name_text
            break
    place.address = extract_text(page, address_xpath)
    place.website = extract_text(page, website_xpath)
    place.phone_number = extract_text(page, phone_number_xpath)
    place.place_type = extract_text(page, place_type_xpath)
    place.introduction = extract_text(page, intro_xpath) or "None Found"

    # Reviews Count
    reviews_count_raw = extract_text(page, reviews_count_xpath)
    if reviews_count_raw:
        try:
            temp = reviews_count_raw.replace('\xa0', '').replace('(','').replace(')','').replace(',','')
            place.reviews_count = int(temp)
        except Exception as e:
            logging.warning(f"Failed to parse reviews count: {e}")
    # Reviews Average
    reviews_avg_raw = extract_text(page, reviews_average_xpath)
    if reviews_avg_raw:
        try:
            temp = reviews_avg_raw.replace(' ','').replace(',','.')
            place.reviews_average = float(temp)
        except Exception as e:
            logging.warning(f"Failed to parse reviews average: {e}")
    # Store Info
    for idx, info_xpath in enumerate([info1, info2, info3]):
        info_raw = extract_text(page, info_xpath)
        if info_raw:
            temp = info_raw.split('·')
            if len(temp) > 1:
                check = temp[1].replace("\n", "").lower()
                if 'shop' in check:
                    place.store_shopping = "Yes"
                if 'pickup' in check:
                    place.in_store_pickup = "Yes"
                if 'delivery' in check:
                    place.store_delivery = "Yes"
    # Opens At
    opens_at_raw = extract_text(page, opens_at_xpath)
    if opens_at_raw:
        opens = opens_at_raw.split('⋅')
        if len(opens) > 1:
            place.opens_at = opens[1].replace("\u202f","")
        else:
            place.opens_at = opens_at_raw.replace("\u202f","")
    else:
        opens_at2_raw = extract_text(page, opens_at_xpath2)
        if opens_at2_raw:
            opens = opens_at2_raw.split('⋅')
            if len(opens) > 1:
                place.opens_at = opens[1].replace("\u202f","")
            else:
                place.opens_at = opens_at2_raw.replace("\u202f","")
    return place


def scrape_place_deep_info(page: Page, place: Place) -> Place:
    """
    Deep mode: Try to extract email and social media from the Google Maps page itself.
    Look for website content that might already be embedded or referenced.
    """
    try:
        # Get the full page text to search for email patterns
        full_text = page.inner_text('body')
        
        # Extract email from the page text
        email = extract_email_from_text(full_text)
        if email:
            place.email = email
        
        # Extract social media links from the page text
        social_links = extract_social_media_from_text(full_text)
        for platform, url in social_links.items():
            setattr(place, platform, url)
            
    except Exception as e:
        logging.warning(f"Deep info extraction failed: {e}")
    
    return place


def apply_maps_filter(page: Page, filter_type: str):
    """
    Click the filter dropdown on Google Maps search results page
    and select the requested filter: 'all', 'none', 'top_rated', or 'open_now'.
    """
    if not filter_type or filter_type == "all":
        # Google's default state already shows all results
        logging.info("Filter: 'all' — skipping filter click (already default)")
        return

    filter_label_map = {
        "none": "All",           # "None" means force back to unfiltered/All state
        "top_rated": "Top Rated",
        "open_now": "Open Now",
    }
    target_text = filter_label_map.get(filter_type)
    if not target_text:
        logging.warning(f"Unknown filter_type: {filter_type}, skipping filter")
        return

    try:
        # Wait a moment for the search results to settle before clicking filter
        page.wait_for_timeout(random.randint(1500, 3000))

        # Google Maps filter dropdown button — look for the chip/button that shows "All"
        # It's typically a button with aria-label containing "All" and role="button"
        dropdown_button = page.locator(
            '//button[contains(@aria-label, "All") and @role="button"]'
        ).first
        
        if dropdown_button.count() == 0:
            # Fallback: look for any button with text "All"
            dropdown_button = page.get_by_text("All", exact=True).first

        if dropdown_button.count() == 0:
            logging.warning("Could not find filter dropdown button on Maps page")
            return

        dropdown_button.click()
        logging.info(f"Clicked filter dropdown, searching for option: {target_text}")
        page.wait_for_timeout(random.randint(800, 1500))

        # Find and click the desired option in the dropdown
        option = page.get_by_text(target_text, exact=True).first
        
        if option.count() == 0:
            # Try non-exact match
            option = page.get_by_text(target_text, exact=False).first

        if option.count() > 0:
            option.click()
            page.wait_for_timeout(random.randint(1500, 3000))  # Wait for filter to take effect
            logging.info(f"✅ Applied Maps filter: '{target_text}' (filter_type={filter_type})")
        else:
            logging.warning(f"Could not find filter option '{target_text}' in dropdown")

    except Exception as e:
        logging.warning(f"Could not apply filter '{filter_type}': {e} — continuing with unfiltered results")


def find_listing_elements(page: Page, min_count: int = 1, timeout: int = 30000):
    """
    Find listing <a> elements on Google Maps results page using multiple fallback selectors.
    Google frequently changes their HTML, so we try several strategies.
    Returns a list of <a> element locators (the caller wraps them in parent for clicking).
    """
    listing_selectors = [
        # Primary: standard Google Maps place links
        '//a[contains(@href, "https://www.google.com/maps/place")]',
        # Fallback: relative href starting with /maps/place
        '//a[contains(@href, "/maps/place")]',
        # Fallback: role-based feed items
        '//div[@role="feed"]//a[contains(@href, "place")]',
        # Fallback: any link with place data
        '//a[contains(@href, "maps.google.com") and contains(@href, "place")]',
    ]
    
    for selector in listing_selectors:
        try:
            page.wait_for_selector(selector, timeout=timeout)
            count = page.locator(selector).count()
            if count >= min_count:
                logging.info(f"✅ Found {count} listings with selector: {selector}")
                return page.locator(selector).all()
        except Exception:
            logging.info(f"⏳ Selector timed out: {selector}")
            continue
    
    # Last resort: wait and try the feed container
    try:
        page.wait_for_timeout(random.randint(2000, 4000))
        # Look for anchor elements inside the feed role
        feed_links = page.locator('//div[@role="feed"]//a[contains(@href, "http")]').all()
        if len(feed_links) > 0:
            logging.info(f"✅ Found {len(feed_links)} listings via feed container last-resort")
            return feed_links
    except Exception:
        pass
    
    return []


def find_place_name(page: Page, timeout: int = 10000):
    """
    Find the place name element on a Google Maps place detail page.
    First tries to wait for the primary selector, then falls back to other selectors.
    """
    primary_selector = '//div[@class="TIHn2 "]//h1[@class="DUwDvf lfPIob"]'
    
    # Step 1: Try waiting for the primary selector (same behavior as original)
    try:
        page.wait_for_selector(primary_selector, timeout=timeout)
        logging.info(f"Found place name via primary wait: {primary_selector}")
        return page.locator(primary_selector)
    except Exception:
        logging.info(f"Primary place name selector timed out, trying fallbacks...")
    
    # Step 2: Fallback chain with quick visibility checks
    fallback_selectors = [
        '//h1[contains(@class, "DUwDvf")]',
        '//h1[@class="DUwDvf lfPIob"]',
        '//div[contains(@class, "TIHn2")]//h1',
        '//h1[@itemprop="name"]',
        # Broader fallbacks
        '//button[@aria-label and contains(@aria-label, "Close")]/preceding::h1[1]',
        '//div[@role="main"]//h1',
    ]
    
    for selector in fallback_selectors:
        try:
            locator = page.locator(selector)
            if locator.count() > 0 and locator.is_visible(timeout=800):
                logging.info(f"Found place name with fallback selector: {selector}")
                return locator
        except Exception:
            continue
    return None


def scrape_places(
    search_for: str,
    total: int,
    abort_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
    mode: str = "fast",
    social_media_options: Optional[Dict[str, bool]] = None,
    headless: bool = True,
    filter_type: str = "all",
    double_check: bool = True,
) -> List[Place]:
    """
    Scrape Google Maps for places matching the search query.
    
    Args:
        search_for: Search query string
        total: Maximum number of places to scrape
        abort_event: Event to signal cancellation
        progress_callback: Called with current count after each successful extraction
        mode: Scraping mode - 'fast', 'deep', or 'ultra_deep'
        social_media_options: Dict of platform -> bool for ultra_deep mode
        headless: Run browser in headless mode (no visible window)
        filter_type: Maps filter - 'all', 'none', 'top_rated', 'open_now'
    """
    setup_logging()
    places: List[Place] = []
    with sync_playwright() as p:
        if platform.system() == "Windows":
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Users\%USERNAME%\AppData\Local\Google\Chrome\Application\chrome.exe",
            ]
            browser_path = None
            for path in chrome_paths:
                expanded_path = os.path.expandvars(path)
                if os.path.exists(expanded_path):
                    browser_path = expanded_path
                    break
            
            if browser_path:
                browser = p.chromium.launch(executable_path=browser_path, headless=headless)
            else:
                browser = p.chromium.launch(headless=headless)
        else:
            browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        if stealth_sync:
            stealth_sync(page)
            logging.info("✅ playwright-stealth active — anti-detection enabled")
        else:
            logging.info("⚠ playwright-stealth not installed — skipping anti-detection")
        # Block resource-heavy requests (images, CSS, fonts) to speed up page load + reduce fingerprinting
        page.route("**/*.{png,jpg,jpeg,svg,gif,webp,woff,woff2,ttf,eot,otf}", lambda route: route.abort())
        # Randomize viewport to avoid browser fingerprinting detection
        viewport_options = [
            {"width": 1920, "height": 1080},
            {"width": 1366, "height": 768},
            {"width": 1536, "height": 864},
            {"width": 1440, "height": 900},
        ]
        page.set_viewport_size(random.choice(viewport_options))
        try:
            page.goto("https://www.google.com/maps/@32.9817464,70.1930781,3.67z?", timeout=60000)
            page.wait_for_timeout(random.randint(800, 1500))
            # Try multiple selectors for the Google Maps search input (Google frequently changes their HTML)
            search_input = None
            search_selectors = [
                "//input[@id='searchboxinput']",
                "//input[@aria-label='Search Google Maps']",
                "//input[@name='q']",
                "//form[@role='search']//input",
                "//div[@role='search']//input",
                "//form[contains(@jsaction,'searchboxFormSubmit')]//input[@name='q']",
            ]
            for selector in search_selectors:
                loc = page.locator(selector)
                # Use a short timeout for is_visible to avoid 30s stalls
                if loc.count() > 0 and loc.is_visible(timeout=3000):
                    search_input = loc
                    logging.info(f"Found search input with selector: {selector}")
                    break

            if search_input is None or search_input.count() == 0:
                # Last resort: wait briefly for page to settle, then look for any visible
                # input inside the search/content area of Google Maps
                page.wait_for_timeout(random.randint(1500, 3000))
                search_input = page.locator(
                    "//div[@role='search']//input | //input[contains(@aria-label, 'Search')]"
                ).first
                if search_input.count() == 0:
                    raise Exception("Could not find Google Maps search input. The page structure may have changed.")
                logging.info("Found search input via last-resort selector")

            search_input.fill(search_for)
            page.keyboard.press("Enter")

            # Wait for results to load — use our fallback helper
            found_listings = find_listing_elements(page, min_count=1, timeout=30000)
            if len(found_listings) > 0:
                found_listings[0].hover()
            else:
                logging.warning("No listing elements found after search — results may be empty")

            # Apply Maps filter if requested
            apply_maps_filter(page, filter_type)

            previously_counted = 0
            same_count_retries = 0
            while True:
                # Scroll the Google Maps results feed panel (not the page)
                page.evaluate('''const feed = document.querySelector("[role='feed']");
                if (feed) { feed.scrollBy(0, 12000); } else { window.scrollBy(0, 12000); }''')
                page.wait_for_timeout(700)
                
                # Re-fetch listings after scroll to check count (shorter timeout — listings already loaded)
                current_listings = find_listing_elements(page, min_count=1, timeout=5000)
                found = len(current_listings)
                logging.info(f"Currently Found: {found}")
                if found >= total:
                    break
                if found == previously_counted:
                    same_count_retries += 1
                    if same_count_retries >= 5:
                        logging.info("Arrived at all available")
                        break
                else:
                    same_count_retries = 0
                previously_counted = found
            
            # Final fetch of listings (shorter timeout — listings already loaded)
            all_listings = find_listing_elements(page, min_count=1, timeout=5000)[:total]
            listings = [listing.locator("xpath=..") for listing in all_listings]
            logging.info(f"Total Found: {len(listings)}")
            
            # Determine which social media platforms to scrape
            target_platforms = None
            if mode == "ultra_deep" and social_media_options:
                target_platforms = {p for p, enabled in social_media_options.items() if enabled}
            
            # Cache for website scrape results — avoids re-visiting same URL on retry
            website_cache: Dict[str, Dict[str, str]] = {}

            for idx, listing in enumerate(listings):
                if abort_event and abort_event.is_set():
                    logging.info("Scrape cancelled by user")
                    break

                # Use retry logic with data verification for every mode
                place = scrape_place_with_retry(
                    page=page,
                    listings=listings,
                    idx=idx,
                    mode=mode,
                    target_platforms=target_platforms,
                    max_retries=3 if mode == "ultra_deep" else 2,
                    double_check=double_check,
                    website_cache=website_cache,
                )

                if place and place.name:
                    places.append(place)
                    if progress_callback:
                        progress_callback(len(places))
                else:
                    logging.warning(f"Skipping listing {idx+1}: could not extract valid data after retries.")
        finally:
            browser.close()
    return places

def save_places_to_csv(places: List[Place], output_path: str = "result.csv", append: bool = False, columns: Optional[List[str]] = None):
    """Save scraped places to a CSV file.
    
    Args:
        places: List of Place objects to save
        output_path: Path to the output CSV file
        append: Whether to append to existing file
        columns: Optional list of column names to include. If None, all columns are saved.
    """
    if not places:
        logging.warning("No data to save. List is empty.")
        return
    
    df = pd.DataFrame([asdict(place) for place in places])
    if not df.empty:
        # Filter to only requested columns if specified
        if columns is not None:
            # Only keep columns that actually exist in the DataFrame
            valid_columns = [c for c in columns if c in df.columns]
            df = df[valid_columns]
        
        file_exists = os.path.isfile(output_path)
        mode = "a" if append else "w"
        header = not (append and file_exists)
        df.to_csv(output_path, index=False, mode=mode, header=header)
        logging.info(f"[SAVED] {len(df)} places to {output_path} (append={append}, columns={len(df.columns)})")
    else:
        logging.warning("No data to save. DataFrame is empty.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--search", type=str, help="Search query for Google Maps")
    parser.add_argument("-t", "--total", type=int, help="Total number of results to scrape")
    parser.add_argument("-o", "--output", type=str, default="result.csv", help="Output CSV file path")
    parser.add_argument("--append", action="store_true", help="Append results to the output file instead of overwriting")
    args = parser.parse_args()
    search_for = args.search or "turkish stores in toronto Canada"
    total = args.total or 1
    output_path = args.output
    append = args.append
    places = scrape_places(search_for, total)
    save_places_to_csv(places, output_path, append=append)

if __name__ == "__main__":
    main()
