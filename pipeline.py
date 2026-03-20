"""
pipeline.py
Full scrape -> enrich -> filter -> push pipeline.
Triggered when a LinkedIn post URL is detected in #linkedin-scraper.
"""

import csv
import os
import threading
import time
from datetime import datetime

import requests

from title_filter import filter_leads

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PHANTOM_LIKERS_ID = "7700895230156471"
PHANTOM_COMMENTERS_ID = "6672845611180416"
INSTANTLY_CAMPAIGN_ID = "75654875-36a1-4565-a47a-fcff4426a442"
ENRICHMENT_LOG = "enrichment_log.csv"

# PhantomBuster
PB_BASE = "https://api.phantombuster.com/api/v2"
PB_POLL_INTERVAL = 30         # seconds between status checks (shorter — simple phantoms are faster)
PB_MAX_POLL_TIME = 30 * 60    # 30 minutes

# Ark AI
ARK_BASE = "https://api.ai-ark.com/api/developer-portal/v1"
ARK_WEBHOOK_TIMEOUT = 15 * 60   # 15 minutes max wait for webhook
ARK_POLL_INTERVAL = 30           # seconds between progress log checks

# Instantly v2
INSTANTLY_BASE = "https://api.instantly.ai/api/v2"
INSTANTLY_DELAY = 1           # seconds between calls

# PhantomBuster scrape cap
PB_MAX_PROFILES = 500

# ---------------------------------------------------------------------------
# Ark AI webhook bridge (shared between pipeline thread and Flask)
# ---------------------------------------------------------------------------
_ark_results = {}    # trackId -> webhook payload data
_ark_events = {}     # trackId -> threading.Event
_ark_lock = threading.Lock()


def _log(msg: str):
    """Print a timestamped log line for Railway / console."""
    print(f"[{datetime.utcnow().isoformat()}] {msg}", flush=True)


def _send_slack_message(text: str):
    """Post a message to #linkedin-scraper via Slack API."""
    token = os.environ["SLACK_BOT_TOKEN"]
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": "#linkedin-scraper", "text": text},
        timeout=10,
    )
    if not resp.ok or not resp.json().get("ok"):
        _log(f"Slack message failed: {resp.text}")


def _send_error(step: str, error: str, post_url: str):
    """Send a formatted error message to Slack and log it."""
    msg = (
        f"\u274c Pipeline failed at {step}\n"
        f"Error: {error}\n"
        f"Post: {post_url}"
    )
    _log(msg)
    _send_slack_message(msg)


# ---------------------------------------------------------------------------
# Step 2 — PhantomBuster: launch BOTH phantoms, poll, fetch & merge results
# ---------------------------------------------------------------------------

def _phantombuster_launch_one(phantom_id: str, label: str, post_url: str) -> str:
    """Launch a single phantom with the given post URL. Returns container ID."""
    import json as _json
    api_key = os.environ["PHANTOMBUSTER_API_KEY"]
    headers = {"X-Phantombuster-Key": api_key, "Content-Type": "application/json"}

    # Fetch current saved argument (to keep sessionCookie + userAgent)
    fetch_resp = requests.get(
        f"{PB_BASE}/agents/fetch",
        headers={"X-Phantombuster-Key": api_key},
        params={"id": phantom_id},
        timeout=30,
    )
    fetch_resp.raise_for_status()
    saved_arg = fetch_resp.json().get("argument", {})
    if isinstance(saved_arg, str):
        saved_arg = _json.loads(saved_arg)

    # Build the launch argument — keep session cookie, set the post URL
    launch_arg = {
        "postUrl": post_url,
        "sessionCookie": saved_arg.get("sessionCookie", ""),
        "userAgent": saved_arg.get("userAgent", ""),
        "numberOfPostsPerLaunch": 1,
        "csvName": "result",
        "watcherMode": False,
        "excludeOwnProfileFromResult": True,
    }

    _log(f"Launching {label} phantom ({phantom_id}) for {post_url}")

    resp = requests.post(
        f"{PB_BASE}/agents/launch",
        headers=headers,
        json={
            "id": phantom_id,
            "argument": launch_arg,
            "saveArgument": False,
        },
        timeout=30,
    )
    resp.raise_for_status()
    container_id = resp.json().get("containerId")
    _log(f"{label} phantom launched — container {container_id}")
    return container_id


def _phantombuster_launch(post_url: str) -> dict:
    """Launch both likers and commenters phantoms. Returns dict of container IDs."""
    likers_container = _phantombuster_launch_one(
        PHANTOM_LIKERS_ID, "Likers", post_url
    )
    commenters_container = _phantombuster_launch_one(
        PHANTOM_COMMENTERS_ID, "Commenters", post_url
    )
    return {
        "likers": {"phantom_id": PHANTOM_LIKERS_ID, "container_id": likers_container},
        "commenters": {"phantom_id": PHANTOM_COMMENTERS_ID, "container_id": commenters_container},
    }


def _phantombuster_poll_one(phantom_id: str, container_id: str, label: str) -> dict:
    """Poll a single phantom until it finishes. Returns the output data."""
    api_key = os.environ["PHANTOMBUSTER_API_KEY"]
    elapsed = 0

    while elapsed < PB_MAX_POLL_TIME:
        time.sleep(PB_POLL_INTERVAL)
        elapsed += PB_POLL_INTERVAL

        resp = requests.get(
            f"{PB_BASE}/agents/fetch-output",
            headers={"X-Phantombuster-Key": api_key},
            params={"id": phantom_id},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        response_container = data.get("containerId")
        status = data.get("status")
        _log(f"{label} status: {status}, container: {response_container} (elapsed {elapsed}s)")

        if response_container != container_id:
            _log(f"Waiting — {label} output is from old run, not ours")
            continue

        if status == "finished":
            return data
        if status in ("error", "stopped"):
            raise RuntimeError(f"{label} phantom ended with status: {status}")

    raise TimeoutError(f"{label} phantom did not finish within 30 minutes")


def _phantombuster_poll(containers: dict) -> dict:
    """Poll both phantoms until both finish. Returns dict with both outputs."""
    results = {}
    for label, info in containers.items():
        data = _phantombuster_poll_one(
            info["phantom_id"], info["container_id"], label.capitalize()
        )
        results[label] = data
    return results


def _phantombuster_parse_results(all_data: dict) -> list[str]:
    """Extract and deduplicate LinkedIn profile URLs from both phantom outputs."""
    import io
    import re

    all_urls = []

    for label, data in all_data.items():
        output_text = data.get("output", "")
        csv_match = re.search(
            r'(https://phantombuster\.s3\.amazonaws\.com/[^\s]+\.csv)', output_text
        )
        if csv_match:
            csv_url = csv_match.group(1)
            _log(f"Fetching {label} results from CSV: {csv_url}")
            resp = requests.get(csv_url, timeout=60)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            count = 0
            for row in reader:
                url = (row.get("profileLink") or row.get("profileUrl") or "")
                if url and "linkedin.com" in url:
                    all_urls.append(url)
                    count += 1
            _log(f"{label}: {count} profiles found in CSV")

    # Deduplicate while preserving order
    seen = set()
    unique_urls = []
    for url in all_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)

    _log(f"Total unique profiles after dedup: {len(unique_urls)} (from {len(all_urls)} total)")
    return unique_urls


# ---------------------------------------------------------------------------
# Step 3 — Ark AI batch enrichment (LinkedIn URLs -> emails via webhook)
# ---------------------------------------------------------------------------

def _ark_enrich_batch(linkedin_urls: list[str], webhook_base_url: str) -> list[dict]:
    """
    Send LinkedIn URLs to Ark AI in batches of 300 (API limit).
    Blocks until all webhook results arrive (or timeout).
    Returns list of dicts: {first_name, last_name, email, company, title, linkedin_url}
    """
    api_key = os.environ["ARK_AI_API_KEY"]
    headers = {"X-TOKEN": api_key, "Content-Type": "application/json"}
    webhook_url = f"{webhook_base_url}/webhook/ark"

    # Split into batches of 300 (Ark AI limit per request)
    batch_size = 300
    batches = [linkedin_urls[i:i + batch_size] for i in range(0, len(linkedin_urls), batch_size)]
    _log(f"Sending {len(linkedin_urls)} LinkedIn URLs to Ark AI in {len(batches)} batch(es) of up to {batch_size}...")
    _log(f"Webhook URL: {webhook_url}")

    # Launch all batches and collect their trackIds + events
    track_ids = []
    events = []
    for batch_num, batch_urls in enumerate(batches, 1):
        _log(f"Launching batch {batch_num}/{len(batches)} ({len(batch_urls)} URLs)...")

        payload = {
            "contact": {
                "linkedin": {
                    "any": {
                        "include": batch_urls,
                    }
                }
            },
            "page": 0,
            "size": len(batch_urls),
            "webhook": webhook_url,
        }

        resp = requests.post(
            f"{ARK_BASE}/people/export",
            headers=headers,
            json=payload,
            timeout=60,
        )
        if not resp.ok:
            _log(f"Ark AI export error — HTTP {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        body = resp.json()

        track_id = body.get("trackId")
        if not track_id:
            raise RuntimeError(f"Ark AI did not return a trackId for batch {batch_num}. Response: {body}")

        _log(f"Batch {batch_num} started — trackId: {track_id}, stats: {body.get('statistics', {})}")

        # Create an Event so the webhook handler can wake us up
        event = threading.Event()
        with _ark_lock:
            _ark_events[track_id] = event
            # Check if webhook already arrived before we registered (race condition fix)
            if _ark_results.get(track_id) is not None:
                event.set()  # Webhook beat us — data already buffered
                _log(f"Batch {batch_num} webhook already arrived before registration!")
            else:
                _ark_results[track_id] = None

        track_ids.append(track_id)
        events.append(event)

        # Small delay between batch requests to be polite to the API
        if batch_num < len(batches):
            time.sleep(1)

    # Wait for ALL webhooks to arrive
    all_enriched = []
    for batch_num, (track_id, event) in enumerate(zip(track_ids, events), 1):
        _log(f"Waiting for batch {batch_num}/{len(batches)} (trackId: {track_id})...")

        elapsed = 0
        while elapsed < ARK_WEBHOOK_TIMEOUT:
            if event.wait(timeout=ARK_POLL_INTERVAL):
                break
            elapsed += ARK_POLL_INTERVAL

            # Poll statistics endpoint for progress
            try:
                stats_resp = requests.get(
                    f"{ARK_BASE}/people/statistics/{track_id}",
                    headers=headers,
                    timeout=15,
                )
                if stats_resp.ok:
                    stats = stats_resp.json()
                    s = stats.get("statistics", {})
                    state = stats.get("state", "UNKNOWN")
                    _log(
                        f"Batch {batch_num} progress — state: {state}, "
                        f"total: {s.get('total', '?')}, "
                        f"found: {s.get('found', '?')}, "
                        f"success: {s.get('success', '?')}, "
                        f"failed: {s.get('failed', '?')} "
                        f"(elapsed {elapsed}s)"
                    )
            except Exception as exc:
                _log(f"Statistics poll error (non-fatal): {exc}")

        # Check if webhook arrived
        with _ark_lock:
            webhook_data = _ark_results.get(track_id)

        # If webhook didn't arrive, try resending it
        if webhook_data is None:
            _log(f"Batch {batch_num} webhook not received — requesting resend...")
            try:
                resend_resp = requests.patch(
                    f"{ARK_BASE}/people/notify",
                    headers=headers,
                    json={"trackId": track_id, "webhook": webhook_url},
                    timeout=30,
                )
                _log(f"Resend response: HTTP {resend_resp.status_code} — {resend_resp.text}")
            except Exception as exc:
                _log(f"Resend request failed: {exc}")

            # Wait up to 3 more minutes for the resent webhook
            _log(f"Waiting up to 3 more minutes for resent webhook...")
            resend_wait = 0
            while resend_wait < 180:
                if event.wait(timeout=ARK_POLL_INTERVAL):
                    break
                resend_wait += ARK_POLL_INTERVAL

        # Retrieve results for this batch
        with _ark_lock:
            webhook_data = _ark_results.pop(track_id, None)
            _ark_events.pop(track_id, None)

        if webhook_data is None:
            raise TimeoutError(
                f"Ark AI webhook not received for batch {batch_num} (trackId {track_id}) "
                f"even after resend request"
            )

        batch_leads = _parse_ark_results(webhook_data)
        _log(f"Batch {batch_num} returned {len(batch_leads)} enriched leads")
        all_enriched.extend(batch_leads)

    _log(f"All {len(batches)} batch(es) complete — {len(all_enriched)} total enriched leads")
    return all_enriched


def _parse_ark_results(webhook_data: dict) -> list[dict]:
    """
    Parse the Ark AI webhook payload into our standard lead format.
    Only includes people with a verified email (found=True, status=VALID).
    """
    people = webhook_data.get("data", [])
    stats = webhook_data.get("statistics", {})
    _log(
        f"Parsing Ark AI results — {len(people)} people, "
        f"stats: total={stats.get('total', '?')}, found={stats.get('found', '?')}"
    )

    enriched = []
    for person in people:
        # Find a valid, verified email
        email_obj = person.get("email", {}) or {}
        outputs = email_obj.get("output", []) or []

        email_addr = ""
        for entry in outputs:
            if entry.get("found") and entry.get("status") == "VALID":
                email_addr = entry.get("address", "")
                break

        if not email_addr:
            continue

        # Extract person details
        summary = person.get("summary", {}) or {}
        company_obj = person.get("company", {}) or {}
        company_summary = company_obj.get("summary", {}) or {}
        link_obj = person.get("link", {}) or {}

        first_name = summary.get("first_name", "")
        last_name = summary.get("last_name", "")
        title = summary.get("title", "") or summary.get("headline", "")
        company_name = company_summary.get("name", "")

        # LinkedIn URL: prefer link.linkedin, fall back to identifier
        linkedin_url = link_obj.get("linkedin", "") or person.get("identifier", "")

        enriched.append({
            "first_name": first_name,
            "last_name": last_name,
            "email": email_addr,
            "company": company_name,
            "title": title,
            "linkedin_url": linkedin_url,
        })

    _log(f"Ark AI enrichment: {len(enriched)} leads with verified emails out of {len(people)} people")
    return enriched


def _write_enrichment_log(rows: list[dict]):
    """Append enrichment results to enrichment_log.csv."""
    file_exists = os.path.isfile(ENRICHMENT_LOG)
    with open(ENRICHMENT_LOG, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "linkedin_url", "first_name", "last_name", "email", "company", "status",
        ])
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Step 4B — Bouncify email validation (optional)
# ---------------------------------------------------------------------------

BOUNCIFY_DELAY = 0.5  # seconds between calls (120 req/min limit)


def _bouncify_verify_email(email: str) -> bool:
    """Verify a single email via Bouncify. Returns True if deliverable."""
    api_key = os.environ.get("BOUNCIFY_API_KEY", "")
    if not api_key:
        return True  # No key configured — skip validation

    try:
        resp = requests.get(
            "https://api.bouncify.io/v1/verify",
            params={"apikey": api_key, "email": email},
            timeout=30,
        )
        if not resp.ok:
            _log(f"Bouncify error for {email}: HTTP {resp.status_code} — keeping lead")
            return True  # On error, keep the lead

        result = resp.json().get("result", "")
        # Accept "deliverable" emails; reject "undeliverable" and "risky"
        return result == "deliverable"

    except Exception as exc:
        _log(f"Bouncify exception for {email}: {exc} — keeping lead")
        return True  # On error, keep the lead


def _bouncify_verify_batch(leads: list[dict]) -> tuple[list[dict], int]:
    """
    Validate all leads through Bouncify.
    Returns (valid_leads, rejected_count).
    If BOUNCIFY_API_KEY is not set, passes all leads through.
    """
    api_key = os.environ.get("BOUNCIFY_API_KEY", "")
    if not api_key:
        _log("BOUNCIFY_API_KEY not set — skipping email validation")
        return leads, 0

    _log(f"Validating {len(leads)} emails through Bouncify...")
    valid = []
    rejected = 0

    for i, lead in enumerate(leads):
        email = lead["email"]
        _log(f"Bouncify {i+1}/{len(leads)}: {email}")

        if _bouncify_verify_email(email):
            valid.append(lead)
        else:
            _log(f"Bouncify rejected: {email}")
            rejected += 1

        if i < len(leads) - 1:
            time.sleep(BOUNCIFY_DELAY)

    _log(f"Bouncify validation: {len(valid)} passed, {rejected} rejected")
    return valid, rejected


# ---------------------------------------------------------------------------
# Step 5 — Instantly v2 push
# ---------------------------------------------------------------------------

def _instantly_add_lead(lead: dict, source_post_url: str) -> str:
    """
    Add a single lead to the Instantly campaign via the v2 API.
    Returns 'added', 'duplicate', or 'error'.
    """
    api_key = os.environ["INSTANTLY_API_KEY"]

    payload = {
        "campaign": INSTANTLY_CAMPAIGN_ID,
        "email": lead["email"],
        "first_name": lead.get("first_name", ""),
        "last_name": lead.get("last_name", ""),
        "company_name": lead.get("company", ""),
        "custom_variables": {
            "linkedin_url": lead.get("linkedin_url", ""),
            "source_post_url": source_post_url,
        },
    }

    try:
        resp = requests.post(
            f"{INSTANTLY_BASE}/leads",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        if resp.ok:
            return "added"

        # Instantly returns 409 or an error body for duplicates
        body = resp.text.lower()
        if resp.status_code == 409 or "duplicate" in body or "already exists" in body:
            return "duplicate"

        _log(f"Instantly error ({resp.status_code}) for {lead['email']}: {resp.text}")
        return "error"

    except requests.RequestException as exc:
        _log(f"Instantly request failed for {lead['email']}: {exc}")
        return "error"


# ---------------------------------------------------------------------------
# Main pipeline orchestrator
# ---------------------------------------------------------------------------

def run_pipeline(post_url: str):
    """Execute the full pipeline for a given LinkedIn post URL."""
    start = time.time()
    _log(f"Pipeline started for {post_url}")
    _send_slack_message(
        f"\U0001f4e1 Got it! Starting the pipeline for:\n{post_url}\n\n"
        f"PhantomBuster is scraping engagers now — this usually takes 5-15 minutes. "
        f"I'll send you a full summary when it's done."
    )

    # ---- Step 2: PhantomBuster (likers + commenters in parallel) ----
    try:
        containers = _phantombuster_launch(post_url)
    except Exception as exc:
        _send_error("PHANTOMBUSTER LAUNCH", str(exc), post_url)
        return

    try:
        pb_data = _phantombuster_poll(containers)
    except Exception as exc:
        _send_error("PHANTOMBUSTER POLL", str(exc), post_url)
        return

    try:
        profile_urls = _phantombuster_parse_results(pb_data)
    except Exception as exc:
        _send_error("PHANTOMBUSTER PARSE", str(exc), post_url)
        return

    total_scraped = len(profile_urls)
    _log(f"PhantomBuster returned {total_scraped} profiles")

    if total_scraped == 0:
        _send_error("PHANTOMBUSTER PARSE", "No profiles found in output", post_url)
        return

    # ---- Step 3: Ark AI batch enrichment ----
    webhook_base_url = os.environ.get("BASE_URL", "https://web-production-e430.up.railway.app")
    try:
        enriched_leads = _ark_enrich_batch(profile_urls, webhook_base_url)
    except Exception as exc:
        _send_error("ARK AI ENRICHMENT", str(exc), post_url)
        return

    total_enriched = len(enriched_leads)
    skipped_no_email = total_scraped - total_enriched
    _log(f"Enriched {total_enriched} leads, skipped {skipped_no_email}")

    # Build enrichment log from batch results
    log_rows = []
    enriched_urls = {lead["linkedin_url"] for lead in enriched_leads}
    for lead in enriched_leads:
        log_rows.append({
            "linkedin_url": lead["linkedin_url"],
            "first_name": lead["first_name"],
            "last_name": lead["last_name"],
            "email": lead["email"],
            "company": lead["company"],
            "status": "enriched",
        })
    for url in profile_urls:
        if url not in enriched_urls:
            log_rows.append({
                "linkedin_url": url,
                "first_name": "", "last_name": "", "email": "", "company": "",
                "status": "no_verified_email",
            })

    # Write enrichment log
    try:
        _write_enrichment_log(log_rows)
    except Exception as exc:
        _log(f"Failed to write enrichment log: {exc}")

    # ---- Step 4: Title filter ----
    try:
        kept_leads, dropped_count = filter_leads(enriched_leads)
    except Exception as exc:
        _send_error("TITLE FILTER", str(exc), post_url)
        return

    _log(f"Title filter: {len(kept_leads)} kept, {dropped_count} dropped")

    # ---- Step 4B: Bouncify email validation ----
    try:
        verified_leads, bouncify_rejected = _bouncify_verify_batch(kept_leads)
    except Exception as exc:
        _send_error("BOUNCIFY VALIDATION", str(exc), post_url)
        return

    _log(f"Bouncify: {len(verified_leads)} verified, {bouncify_rejected} rejected")

    # ---- Step 5: Instantly push ----
    added_count = 0
    duplicates_skipped = 0
    errors_count = 0

    for i, lead in enumerate(verified_leads):
        _log(f"Pushing to Instantly {i+1}/{len(verified_leads)}: {lead['email']}")
        try:
            result = _instantly_add_lead(lead, post_url)
            if result == "added":
                added_count += 1
            elif result == "duplicate":
                duplicates_skipped += 1
            else:
                errors_count += 1
        except Exception as exc:
            _log(f"Instantly exception for {lead['email']}: {exc}")
            errors_count += 1

        if i < len(verified_leads) - 1:
            time.sleep(INSTANTLY_DELAY)

    # ---- Step 6: Slack summary ----
    elapsed = time.time() - start
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)
    enriched_pct = round((total_enriched / total_scraped) * 100) if total_scraped else 0

    bouncify_line = ""
    if os.environ.get("BOUNCIFY_API_KEY"):
        bouncify_line = f"\U0001f50d Bouncify rejected: {bouncify_rejected}\n"

    summary = (
        f"\u2705 Pipeline complete for:\n{post_url}\n\n"
        f"\U0001f465 Engagers scraped: {total_scraped}\n"
        f"\U0001f4e7 Emails enriched by Ark AI: {total_enriched} ({enriched_pct}%)\n"
        f"\U0001f3af Passed title filter: {len(kept_leads)}\n"
        f"\U0001f6ab Filtered out by title: {dropped_count}\n"
        f"{bouncify_line}"
        f"\u23ed\ufe0f Skipped (no email found): {skipped_no_email}\n"
        f"\u2795 Added to Instantly campaign: {added_count}\n"
        f"\U0001f501 Duplicates skipped: {duplicates_skipped}\n"
        f"\u23f1 Total time: {mins} mins {secs} secs"
    )

    _log(summary)
    _send_slack_message(summary)
