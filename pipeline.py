"""
pipeline.py
Full scrape -> enrich -> filter -> push pipeline.
Triggered when a LinkedIn post URL is detected in #linkedin-scraper.
"""

import csv
import os
import time
from datetime import datetime
from typing import Optional

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

# Prospeo
PROSPEO_BASE = "https://api.prospeo.io"
PROSPEO_DELAY = 0.5           # seconds between calls (rate limit: 30/sec)

# Instantly v2
INSTANTLY_BASE = "https://api.instantly.ai/api/v2"
INSTANTLY_DELAY = 1           # seconds between calls

# PhantomBuster scrape cap
PB_MAX_PROFILES = 500


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
# Step 3 — Prospeo enrichment (LinkedIn URL first, name+company fallback)
# ---------------------------------------------------------------------------

def _prospeo_enrich(linkedin_url: str) -> Optional[dict]:
    """
    Enrich a LinkedIn profile URL via Prospeo's v2 enrich-person API.
    Returns a dict with first_name, last_name, email, company, title or None.
    """
    api_key = os.environ["PROSPEO_API_KEY"]
    headers = {"Content-Type": "application/json", "X-KEY": api_key}

    try:
        resp = requests.post(
            f"{PROSPEO_BASE}/enrich-person",
            headers=headers,
            json={
                "only_verified_email": True,
                "data": {"linkedin_url": linkedin_url},
            },
            timeout=30,
        )
        if not resp.ok:
            _log(f"Prospeo HTTP {resp.status_code} for {linkedin_url}")
            return None

        body = resp.json()
        if body.get("error"):
            return None

        person = body.get("person", {})
        company_obj = body.get("company", {}) or {}

        # Extract email
        email_obj = person.get("email", {}) or {}
        email_addr = email_obj.get("email", "") if isinstance(email_obj, dict) else ""

        if not email_addr:
            return None

        first = person.get("first_name", "")
        last = person.get("last_name", "")
        title = person.get("current_job_title", "")
        company = company_obj.get("name", "")

        return {
            "first_name": first,
            "last_name": last,
            "email": email_addr,
            "company": company,
            "title": title,
        }

    except requests.RequestException as exc:
        _log(f"Prospeo error for {linkedin_url}: {exc}")

    return None


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

    # ---- Step 3: Prospeo enrichment ----
    enriched_leads = []
    skipped_no_email = 0
    log_rows = []

    for i, url in enumerate(profile_urls):
        _log(f"Enriching {i+1}/{total_scraped}: {url}")
        try:
            result = _prospeo_enrich(url)
            if result:
                result["linkedin_url"] = url
                enriched_leads.append(result)
                log_rows.append({
                    "linkedin_url": url,
                    "first_name": result["first_name"],
                    "last_name": result["last_name"],
                    "email": result["email"],
                    "company": result["company"],
                    "status": "enriched",
                })
            else:
                skipped_no_email += 1
                log_rows.append({
                    "linkedin_url": url,
                    "first_name": "", "last_name": "", "email": "", "company": "",
                    "status": "no_verified_email",
                })
        except Exception as exc:
            _log(f"Prospeo exception for {url}: {exc}")
            skipped_no_email += 1
            log_rows.append({
                "linkedin_url": url,
                "first_name": "", "last_name": "", "email": "", "company": "",
                "status": f"error: {exc}",
            })

        if i < total_scraped - 1:
            time.sleep(PROSPEO_DELAY)

    # Write enrichment log
    try:
        _write_enrichment_log(log_rows)
    except Exception as exc:
        _log(f"Failed to write enrichment log: {exc}")

    total_enriched = len(enriched_leads)
    _log(f"Enriched {total_enriched} leads, skipped {skipped_no_email}")

    # ---- Step 4: Title filter ----
    try:
        kept_leads, dropped_count = filter_leads(enriched_leads)
    except Exception as exc:
        _send_error("TITLE FILTER", str(exc), post_url)
        return

    _log(f"Title filter: {len(kept_leads)} kept, {dropped_count} dropped")

    # ---- Step 5: Instantly push ----
    added_count = 0
    duplicates_skipped = 0
    errors_count = 0

    for i, lead in enumerate(kept_leads):
        _log(f"Pushing to Instantly {i+1}/{len(kept_leads)}: {lead['email']}")
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

        if i < len(kept_leads) - 1:
            time.sleep(INSTANTLY_DELAY)

    # ---- Step 6: Slack summary ----
    elapsed = time.time() - start
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)
    enriched_pct = round((total_enriched / total_scraped) * 100) if total_scraped else 0

    summary = (
        f"\u2705 Pipeline complete for:\n{post_url}\n\n"
        f"\U0001f465 Engagers scraped: {total_scraped}\n"
        f"\U0001f4e7 Emails enriched by Prospeo: {total_enriched} ({enriched_pct}%)\n"
        f"\U0001f3af Passed title filter: {len(kept_leads)}\n"
        f"\U0001f6ab Filtered out by title: {dropped_count}\n"
        f"\u23ed\ufe0f Skipped (no email found): {skipped_no_email}\n"
        f"\u2795 Added to Instantly campaign: {added_count}\n"
        f"\U0001f501 Duplicates skipped: {duplicates_skipped}\n"
        f"\u23f1 Total time: {mins} mins {secs} secs"
    )

    _log(summary)
    _send_slack_message(summary)
