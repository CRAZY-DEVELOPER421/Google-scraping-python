import logging
import sys
import os
import uuid
import threading
import smtplib
import tempfile
from typing import List, Optional, Dict
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

# ─── Suppress Flask/Werkzeug startup noise ────────────────
# Keep only our custom banner, hide Flask defaults
import werkzeug.serving
werkzeug.serving._log_add_style = False  # type: ignore[attr-defined]
logging.getLogger('werkzeug').setLevel(logging.ERROR)
os.environ['FLASK_RUN_FROM_CLI'] = 'false'

dotenv_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=dotenv_path)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main import scrape_places, Place, save_places_to_csv, setup_logging
from database.saved_data_service import search_saved_places
from ai.routes import ai_bp

app = Flask(__name__)
app.register_blueprint(ai_bp)
app.config['TEMPLATES_AUTO_RELOAD'] = True
CORS(app, resources={r"/scrape*": {"origins": "*"}})

setup_logging()

# ─── Configuration ─────────────────────────────────────────

MAX_TOTAL = 30
JOB_CLEANUP_AGE_MINUTES = 60
JOB_CLEANUP_INTERVAL_SECONDS = 300  # Run cleanup every 5 minutes


@dataclass
class ScrapeJob:
    job_id: str
    keyword: str
    location: str
    total: int
    filter_type: str = "all"        # all | none | top_rated | open_now
    mode: str = "fast"              # fast | deep | ultra_deep
    social_media_options: Optional[Dict[str, bool]] = None
    headless: bool = False
    double_check: bool = True
    email: Optional[str] = None
    status: str = "pending"         # pending | running | completed | cancelled | error
    results: List[dict] = field(default_factory=list)
    ai_results: Optional[List[dict]] = None  # AI Search results (for email attachment)
    scraped_so_far: int = 0
    error: Optional[str] = None
    abort_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
    created_at: datetime = field(default_factory=datetime.now)
    # Multi-location fields
    locations: List[str] = field(default_factory=list)  # All locations for multi-scrape
    current_location_index: int = 0                     # Which location is being scraped
    location_totals: List[int] = field(default_factory=list)  # Per-location result counts


# In-memory job store
jobs: dict[str, ScrapeJob] = {}
jobs_lock = threading.Lock()


def _build_scrape_query(keyword: str, location: str, total: int, filter_type: str = "all") -> str:
    """
    Build a search query for the main Google Maps scraper with quantity and filter.

    - "all" or "none": "{total} {keyword} in {location}"
    - "top_rated": "{total} top rated {keyword} in {location}"
    - "open_now": "{total} new {keyword} in {location}"
    """
    if filter_type == "top_rated":
        return f"{total} top rated {keyword} in {location}"
    elif filter_type == "open_now":
        return f"{total} new {keyword} in {location}"
    else:  # "all" or "none"
        return f"{total} {keyword} in {location}"


def update_job_progress(job: ScrapeJob, count: int):
    """Thread-safe update of job's scraped_so_far counter."""
    with jobs_lock:
        job.scraped_so_far = count


def run_single_scrape(job: ScrapeJob, search_query: str, per_location_total: int = 0) -> List[Place]:
    """Run a single scrape for one location query. Returns list of Place objects."""
    total_to_scrape = per_location_total if per_location_total > 0 else job.total

    places: List[Place] = scrape_places(
        search_for=search_query,
        total=total_to_scrape,
        abort_event=job.abort_event,
        progress_callback=lambda count: update_job_progress(job, count),
        mode=job.mode,
        social_media_options=job.social_media_options,
        headless=job.headless,
        filter_type=job.filter_type,
        double_check=job.double_check,
    )
    return places


def deduplicate_places(places_list: List[Place]) -> List[Place]:
    """Deduplicate Place objects by name (case-insensitive).
    First occurrence wins, subsequent duplicates are dropped."""
    seen: Set[str] = set()
    unique: List[Place] = []
    for place in places_list:
        key = place.name.strip().lower() if place.name else ""
        if key and key not in seen:
            seen.add(key)
            unique.append(place)
    return unique


def scrape_worker(job: ScrapeJob):
    """Run the scraper in a background thread, checking abort_event.
    Supports both single-location and multi-location (comma-separated) scraping."""

    try:
        with jobs_lock:
            job.status = "running"

        all_places: List[Place] = []

        # Check if multi-location (comma-separated)
        locations = job.locations if job.locations else [job.location]
        total_locations = len(locations)

        if total_locations > 1:
            # ─── Multi-location scraping ───
            # Distribute total across locations evenly (remainder goes to LAST locations)
            per_location = job.total // total_locations
            remainder = job.total % total_locations
            location_totals = []
            for i in range(total_locations):
                # Last 'remainder' locations get +1 each
                lt = per_location + (1 if i >= total_locations - remainder else 0)
                location_totals.append(lt)

            with jobs_lock:
                job.location_totals = location_totals

            for idx, loc in enumerate(locations):
                if job.abort_event.is_set():
                    break

                with jobs_lock:
                    job.current_location_index = idx

                loc = loc.strip()
                if not loc:
                    continue

                target_for_this = location_totals[idx]
                search_query = _build_scrape_query(job.keyword, loc, target_for_this, job.filter_type)
                logging.info(f"📍 Multi-scrape: scraping location {idx+1}/{total_locations}: '{loc}' (target: {target_for_this})")

                try:
                    places = run_single_scrape(job, search_query, target_for_this)
                    all_places.extend(places)

                    with jobs_lock:
                        job.scraped_so_far = len(all_places)

                    # Redistribute: if this location returned fewer results than target,
                    # add remaining to subsequent locations so total target is met
                    actual_count = len(places)
                    if actual_count < target_for_this and idx < total_locations - 1:
                        remaining = target_for_this - actual_count
                        # Distribute remaining to next locations evenly
                        remaining_locs = total_locations - idx - 1
                        extra_per = remaining // remaining_locs
                        extra_rem = remaining % remaining_locs
                        for j in range(idx + 1, total_locations):
                            add = extra_per + (1 if j - (idx + 1) < extra_rem else 0)
                            location_totals[j] += add
                        logging.info(f"↻ Redistributing {remaining} results to remaining {remaining_locs} locations")
                        with jobs_lock:
                            job.location_totals = location_totals

                except Exception as e:
                    logging.warning(f"Failed to scrape location '{loc}': {e}")
                    continue

            # Deduplicate across all locations
            all_places = deduplicate_places(all_places)

        else:
            # ─── Single-location scraping ───
            search_query = _build_scrape_query(job.keyword, job.location, job.total, job.filter_type)
            all_places = run_single_scrape(job, search_query)
            all_places = deduplicate_places(all_places)

        results = [asdict(place) for place in all_places]

        with jobs_lock:
            if job.abort_event.is_set():
                job.status = "cancelled"
                job.results = results
            else:
                job.status = "completed"
                job.results = results
                job.scraped_so_far = len(results)
        
        # ─── Email sending (OUTSIDE the lock — avoids deadlock) ───
        if job.email and results and job.status == "completed":
            location_label = job.location if total_locations <= 1 else f"{total_locations} locations"
            try:
                with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
                    temp_csv_path = tmp.name
                places_objs = [Place(**p) for p in results]
                mode_columns = get_columns_for_mode(job.mode, job.social_media_options)
                save_places_to_csv(places_objs, temp_csv_path, columns=mode_columns)
                
                # Wait for AI search results (up to 45s) for email — NO lock held
                ai_results = None
                for _ in range(45):
                    # Read ai_results without holding the lock (safe: only set once by /ai-results endpoint)
                    if job.ai_results is not None:
                        ai_results = job.ai_results
                        break
                    if job.abort_event.is_set():
                        break
                    threading.Event().wait(1.0)
                
                if ai_results:
                    logging.info(f"📧 Including {len(ai_results)} AI Search results in email")
                else:
                    logging.info(f"📧 AI results not available within timeout — sending scraper-only email")
                
                send_results_email(job.email, temp_csv_path, job.keyword, location_label, len(results), ai_results)
            except Exception as e:
                logging.warning(f"Email sending failed: {e}")
            finally:
                if os.path.exists(temp_csv_path):
                    os.remove(temp_csv_path)

    except Exception as e:
        logging.exception("Scraping failed")
        with jobs_lock:
            job.status = "error"
            job.error = str(e)


def send_results_email(to_email: str, csv_path: str, keyword: str, location: str, total_results: int, ai_results: Optional[List[dict]] = None) -> bool:
    """
    Send an email with the CSV results attached using Gmail SMTP.
    If AI search results are provided, they are attached as a second CSV file.
    Returns True if sent successfully, False otherwise.
    """
    smtp_email = os.environ.get("SMTP_EMAIL")
    smtp_password = os.environ.get("SMTP_APP_PASSWORD")

    if not smtp_email or not smtp_password:
        logging.warning("SMTP credentials not configured (SMTP_EMAIL / SMTP_APP_PASSWORD), skipping email")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_email
        msg["To"] = to_email
        msg["Subject"] = f"Your Zaucto Scraper results are ready! ({total_results} places found)"

        ai_count = len(ai_results) if ai_results else 0
        ai_line = f"\nPlus {ai_count} businesses found by AI Search." if ai_count else ""
        body = f"""Hi,

Your scraping job for "{keyword}" in "{location}" is complete!

We found {total_results} places from Google Maps.{ai_line}

Scraper results are attached as 'zaucto_results.csv'.
"""
        if ai_count:
            body += "AI Search results are attached as 'zaucto_ai_results.csv'.\n"
        body += """
Thanks for using Zaucto Scraper.
"""
        msg.attach(MIMEText(body, "plain"))

        # Attach scraper results CSV
        with open(csv_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename=zaucto_results.csv")
        msg.attach(part)

        # Attach AI results CSV (if available)
        if ai_results:
            ai_csv_lines = []
            ai_csv_lines.append("Name,Address,Email,Phone Number,Website")
            for biz in ai_results:
                name = (biz.get("name") or "").replace('"', '""')
                address = (biz.get("address") or "").replace('"', '""')
                email = (biz.get("email") or "").replace('"', '""')
                phone = (biz.get("phone_number") or "").replace('"', '""')
                website = (biz.get("website") or "").replace('"', '""')
                ai_csv_lines.append(f'"{name}","{address}","{email}","{phone}","{website}"')
            ai_csv_content = "\n".join(ai_csv_lines)
            
            part2 = MIMEBase("application", "octet-stream")
            part2.set_payload(ai_csv_content.encode("utf-8"))
            encoders.encode_base64(part2)
            part2.add_header("Content-Disposition", f"attachment; filename=zaucto_ai_results.csv")
            msg.attach(part2)

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(smtp_email, smtp_password)
        server.sendmail(smtp_email, to_email, msg.as_string())
        server.quit()

        logging.info(f"Email sent successfully to {to_email} (scraper={total_results}, ai={ai_count})")
        return True

    except Exception as e:
        logging.warning(f"Failed to send email to {to_email}: {e}")
        return False


@app.route("/scrape/job/<job_id>/ai-results", methods=["POST"])
def store_ai_results(job_id: str):
    """
    Store AI Search results in the scrape job for email inclusion.
    Called by the frontend after AI search completes.
    """
    data = request.get_json() or {}
    results = data.get("results", [])
    if not isinstance(results, list):
        return jsonify({"error": "Invalid results format"}), 400
    
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        job.ai_results = results
        logging.info(f"✅ AI results stored for job {job_id}: {len(results)} businesses")
    
    return jsonify({"success": True, "count": len(results)})


def cleanup_old_jobs():
    """Remove jobs older than JOB_CLEANUP_AGE_MINUTES to free memory."""
    while True:
        threading.Event().wait(JOB_CLEANUP_INTERVAL_SECONDS)
        cutoff = datetime.now() - timedelta(minutes=JOB_CLEANUP_AGE_MINUTES)
        with jobs_lock:
            old_ids = [
                jid for jid, j in jobs.items()
                if j.created_at < cutoff and j.status in ("completed", "cancelled", "error")
            ]
            for jid in old_ids:
                del jobs[jid]
            if old_ids:
                logging.info(f"Cleaned up {len(old_ids)} old jobs")


# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_old_jobs, daemon=True)
cleanup_thread.start()


# ─── Column visibility per mode ───────────────────────────

def get_columns_for_mode(mode: str, social_media_options: Optional[Dict[str, bool]] = None) -> list:
    """
    Return the list of column keys to display in the results table
    based on the scraping mode and selected social media platforms.
    """
    # Base columns that always show in all modes (NO email, NO social in base)
    base = [
        "name", "phone_number", "address", "website",
        "reviews_count", "reviews_average",
        "place_type", "opens_at",
        "store_shopping", "in_store_pickup", "store_delivery",
        "introduction",
    ]

    if mode == "fast":
        # Fast mode: ONLY base columns — NO email, NO social media
        return base

    elif mode == "deep":
        # Deep mode: base + email + Instagram + Facebook + LinkedIn
        return base + ["email", "instagram", "facebook", "linkedin"]

    elif mode == "ultra_deep":
        # Ultra Deep: base + email + only the allowed social platforms the user selected
        ALLOWED_PLATFORMS = {"instagram", "linkedin", "facebook", "twitter", "whatsapp"}
        social_cols = []
        if social_media_options:
            for platform, enabled in social_media_options.items():
                if enabled and platform != "email" and platform in ALLOWED_PLATFORMS:
                    social_cols.append(platform)
        # Always include email for ultra_deep
        return base + ["email"] + sorted(social_cols)

    return base


# ─── Routes ────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


def parse_locations(location_str: str) -> List[str]:
    """
    Parse comma-separated location string into a list of trimmed locations.
    Returns empty list if no commas found (single location mode).
    """
    parts = [loc.strip() for loc in location_str.split(",") if loc.strip()]
    return parts if len(parts) > 1 else []


@app.route("/scrape", methods=["POST"])
def start_scrape():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400

    keyword = data.get("keyword", "").strip()
    location = data.get("location", "").strip()
    total = data.get("total", 10)
    mode = data.get("mode", "fast").strip().lower()
    filter_type = data.get("filter_type", "all").strip().lower()
    if filter_type not in ("all", "none", "top_rated", "open_now"):
        filter_type = "all"
    email = data.get("email", "").strip()
    if email and ("@" not in email or "." not in email):
        email = ""  # invalid email, ignore silently
    social_media_options = data.get("social_media_options", None)
    headless = data.get("headless", False)  # Default False - show browser window
    double_check = data.get("double_check", True)

    if not keyword or not location:
        return jsonify({"error": "Keyword and location are required"}), 400

    if mode not in ("fast", "deep", "ultra_deep"):
        mode = "fast"

    try:
        total = int(total)
        total = max(1, min(total, MAX_TOTAL))
    except (ValueError, TypeError):
        total = 10

    # Validate social_media_options if provided
    if social_media_options is not None and not isinstance(social_media_options, dict):
        social_media_options = None

    # Parse comma-separated locations for multi-scraping
    locations = parse_locations(location)
    is_multi = len(locations) > 1

    job_id = uuid.uuid4().hex[:12]
    job = ScrapeJob(
        job_id=job_id,
        keyword=keyword,
        location=location,
        total=total,
        filter_type=filter_type,
        mode=mode,
        social_media_options=social_media_options,
        headless=bool(headless),
        double_check=bool(double_check),
        email=email or None,
        locations=locations,
    )

    with jobs_lock:
        jobs[job_id] = job

    thread = threading.Thread(target=scrape_worker, args=(job,), daemon=True)
    job.thread = thread
    thread.start()

    # Determine which columns to show based on mode
    columns = get_columns_for_mode(mode, social_media_options)

    return jsonify({
        "success": True,
        "job_id": job_id,
        "status": "running",
        "total": total,
        "mode": mode,
        "multi_location": is_multi,
        "locations": locations if is_multi else None,
        "columns": columns,
    })


@app.route("/scrape/status/<job_id>", methods=["GET"])
def scrape_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)

    if not job:
        return jsonify({"error": "Job not found"}), 404

    with jobs_lock:
        # Determine which columns to show based on the job's mode
        columns = get_columns_for_mode(job.mode, job.social_media_options)

        # Build location progress info for multi-scraping
        location_info = None
        if job.locations and len(job.locations) > 1:
            current_loc = ""
            if job.current_location_index < len(job.locations):
                current_loc = job.locations[job.current_location_index]
            location_info = {
                "locations": job.locations,
                "total_locations": len(job.locations),
                "current_index": job.current_location_index,
                "current_location": current_loc,
            }

        return jsonify({
            "job_id": job.job_id,
            "status": job.status,
            "keyword": job.keyword,
            "location": job.location,
            "total": job.total,
            "mode": job.mode,
            "columns": columns,
            "scraped_so_far": job.scraped_so_far,
            "results": job.results,
            "error": job.error,
            "multi_location": len(job.locations) > 1 if job.locations else False,
            "location_info": location_info,
        })


@app.route("/scrape/cancel/<job_id>", methods=["POST"])
def cancel_scrape(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)

    if not job:
        return jsonify({"error": "Job not found"}), 404

    with jobs_lock:
        if job.status in ("completed", "cancelled", "error"):
            return jsonify({"error": f"Job already in '{job.status}' state"}), 400

        job.abort_event.set()

    return jsonify({"success": True, "job_id": job_id, "status": "cancelling"})


@app.route("/scrape/jobs", methods=["GET"])
def list_jobs():
    """Return a list of recent job IDs and their statuses."""
    with jobs_lock:
        job_list = [
            {
                "job_id": j.job_id,
                "keyword": j.keyword,
                "location": j.location,
                "status": j.status,
                "mode": j.mode,
                "total": j.total,
                "scraped_so_far": j.scraped_so_far,
                "created_at": j.created_at.isoformat(),
            }
            for j in sorted(jobs.values(), key=lambda x: x.created_at, reverse=True)
        ]
    return jsonify({"jobs": job_list})


@app.route("/saved-data/search", methods=["GET"])
def saved_data_search():
    keyword = request.args.get("keyword", "").strip()
    location = request.args.get("location", "").strip()

    if not keyword or not location:
        return jsonify({"error": "Both keyword and location are required to search saved data"}), 400

    # Pagination params
    try:
        page = int(request.args.get("page", 1))
    except (ValueError, TypeError):
        page = 1
    try:
        limit = int(request.args.get("limit", 20))
    except (ValueError, TypeError):
        limit = 20

    success, results, error, total = search_saved_places(keyword, location, page, limit)

    if not success:
        return jsonify({"error": "Database query failed", "details": error}), 500

    total_pages = max(1, (total + limit - 1) // limit) if total > 0 else 1

    return jsonify({
        "success": True,
        "count": len(results),
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "results": results
    })


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    with jobs_lock:
        active = sum(1 for j in jobs.values() if j.status == "running")
    return jsonify({
        "status": "healthy",
        "active_jobs": active,
        "total_jobs": len(jobs),
    })


# ─── Error Handlers ────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    print("=" * 55)
    print("  >>  Zaucto Scraper  v2.0")
    print("  >>  http://127.0.0.1:5050")
    print("=" * 55)
    app.run(debug=False, host="127.0.0.1", port=5050)
