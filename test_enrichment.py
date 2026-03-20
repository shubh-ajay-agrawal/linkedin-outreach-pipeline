"""
test_enrichment.py
Standalone test script — sends LinkedIn URLs to the deployed /test/enrich endpoint.

Usage:
    python test_enrichment.py urls.txt

Where urls.txt contains one LinkedIn profile URL per line, e.g.:
    https://www.linkedin.com/in/someone
    https://www.linkedin.com/in/another-person
"""

import csv
import json
import sys
import time

import requests

# The deployed Railway URL — change this if your deployment URL is different
BASE_URL = "https://web-production-e430.up.railway.app"


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_enrichment.py <urls_file>")
        print("  urls_file: text file with one LinkedIn profile URL per line")
        sys.exit(1)

    urls_file = sys.argv[1]

    # Read URLs from file
    with open(urls_file) as f:
        urls = [line.strip() for line in f if line.strip() and "linkedin.com" in line]

    if not urls:
        print(f"No LinkedIn URLs found in {urls_file}")
        sys.exit(1)

    print(f"Sending {len(urls)} LinkedIn URLs to {BASE_URL}/test/enrich ...")
    print("This may take several minutes (Ark AI processes in batches).\n")

    start = time.time()

    resp = requests.post(
        f"{BASE_URL}/test/enrich",
        json={"urls": urls},
        timeout=1200,  # 20 min timeout for large batches
    )

    elapsed = time.time() - start
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)

    if not resp.ok:
        print(f"ERROR: HTTP {resp.status_code}")
        print(resp.text)
        sys.exit(1)

    data = resp.json()

    # Print summary
    print("=" * 50)
    print("RESULTS")
    print("=" * 50)
    print(f"URLs sent:          {data['total_urls']}")
    print(f"Emails found:       {data['enriched']}")
    print(f"Bouncify passed:    {data['bouncify_passed']}")
    print(f"Bouncify rejected:  {data['bouncify_rejected']}")
    print(f"Time:               {mins}m {secs}s")
    print()

    leads = data.get("leads", [])
    if leads:
        # Print leads table
        print(f"{'Name':<30} {'Email':<35} {'Title':<30} {'Company':<20}")
        print("-" * 115)
        for lead in leads:
            name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
            print(f"{name:<30} {lead.get('email', ''):<35} {lead.get('title', '')[:30]:<30} {lead.get('company', '')[:20]:<20}")

        # Save to CSV
        csv_file = "test_enrichment_results.csv"
        with open(csv_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["first_name", "last_name", "email", "company", "title", "linkedin_url"])
            writer.writeheader()
            writer.writerows(leads)
        print(f"\nResults saved to {csv_file}")
    else:
        print("No leads returned.")


if __name__ == "__main__":
    main()
