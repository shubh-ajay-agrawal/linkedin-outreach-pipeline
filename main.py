"""
main.py
Flask app that listens for Slack events and triggers the LinkedIn outreach pipeline.
"""

import hashlib
import hmac
import os
import re
import threading
import time

from flask import Flask, jsonify, request
from dotenv import load_dotenv

from pipeline import run_pipeline

load_dotenv()

app = Flask(__name__)

# Regex to match LinkedIn post URLs
LINKEDIN_POST_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/(?:posts/|feed/update/)\S+"
)


def _verify_slack_signature(req) -> bool:
    """Verify that the incoming request is genuinely from Slack."""
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    timestamp = req.headers.get("X-Slack-Request-Timestamp", "")
    signature = req.headers.get("X-Slack-Signature", "")

    if not timestamp or not signature:
        return False

    # Reject requests older than 5 minutes to prevent replay attacks
    if abs(time.time() - int(timestamp)) > 300:
        return False

    body = req.get_data(as_text=True)
    base_string = f"v0:{timestamp}:{body}"
    computed = "v0=" + hmac.new(
        signing_secret.encode(), base_string.encode(), hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed, signature)


@app.route("/slack/events", methods=["POST"])
def slack_events():
    """Handle incoming Slack event subscriptions."""

    # --- Slack URL verification challenge ---
    data = request.json
    if data and data.get("type") == "url_verification":
        return jsonify({"challenge": data["challenge"]})

    # --- Verify request signature ---
    if not _verify_slack_signature(request):
        return "Invalid signature", 403

    # --- Ignore retries (Slack sends X-Slack-Retry-Num on retries) ---
    if request.headers.get("X-Slack-Retry-Num"):
        return jsonify({"ok": True}), 200

    # --- Process event ---
    event = (data or {}).get("event", {})

    # Only handle message events (ignore subtypes like bot_message, message_changed, etc.)
    if event.get("type") != "message":
        return jsonify({"ok": True}), 200

    # Ignore bot messages to prevent loops
    if event.get("bot_id") or event.get("subtype"):
        return jsonify({"ok": True}), 200

    text = event.get("text", "")
    match = LINKEDIN_POST_RE.search(text)

    if match:
        post_url = match.group(0)
        # Strip trailing angle bracket if Slack auto-wrapped the URL
        post_url = post_url.rstrip(">")
        # Run pipeline in background thread so we respond to Slack within 3 seconds
        thread = threading.Thread(target=run_pipeline, args=(post_url,), daemon=True)
        thread.start()

    return jsonify({"ok": True}), 200


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint for Railway."""
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
