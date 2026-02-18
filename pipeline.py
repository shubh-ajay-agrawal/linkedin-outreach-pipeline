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
PHANTOM_ID = "5647257991330907"
INSTANTLY_CAMPAIGN_ID = "75654875-36a1-4565-a47a-fcff4426a442"
ENRICHMENT_LOG = "enrichment_log.csv"

# PhantomBuster
PB_BASE = "https://api.phantombuster.com/api/v2"
PB_POLL_INTERVAL = 120        # seconds between status checks
PB_MAX_POLL_TIME = 30 * 60    # 30 minutes

# Prospeo
PROSPEO_BASE = "https://api.prospeo.io"
PROSPEO_DELAY = 2             # seconds between calls

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
# Step 2 — PhantomBuster: launch, poll, fetch results
# ---------------------------------------------------------------------------

def _phantombuster_launch(post_url: str) -> str:
    """Launch the phantom and return the container ID."""
    api_key = os.environ["PHANTOMBUSTER_API_KEY"]
    headers = {"X-Phantombuster-Key": api_key, "Content-Type": "application/json"}

    # Step A: Fetch the phantom's current saved arguments (sessionCookie, etc.)
    fetch_resp = requests.get(
        f"{PB_BASE}/agents/fetch",
        headers={"X-Phantombuster-Key": api_key},
        params={"id": PHANTOM_ID},
        timeout=30,
    )
    fetch_resp.raise_for_status()
    saved_argument = fetch_resp.json().get("argument", {})
    if isinstance(saved_argument, str):
        import json as _json
        saved_argument = _json.loads(saved_argument)

    # Step B: Merge in our overrides (post URL + engager types)
    saved_argument["linkedinPostUrl"] = post_url
    saved_argument["postEngagersToExtract"] = ["likers", "commenters"]

    # Step C: Save the merged config back
    save_resp = requests.post(
        f"{PB_BASE}/agents/save",
        headers=headers,
        json={
            "id": PHANTOM_ID,
            "argument": saved_argument,
        },
        timeout=30,
    )
    save_resp.raise_for_status()
    _log(f"PhantomBuster config updated with post URL")

    # Step D: Launch the phantom (uses saved config)
    resp = requests.post(
        f"{PB_BASE}/agents/launch",
        headers=headers,
        json={"id": PHANTOM_ID},
        timeout=30,
    )
    resp.raise_for_status()
    container_id = resp.json().get("containerId")
    _log(f"PhantomBuster launched — container {container_id}")
    return container_id


def _phantombuster_poll(container_id: str) -> dict:
    """Poll until the phantom finishes or we time out. Returns the agent object."""
    api_key = os.environ["PHANTOMBUSTER_API_KEY"]
    elapsed = 0

    while elapsed < PB_MAX_POLL_TIME:
        time.sleep(PB_POLL_INTERVAL)
        elapsed += PB_POLL_INTERVAL

        resp = requests.get(
            f"{PB_BASE}/agents/fetch-output",
            headers={"X-Phantombuster-Key": api_key},
            params={"id": PHANTOM_ID},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        response_container = data.get("containerId")
        status = data.get("status")
        _log(f"PhantomBuster status: {status}, container: {response_container} (elapsed {elapsed}s)")

        # Ignore results from a previous run — keep waiting for OUR run
        if response_container != container_id:
            _log(f"Waiting — output is from old run ({response_container}), not ours ({container_id})")
            continue

        if status == "finished":
            return data
        if status in ("error", "stopped"):
            raise RuntimeError(f"Phantom ended with status: {status}")

    raise TimeoutError("PhantomBuster did not finish within 30 minutes")


def _phantombuster_parse_results(data: dict) -> list[str]:
    """Extract LinkedIn profile URLs from the phantom output."""
    import io
    import re

    # Strategy 1: Try resultObject (JSON data directly from PhantomBuster)
    result_object = data.get("resultObject")
    if result_object:
        if isinstance(result_object, str):
            import json as _json
            result_object = _json.loads(result_object)
        if isinstance(result_object, list):
            urls = []
            for entry in result_object:
                url = ""
                if isinstance(entry, dict):
                    url = entry.get("profileUrl") or entry.get("linkedInProfileUrl") or entry.get("url", "")
                elif isinstance(entry, str):
                    url = entry
                if url and "linkedin.com" in url:
                    urls.append(url)
            if urls:
                return urls

    # Strategy 2: Extract the S3 CSV URL from the console output log
    output_text = data.get("output", "")
    csv_match = re.search(r'(https://phantombuster\.s3\.amazonaws\.com/[^\s]+\.csv)', output_text)
    if csv_match:
        csv_url = csv_match.group(1)
        _log(f"Fetching results from CSV: {csv_url}")
        resp = requests.get(csv_url, timeout=60)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        urls = []
        for row in reader:
            url = (row.get("profileLink") or row.get("profileUrl")
                   or row.get("linkedInProfileUrl") or row.get("url") or "")
            if "linkedin.com" in url:
                urls.append(url)
        return urls

    # Strategy 3: Try the JSON URL from console output
    json_match = re.search(r'(https://phantombuster\.s3\.amazonaws\.com/[^\s]+\.json)', output_text)
    if json_match:
        json_url = json_match.group(1)
        _log(f"Fetching results from JSON: {json_url}")
        resp = requests.get(json_url, timeout=60)
        resp.raise_for_status()
        import json as _json
        results = _json.loads(resp.text)
        if isinstance(results, list):
            urls = []
            for entry in results:
                if isinstance(entry, dict):
                    url = entry.get("profileUrl") or entry.get("linkedInProfileUrl") or entry.get("url", "")
                    if url and "linkedin.com" in url:
                        urls.append(url)
            return urls

    return []


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

    # ---- Step 2: PhantomBuster ----
    try:
        container_id = _phantombuster_launch(post_url)
    except Exception as exc:
        _send_error("PHANTOMBUSTER LAUNCH", str(exc), post_url)
        return

    try:
        pb_data = _phantombuster_poll(container_id)
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

        # Rate limit: 2s between Prospeo calls + 5s between profiles
        if i < total_scraped - 1:
            time.sleep(5)

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
