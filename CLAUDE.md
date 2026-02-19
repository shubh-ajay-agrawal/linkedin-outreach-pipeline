# CLAUDE.md — Project Context & Instructions

## Project Status: COMPLETE AND RUNNING

The pipeline is fully built, deployed, and tested. It works end-to-end from Slack.

---

## Who is the user?

Shubh is non-technical. He does not write code. Every explanation must be:
- Written in plain English, no jargon
- Broken into small numbered steps
- Accompanied by the exact Terminal commands to copy-paste (when relevant)
- Explained with analogies or anecdotes so he understands WHY, not just WHAT

When Shubh asks "what should I do next?", don't dump 10 things on him. Give him ONE step at a time, confirm he's done, then give the next.

---

## What we built

A **LinkedIn outreach pipeline** that runs automatically via a Slack bot.

### The analogy:
Think of it like a vending machine. Shubh drops a LinkedIn post URL into a Slack channel (that's the coin). The machine automatically does 5 things and spits out a result (leads added to his email campaign + a summary in Slack).

### The 5 things the machine does:

1. **Scrapes engagers** — Uses PhantomBuster (two phantoms: likers + commenters) to grab everyone who liked/commented on that LinkedIn post.

2. **Finds their emails** — Uses Prospeo to look up verified email addresses for each person. Only returns emails Prospeo can verify as real (`only_verified_email: true`). This gives a 30-50% hit rate, which is intentionally conservative to protect sender reputation.

3. **Filters by job title** — Only keeps decision-makers (founders, CEOs, VPs, directors). Drops students, interns, freelancers.

4. **Pushes to email campaign** — Adds the clean leads to an Instantly email campaign so they get Shubh's outreach sequence.

5. **Reports back** — Sends a summary message to Slack with all the numbers.

---

## Tech decisions

| Decision | Choice | Why |
|---|---|---|
| PhantomBuster approach | TWO separate phantoms (likers + commenters), launched in parallel, results merged & deduped | The combined phantom got corrupted after heavy testing. Separate phantoms are simpler and more robust. |
| PhantomBuster API version | v2 (`/api/v2/agents/launch` with `argument` passed directly, `/api/v2/agents/fetch-output` for polling) | Pass the post URL directly in the launch call. Results come as CSV on S3, extracted via regex from the console output. |
| Prospeo enrichment | v2 `/enrich-person` endpoint with `only_verified_email: true` | Only returns verified emails to protect sender reputation. 30-50% enrichment rate is expected and intentional. |
| Prospeo rate limiting | 0.5 seconds between calls (2/sec) | Shubh's plan allows 30/sec. We use 2/sec for safety margin. |
| Instantly API version | v2 (`/api/v2/leads` with Bearer auth). **IMPORTANT: use `campaign` field, NOT `campaign_id`** | `campaign_id` is silently ignored. Must use `campaign`. |
| Slack integration | Events API with URL verification | Standard for production, works with Railway |
| Deployment | Railway, auto-deploys from GitHub | Simple, reliable |
| Web framework | Flask | Lightweight, perfect for a single webhook endpoint |

---

## File structure

| File | What it does |
|---|---|
| `main.py` | The front door. Listens for Slack messages, verifies they're real, spots LinkedIn URLs, and kicks off the pipeline in a background thread. |
| `pipeline.py` | The brain. Launches both PhantomBuster phantoms, polls for results, enriches via Prospeo, filters by title, pushes to Instantly, sends Slack summary. |
| `title_filter.py` | The bouncer. Checks job titles and only lets decision-makers through. |
| `.env` | API keys (filled in and working — all 5 keys verified). |
| `.env.example` | Template showing which API keys are needed. |
| `requirements.txt` | Python packages: flask, requests, python-dotenv. |
| `Procfile` | Tells Railway how to start the app (`web: python main.py`). |
| `README.md` | Setup instructions. |

### Test files (can be deleted):
- `test_pipeline.py`, `test_pipeline_100.py`, `enrichment_log.csv`

---

## Hardcoded constants

- **PhantomBuster Likers Phantom ID**: `7700895230156471`
- **PhantomBuster Commenters Phantom ID**: `6672845611180416`
- **PhantomBuster OLD Combined Phantom ID**: `5647257991330907` — **DO NOT USE, corrupted**
- **Instantly Campaign ID**: `75654875-36a1-4565-a47a-fcff4426a442` (campaign name: "Claudecode_experimental")
- **Slack channel**: `#linkedin-scraper`
- **PhantomBuster poll interval**: 30 seconds
- **PhantomBuster max wait**: 30 minutes
- **Prospeo delay between calls**: 0.5 seconds
- **Instantly delay between calls**: 1 second

---

## Credentials (stored in `.env` and Railway environment variables)

| Variable | What it is | Where Shubh gets it |
|---|---|---|
| `PHANTOMBUSTER_API_KEY` | Authenticates with PhantomBuster | PhantomBuster dashboard → profile icon → API Keys |
| `PROSPEO_API_KEY` | Authenticates with Prospeo | Prospeo dashboard → API in sidebar |
| `INSTANTLY_API_KEY` | Authenticates with Instantly | Instantly → Settings → API → generate key |
| `SLACK_BOT_TOKEN` | Lets the bot read/send Slack messages | Slack app → OAuth & Permissions → Bot Token (starts with `xoxb-`) |
| `SLACK_SIGNING_SECRET` | Verifies incoming requests are from Slack | Slack app → Basic Information → Signing Secret |

---

## Deployment info

- **GitHub repo**: `https://github.com/shubh-ajay-agrawal/linkedin-outreach-pipeline`
- **Railway project**: "dependable-nourishment" / production
- **Railway public URL**: `https://web-production-e430.up.railway.app`
- **Health check**: `/health` returns `{"status":"ok"}`
- **Slack Events URL**: `https://web-production-e430.up.railway.app/slack/events`
- **Auto-deploy**: Railway auto-deploys when code is pushed to `main` branch on GitHub

---

## Full bug history (for reference)

### Session 1 (2026-02-18) — Building & local testing:
1. **Python 3.9 compatibility** — `dict | None` type hint changed to `Optional[dict]`
2. **PhantomBuster Phantom ID** — was wrong, updated to `5647257991330907`
3. **PhantomBuster launch method** — Can pass `argument` directly in launch call
4. **PhantomBuster CSV parsing** — `resultObject` is always null; results are in CSV on S3; column is `profileLink` not `profileUrl`
5. **Prospeo API migration** — Old endpoints dead; new endpoint is `/enrich-person`
6. **Prospeo API key** — Original key was wrong; correct key is the "CC pirpleine" key
7. **Instantly `campaign` vs `campaign_id`** — Must use `campaign`, not `campaign_id`

### Session 2 (2026-02-19) — Deployment & Slack integration:
8. **PhantomBuster polling used old results** — Poll now checks `containerId` matches our launch
9. **PhantomBuster `companyUrl` vs `linkedinPostUrl`** — Updated both fields
10. **Slack URL pipe separator** — Slack wraps links as `<url|display_text>`; fixed by splitting on `|`
11. **PhantomBuster `launchType` values** — Must be `"repeatedly"` for API launches

### Session 3 (2026-02-19/20) — PhantomBuster fix & Prospeo speedup:
12. **Combined phantom corrupted** — After 43 launches, the combined phantom (ID: `5647257991330907`) refused to scrape LinkedIn. It would start, save empty results, and exit in ~9 seconds regardless of configuration. Root cause: internal leads database was full (`databaseLeft: 0` on the account) and the phantom's internal state was corrupted. No API endpoint exists to clear the phantom's leads database. **Fixed by switching to two separate, working phantoms** (likers: `7700895230156471`, commenters: `6672845611180416`). These are simpler, don't have the complex caching, and were already on Shubh's account.
13. **Prospeo enrichment too slow** — Was waiting 7 seconds between calls (2s delay + 5s profile delay). Shubh's plan allows 30 requests/sec. **Fixed by reducing to 0.5s between calls** — 14x speedup.
14. **Railway not auto-deploying** — After pushing the Prospeo speedup commit, Railway kept redeploying the old commit. Fixed by pushing a new commit to force Railway to pick it up.

---

## Troubleshooting guide (if something breaks)

| Symptom | Likely cause | Fix |
|---|---|---|
| Bot doesn't respond in Slack at all | Railway app is down | Check Railway dashboard — restart if needed |
| Bot says "Got it!" but then reports 0 profiles | LinkedIn session cookie expired | Go to PhantomBuster dashboard → reconnect LinkedIn on BOTH the likers and commenters phantoms |
| Prospeo returns 0 emails | Prospeo credits exhausted | Check Prospeo dashboard for credit balance |
| Instantly shows errors | API key rotated or campaign deleted | Check Instantly settings for valid API key; verify campaign still exists |
| Pipeline works but leads aren't in the campaign | Using `campaign_id` instead of `campaign` | Verify pipeline.py uses `"campaign"` field (not `"campaign_id"`) |

---

## How to explain things to Shubh

### DO:
- Use analogies
- Give one step at a time, wait for confirmation
- Provide exact copy-paste commands for Terminal
- Tell him what he should SEE after each step
- If something fails, ask him to paste the error message

### DON'T:
- Use jargon without explaining it
- Give him 10 steps at once
- Assume he knows what Terminal output means

---

## Error handling notes

- Every step in the pipeline is wrapped in try/except — if one step fails, it sends an error to Slack and stops gracefully
- If Prospeo can't find an email for someone, that person is silently skipped (not an error)
- If Instantly says a lead already exists, it's counted as a duplicate and skipped
- All errors print to console with timestamps (visible in Railway logs)

---

## Title filter rules

**KEEP** leads with titles containing: founder, co-founder, cofounder, ceo, chief executive, cro, chief revenue, head of sales/growth/revenue/marketing, vp sales/growth, vice president sales/growth, director of sales/growth/revenue, account executive, ae, demand gen, demand generation, revenue, gtm, go-to-market, sales lead, growth lead, owner

**DROP** leads with titles containing: student, intern, internship, freelance, freelancer, job seeker, looking for, open to work, assistant, coordinator, entry level, junior

**BLANK title** = keep the lead (benefit of the doubt — maybe their title just isn't listed)

---

## PhantomBuster reference (for future debugging)

### Phantoms on Shubh's account (via API):
| ID | Name | Status |
|---|---|---|
| `7700895230156471` | Extracting likers from LinkedIn post | **ACTIVE — used by pipeline** |
| `6672845611180416` | Extracting commenters from LinkedIn post | **ACTIVE — used by pipeline** |
| `5647257991330907` | DO NOT TOUCH _ CLAUDE CODE SCRAPER | **BROKEN — do not use** |
| `4924999688120171` | Extracting likers from LinkedIn post | Unused duplicate |
| `5428501435053769` | Extracting commenters from LinkedIn post | Unused duplicate |
| `2852357423068156` | Extracting Posts from LinkedIn page | Unused |
| `4246249022549027` | Saving your LinkedIn Leads | Unused |

### How the pipeline uses PhantomBuster:
1. Fetches each phantom's saved argument (to get `sessionCookie` and `userAgent`)
2. Launches each phantom with `argument` passed directly in the launch call (not saved)
3. The argument contains: `postUrl`, `sessionCookie`, `userAgent`, `numberOfPostsPerLaunch: 1`, `csvName: "result"`, `watcherMode: false`, `excludeOwnProfileFromResult: true`
4. Polls `fetch-output` every 30 seconds, checking `containerId` matches our launch
5. Extracts CSV URL from console output via regex
6. Downloads CSV and reads `profileLink` column for LinkedIn profile URLs
7. Deduplicates across both phantoms' results

### Key PhantomBuster lessons learned:
- Combined phantoms can get corrupted after many launches — prefer simpler single-purpose phantoms
- `launchType` must be `"repeatedly"` for API launches to work
- `fileMgmt: "delete"` clears old CSV data but doesn't fix corrupted internal state
- There is NO API to clear a phantom's internal leads database
- Session cookies can expire — reconnect LinkedIn in the dashboard if scraping returns 0
