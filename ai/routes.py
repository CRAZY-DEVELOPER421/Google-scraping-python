"""
Flask Blueprint for AI Search panel.
Routes: /api/ai-search/start, /chat, /usage, /status/<job_id>
"""
import uuid
import logging
from flask import Blueprint, request, jsonify
from ai.service import run_ai_search, handle_chat_query, get_stream_status
from ai.usage_tracker import get_usage

ai_bp = Blueprint('ai_search', __name__, url_prefix='/api/ai-search')


@ai_bp.route('/start', methods=['POST'])
def start_ai_search():
    """Start AI business search. Returns results + usage."""
    data = request.get_json() or {}
    keyword = (data.get("keyword") or "").strip()
    location = (data.get("location") or "").strip()
    result_count = int(data.get("results", 10))
    mode = (data.get("mode") or "fast").strip().lower()

    if not keyword or not location:
        return jsonify({"error": "Keyword and location required"}), 400

    result_count = max(1, min(result_count, 30))  # cap at 30
    query = f"{keyword} in {location}"
    
    logging.info(f"AI Search: '{query}' (mode={mode})")
    result = run_ai_search(query, mode, result_count, keyword, location)
    
    if "error" in result:
        return jsonify(result), 429
        
    return jsonify({
        "search_id": uuid.uuid4().hex[:12],
        "results": result.get("results", []),
        "usage": result.get("usage", get_usage()),
        "mode": mode,
    })


@ai_bp.route('/chat', methods=['POST'])
def ai_chat():
    """Chat endpoint for AI Search Panel."""
    data = request.get_json() or {}
    user_query = (data.get("query") or "").strip()
    mode = (data.get("mode") or "fast").strip().lower()
    result_count = int(data.get("results", 10))

    if not user_query:
        return jsonify({"error": "Empty query"}), 400

    result_count = max(1, min(result_count, 30))
    result = handle_chat_query(user_query, mode, result_count)
    return jsonify(result)


@ai_bp.route('/usage', methods=['GET'])
def check_usage():
    """Return API usage stats."""
    return jsonify(get_usage())


@ai_bp.route('/status/<job_id>', methods=['GET'])
def stream_status(job_id: str):
    """Get status of a streaming search job."""
    status = get_stream_status(job_id)
    return jsonify(status)
