"""
prospeo_test.py
Scrapes a LinkedIn post's engagers via PhantomBuster, then enriches each one
through Prospeo to measure the enrichment rate. Outputs a CSV file for sharing
with the Prospeo team.

Usage:
    python prospeo_test.py
    (paste the LinkedIn post URL when prompted)
"""

import csv
import io
import json
import os
import re
import sys
import time
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PB_BASE = "https://api.phantombuster.com/api/v2"
PROSPEO_BASE = "https://api.prospeo.io"
PHANTOM_LIKERS_ID = "7700895230156471"
PHANTOM_COMMENTERS_ID = "6672845611180416"
PB_POLL_INTERVAL = 30
PB_MAX_POLL_TIME = 30 * 60
PROSPEO_DELAY = 0.5


def log(msg):
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Step 1: PhantomBuster — scrape engagers
# ---------------------------------------------------------------------------

def launch_phantom(phantom_id, label, post_url):
    api_key = os.environ["PHANTOMBUSTER_API_KEY"]
    headers = {"X-Phantombuster-Key": api_key, "Content-Type": "application/json"}

    # Get saved argument (for session cookie)
    resp = requests.get(
        f"{PB_BASE}/agents/fetch",
        headers={"X-Phantombuster-Key": api_key},
        params={"id": phantom_id},
        timeout=30,
    )
    resp.raise_for_status()
    saved_arg = resp.json().get("argument", {})
    if isinstance(saved_arg, str):
        saved_arg = json.loads(saved_arg)

    launch_arg = {
        "postUrl": post_url,
        "sessionCookie": saved_arg.get("sessionCookie", ""),
        "userAgent": saved_arg.get("userAgent", ""),
        "numberOfPostsPerLaunch": 1,
        "csvName": "result",
        "watcherMode": False,
        "excludeOwnProfileFromResult": True,
    }

    log(f"Launching {label} phantom...")
    resp = requests.post(
        f"{PB_BASE}/agents/launch",
        headers=headers,
        json={"id": phantom_id, "argument": launch_arg, "saveArgument": False},
        timeout=30,
    )
    resp.raise_for_status()
    container_id = resp.json().get("containerId")
    log(f"{label} phantom launched — container {container_id}")
    return container_id


def poll_phantom(phantom_id, container_id, label):
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

        status = data.get("status")
        resp_container = data.get("containerId")
        log(f"{label}: status={status}, container={resp_container} ({elapsed}s)")

        if resp_container != container_id:
            continue

        if status == "finished":
            return data
        if status in ("error", "stopped"):
            raise RuntimeError(f"{label} phantom failed with status: {status}")

    raise TimeoutError(f"{label} phantom didn't finish in 30 minutes")


def scrape_post(post_url):
    """Launch both phantoms, poll, extract and deduplicate LinkedIn URLs."""
    log("Starting PhantomBuster scrape...")

    likers_cid = launch_phantom(PHANTOM_LIKERS_ID, "Likers", post_url)
    commenters_cid = launch_phantom(PHANTOM_COMMENTERS_ID, "Commenters", post_url)

    log("Both phantoms launched. Polling for results (this takes 5-15 min)...")

    likers_data = poll_phantom(PHANTOM_LIKERS_ID, likers_cid, "Likers")
    commenters_data = poll_phantom(PHANTOM_COMMENTERS_ID, commenters_cid, "Commenters")

    all_urls = []
    for label, data in [("Likers", likers_data), ("Commenters", commenters_data)]:
        output_text = data.get("output", "")
        csv_match = re.search(
            r'(https://phantombuster\.s3\.amazonaws\.com/[^\s]+\.csv)', output_text
        )
        if csv_match:
            log(f"Downloading {label} CSV...")
            resp = requests.get(csv_match.group(1), timeout=60)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            count = 0
            for row in reader:
                url = (row.get("profileLink") or row.get("profileUrl") or "")
                if url and "linkedin.com" in url:
                    all_urls.append(url)
                    count += 1
            log(f"{label}: {count} profiles found")

    # Deduplicate
    seen = set()
    unique = []
    for url in all_urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)

    log(f"Total unique profiles: {len(unique)}")
    return unique


# ---------------------------------------------------------------------------
# Step 2: Prospeo enrichment
# ---------------------------------------------------------------------------

def enrich_with_prospeo(linkedin_urls):
    """Enrich each URL via Prospeo. Returns list of result dicts."""
    api_key = os.environ["PROSPEO_API_KEY"]
    headers = {"Content-Type": "application/json", "X-KEY": api_key}

    results = []
    total = len(linkedin_urls)

    for i, url in enumerate(linkedin_urls, 1):
        log(f"Enriching {i}/{total}: {url}")

        try:
            resp = requests.post(
                f"{PROSPEO_BASE}/enrich-person",
                headers=headers,
                json={
                    "only_verified_email": True,
                    "data": {"linkedin_url": url},
                },
                timeout=30,
            )

            if not resp.ok:
                results.append({
                    "linkedin_url": url,
                    "status": f"http_error_{resp.status_code}",
                    "email": "",
                    "first_name": "",
                    "last_name": "",
                    "title": "",
                    "company": "",
                })
                continue

            body = resp.json()

            if body.get("error"):
                results.append({
                    "linkedin_url": url,
                    "status": "api_error",
                    "email": "",
                    "first_name": "",
                    "last_name": "",
                    "title": "",
                    "company": "",
                })
                continue

            person = body.get("person", {}) or {}
            company_obj = body.get("company", {}) or {}
            email_obj = person.get("email", {}) or {}
            email_addr = email_obj.get("email", "") if isinstance(email_obj, dict) else ""

            results.append({
                "linkedin_url": url,
                "status": "found" if email_addr else "no_email",
                "email": email_addr,
                "first_name": person.get("first_name", ""),
                "last_name": person.get("last_name", ""),
                "title": person.get("current_job_title", ""),
                "company": company_obj.get("name", ""),
            })

        except Exception as exc:
            log(f"  Error: {exc}")
            results.append({
                "linkedin_url": url,
                "status": "exception",
                "email": "",
                "first_name": "",
                "last_name": "",
                "title": "",
                "company": "",
            })

        if i < total:
            time.sleep(PROSPEO_DELAY)

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    post_url = input("\nPaste the LinkedIn post URL and press Enter:\n> ").strip()

    if "linkedin.com" not in post_url:
        print("That doesn't look like a LinkedIn URL. Please try again.")
        sys.exit(1)

    # Clean Slack formatting if present
    post_url = post_url.rstrip(">")
    if "|" in post_url:
        post_url = post_url.split("|")[0]

    print(f"\n{'='*60}")
    print(f"POST: {post_url}")
    print(f"{'='*60}\n")

    # Step 1: Scrape
    linkedin_urls = scrape_post(post_url)

    if not linkedin_urls:
        print("\nNo profiles found. PhantomBuster returned nothing.")
        print("This usually means the LinkedIn session cookie expired.")
        print("Go to PhantomBuster dashboard and reconnect LinkedIn on both phantoms.")
        sys.exit(1)

    # Step 2: Enrich
    log(f"\nStarting Prospeo enrichment for {len(linkedin_urls)} profiles...\n")
    results = enrich_with_prospeo(linkedin_urls)

    # Step 3: Write CSV
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"prospeo_test_{timestamp}.csv"

    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "linkedin_url", "status", "email", "first_name", "last_name", "title", "company",
        ])
        writer.writeheader()
        writer.writerows(results)

    # Step 4: Print summary
    found = sum(1 for r in results if r["status"] == "found")
    no_email = sum(1 for r in results if r["status"] == "no_email")
    errors = sum(1 for r in results if r["status"] not in ("found", "no_email"))
    total = len(results)
    rate = round((found / total) * 100, 1) if total else 0

    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"LinkedIn post:        {post_url}")
    print(f"Profiles scraped:     {total}")
    print(f"Emails found:         {found}")
    print(f"No email:             {no_email}")
    print(f"Errors:               {errors}")
    print(f"ENRICHMENT RATE:      {rate}%")
    print(f"{'='*60}")
    print(f"\nFull results saved to: {filename}")
    print(f"Share this file with the Prospeo team.")


if __name__ == "__main__":
    main()
