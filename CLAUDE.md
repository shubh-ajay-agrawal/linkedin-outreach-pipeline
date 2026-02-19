# CLAUDE.md — Project Context & Instructions

## Who is the user?

Shubh is non-technical. He does not write code. Every explanation must be:
- Written in plain English, no jargon
- Broken into small numbered steps
- Accompanied by the exact Terminal commands to copy-paste (when relevant)
- Explained with analogies or anecdotes so he understands WHY, not just WHAT

When Shubh asks "what should I do next?", don't dump 10 things on him. Give him ONE step at a time, confirm he's done, then give the next.

---

## What are we building?

A **LinkedIn outreach pipeline** that runs automatically via a Slack bot.

### The analogy:
Think of it like a vending machine. Shubh drops a LinkedIn post URL into a Slack channel (that's the coin). The machine automatically does 5 things and spits out a result (leads added to his email campaign + a summary in Slack).

### The 5 things the machine does:

1. **Scrapes engagers** — Uses PhantomBuster to grab everyone who liked/commented on that LinkedIn post. Like hiring someone to write down the name of every person who raised their hand at a conference talk.

2. **Finds their emails** — Uses Prospeo to look up verified email addresses for each person. Like looking up someone's business card after getting their name. We try two methods: first by their LinkedIn URL, and if that doesn't work, by their name + company.

3. **Filters by job title** — Only keeps decision-makers (founders, CEOs, VPs, directors). Drops students, interns, freelancers. Like sorting a stack of business cards and only keeping the ones from people who can actually buy your product.

4. **Pushes to email campaign** — Adds the clean leads to an Instantly email campaign so they get Shubh's outreach sequence. Like loading addresses into an envelope-stuffing machine.

5. **Reports back** — Sends a summary message to Slack with all the numbers (how many scraped, enriched, filtered, added). Like getting a receipt from the vending machine.

---

## Tech decisions already made

| Decision | Choice | Why |
|---|---|---|
| PhantomBuster API version | v2 (`/api/v2/agents/save` to update config, then `/api/v2/agents/launch` + `/api/v2/agents/fetch-output`) | Must save config first (post URL + engager types), then launch. Results come as CSV on S3, extracted via regex from the console output. |
| Prospeo enrichment strategy | Single-call: v2 `/enrich-person` endpoint with `only_verified_email: true` and `linkedin_url` in `data` object | Old endpoints (`/linkedin-email-finder`, `/email-finder`) are deprecated. New v2 API returns person + company objects. |
| Instantly API version | v2 (`/api/v2/leads` with Bearer auth). **IMPORTANT: use `campaign` field, NOT `campaign_id`** | `campaign_id` is silently ignored — leads get added to workspace but not to the campaign. Must use `campaign`. |
| Slack integration method | Events API with URL verification | Standard for production, works with Railway |
| Deployment platform | Railway | Simple, auto-deploys from GitHub |
| Web framework | Flask | Lightweight, perfect for a single webhook endpoint |

---

## File structure (all files are already created)

| File | What it does |
|---|---|
| `main.py` | The front door. Listens for Slack messages, verifies they're real, spots LinkedIn URLs, and kicks off the pipeline in the background. |
| `pipeline.py` | The brain. Runs the full 5-step process: PhantomBuster → Prospeo → title filter → Instantly → Slack summary. **Heavily modified during testing** — PhantomBuster launch logic, Prospeo enrichment, Instantly push, and CSV parsing were all rewritten. |
| `title_filter.py` | The bouncer. Checks job titles and only lets decision-makers through. |
| `.env.example` | A template showing which API keys are needed (no real values). |
| `.env` | The real API keys (**filled in and working** — all 5 keys verified). |
| `requirements.txt` | The shopping list of Python packages to install (flask, requests, python-dotenv). |
| `Procfile` | One line that tells Railway how to start the app. |
| `README.md` | Setup instructions (more technical, for reference). |
| `test_pipeline.py` | Test script — runs pipeline directly, bypassing Slack. *Can delete after deployment.* |
| `test_pipeline_100.py` | Test script — runs pipeline on first 100 profiles only. *Can delete after deployment.* |
| `enrichment_log.csv` | Log of all enrichment results from test runs. *Can delete after deployment.* |

---

## Hardcoded constants (do not change these)

- **PhantomBuster Phantom ID**: `5647257991330907` (renamed by Shubh, but code uses this ID)
- **Instantly Campaign ID**: `75654875-36a1-4565-a47a-fcff4426a442` (campaign name: "Claudecode_experimental")
- **Slack channel**: `#linkedin-scraper`
- **PhantomBuster poll interval**: 120 seconds
- **PhantomBuster max wait**: 30 minutes
- **Prospeo delay between calls**: 2 seconds
- **Profile delay before enrichment**: 5 seconds
- **Instantly delay between calls**: 1 second
- **PhantomBuster engager types**: `["likers", "commenters"]`

---

## Credentials needed (stored in `.env`)

| Variable | What it is | Where Shubh gets it |
|---|---|---|
| `PHANTOMBUSTER_API_KEY` | Authenticates with PhantomBuster | PhantomBuster dashboard → profile icon → API Keys |
| `PROSPEO_API_KEY` | Authenticates with Prospeo | Prospeo dashboard → API in sidebar |
| `INSTANTLY_API_KEY` | Authenticates with Instantly | Instantly → Settings → API → generate key |
| `SLACK_BOT_TOKEN` | Lets the bot read/send Slack messages | Slack app → OAuth & Permissions → Bot Token (starts with `xoxb-`) |
| `SLACK_SIGNING_SECRET` | Verifies incoming requests are from Slack (security) | Slack app → Basic Information → Signing Secret |

---

## Where Shubh is in the process

### DONE:
- All code files created, debugged, and tested end-to-end
- `.env` file created with all 5 API keys filled in
- Slack app created (Bot Token + Signing Secret obtained)
- Python virtual environment set up and dependencies installed (`venv/`)
- PhantomBuster phantom configured, renamed, LinkedIn connected, auto-launch enabled
- PhantomBuster billing issue resolved (card updated)
- App boots locally without errors (runs on port 3000)
- **Full end-to-end local test completed successfully** on 2026-02-18:
  - Test post: Dima Bilous AI sales team post
  - PhantomBuster scraped 941 engagers
  - Prospeo enriched 52 of 100 tested profiles (52% hit rate)
  - Title filter kept 19 decision-makers, dropped 33
  - All 19 leads successfully pushed to Instantly "Claudecode_experimental" campaign
  - Slack summary message sent to `#linkedin-scraper`
- **Deployed to Railway on 2026-02-19:**
  - GitHub repo created: `https://github.com/shubh-ajay-agrawal/linkedin-outreach-pipeline`
  - Code pushed to GitHub, Railway auto-deploys from it
  - Railway project: "dependable-nourishment" / production
  - Railway public URL: `https://web-production-e430.up.railway.app`
  - Health check verified: `/health` returns `{"status":"ok"}`
  - All 5 environment variables added to Railway (PHANTOMBUSTER_API_KEY, PROSPEO_API_KEY, INSTANTLY_API_KEY, SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET)
  - Deployment status: ACTIVE / Online
- **Slack Events API connected on 2026-02-19:**
  - Request URL set to: `https://web-production-e430.up.railway.app/slack/events`
  - URL verification: passed (green checkmark)
  - Bot event subscription added: `message.channels`
  - Bot was already in `#linkedin-scraper` channel from prior local testing
- **First Railway pipeline run triggered on 2026-02-19:**
  - Shubh pasted a LinkedIn post URL in `#linkedin-scraper`
  - Pipeline started on Railway (visible in Railway logs)
  - Ran against old Dima Bilous data (941 profiles) due to PhantomBuster container ID bug (see bug #8 below) — this is fine, Shubh confirmed he's OK using that data

### Bugs found and fixed during testing:
1. **Python 3.9 compatibility** — `dict | None` type hint changed to `Optional[dict]` (Mac has Python 3.9)
2. **PhantomBuster Phantom ID** — was wrong (`5251160215300729`), updated to `5647257991330907`
3. **PhantomBuster launch method** — Originally thought you cannot pass `argument` in launch call, but Swagger spec confirms you CAN pass `argument` or `bonusArgument` directly in the launch call. However, using save-then-launch is still valid. The relevant argument fields are `linkedinPostUrl`, `companyUrl`, `inputType`, `postEngagersToExtract`, `sessionCookie`, `userAgent`, and optionally `postsPublishedFromDate`.
4. **PhantomBuster CSV parsing** — `resultObject` is always null. Results are in a CSV on S3. URL must be extracted via regex from the `output` (console log) field. Also, the profile URL column is `profileLink` (941 rows) not `profileUrl` (only 50 rows).
5. **Prospeo API migration** — Old endpoints (`/linkedin-email-finder`, `/email-finder`) are dead. New endpoint is `/enrich-person` with `{"only_verified_email": true, "data": {"linkedin_url": "..."}}`. Response structure is `{"person": {...}, "company": {...}}`.
6. **Prospeo API key** — Original key was wrong. Correct key is the "CC pirpleine" key from Prospeo dashboard.
7. **Instantly `campaign` vs `campaign_id`** — The v2 API field is `campaign`, NOT `campaign_id`. Using `campaign_id` silently adds leads to workspace without linking to the campaign.
8. **PhantomBuster polling used old results** — The `_phantombuster_poll` function checked agent status but never verified the `containerId` matched the run we launched. If a previous run was already "finished", the poll would immediately return OLD results instead of waiting for the new run. **Fixed on 2026-02-19:** poll now compares `containerId` in the response to the one returned by launch, and ignores results from old runs.

### Code changes pushed to GitHub on 2026-02-19 (all deployed to Railway):
- **Acknowledgment message** — When the pipeline starts, it immediately sends a Slack message: "Got it! Starting the pipeline..." so Shubh knows the bot received the URL and is working. ✅ WORKING
- **Container ID check** — PhantomBuster polling now verifies it's looking at results from the correct run (bug #8 fix above). ✅ PUSHED
- **`companyUrl` field fix** — pipeline.py now updates BOTH `linkedinPostUrl` AND `companyUrl` in PhantomBuster config (see bug #9 below). ✅ PUSHED
- **Slack URL cleanup** — main.py now strips Slack's `|display_text` from URLs. Slack wraps links as `<url|display_text>` and the old regex captured both parts, creating a mangled double-URL. ✅ PUSHED

### Bugs found and fixed on 2026-02-19 (session 2):
9. **PhantomBuster `companyUrl` vs `linkedinPostUrl`** — Our code was only updating `linkedinPostUrl`, but PhantomBuster also uses `companyUrl`. Now we update BOTH. However, this alone did NOT fix the scraping issue — see bug #10.
10. **Slack URL pipe separator** — Slack formats links as `<actual_url|display_text>`. Our regex captured everything including the `|display_text`, sending a mangled URL to PhantomBuster (two URLs glued together with `|`). Fixed by splitting on `|` and taking only the first part.
11. **PhantomBuster `launchType` values** — The save endpoint accepts `"manually"` (not `"manual"`) and `"repeatedly"` (not `"automatic"`). Using wrong values causes 400 errors. Also, setting `launchType: "manually"` STOPS the phantom — it can't be launched via API in that state. The phantom MUST have `launchType: "repeatedly"` for API launches to work (PhantomBuster quirk).

### CRITICAL UNSOLVED BUG — PhantomBuster won't scrape new URLs:

**The #1 problem:** PhantomBuster keeps returning old cached data (941 profiles from the original Dima Bilous test post) instead of scraping whatever new URL Shubh pastes in Slack.

**Root cause investigation done on 2026-02-19:**
We dug deep into the PhantomBuster API and discovered multiple issues:

1. **The phantom has an `inputType` field** that tells it what mode to operate in. Valid values: `"linkedinPostUrl"`, `"linkedinCompanyUrl"`, `"linkedinProfileUrl"`, `"linkedinPostSearch"`. Our saved config was MISSING this field. We discovered this by fetching the phantom script's manifest via `/api/v2/scripts/fetch?id=5251160215300729`.

2. **When `inputType` is set, `postsPublishedFromDate` becomes required.** Setting `inputType: "linkedinPostUrl"` without `postsPublishedFromDate` causes: `"Error: the Phantom Configuration is invalid: must have required property 'postsPublishedFromDate'"`. Set `shouldOnlyRetrievePostsPublishedFromDate: false` and `postsPublishedFromDate: "01-01-2020"` to satisfy this.

3. **`fileMgmt: "mix"` (default) caches old results** — The phantom's result CSV accumulates data across ALL runs. Even after changing the URL, the old 941 profiles persist in the CSV. When the phantom runs, it re-exports these cached results without actually scraping LinkedIn. Setting `fileMgmt: "delete"` clears old CSV data, but the phantom STILL doesn't scrape — it just saves empty results and exits in ~9 seconds.

4. **The phantom has an internal leads database** (visible in the PhantomBuster dashboard "Leads" tab) that stores all 941 leads separately from the CSV. This is NOT the same as PhantomBuster's org-storage API (we checked — 0 leads found via org-storage for this phantom ID). The leads tab shows all the old Dima Bilous profiles. This internal database may be what prevents re-scraping.

5. **The PhantomBuster launch API supports `bonusArgument`** — a one-time argument override that gets merged with the saved argument. We discovered this from the Swagger spec at `github.com/phantombuster/public-gists/master/swagger-api-v2.json`. Passing `bonusArgument` with `inputType` in the launch call DID cause the phantom to read our argument (we could see it printed in the console output), but it still didn't scrape.

**What was tried and the results:**

| Attempt | Result |
|---|---|
| Update `linkedinPostUrl` only via `/agents/save` | URL saved correctly, phantom ignored it, returned old 941 profiles |
| Update BOTH `linkedinPostUrl` + `companyUrl` via `/agents/save` | Both saved correctly (verified by re-fetching), phantom still returned old 941 profiles |
| Set `fileMgmt: "delete"` to clear cached CSV | Old CSV cleared, but phantom saved EMPTY results (0 profiles) — didn't actually scrape LinkedIn |
| Set `fileMgmt: "delete"` + pass `inputType: "linkedinPostUrl"` via `bonusArgument` | Phantom printed the argument in console (confirmed it's reading it), but threw error: missing `postsPublishedFromDate` |
| Add `postsPublishedFromDate` + `shouldOnlyRetrievePostsPublishedFromDate: false` | Phantom stopped throwing error, but still didn't scrape — finished in ~9 seconds with 0 profiles |
| Save full argument with all fields via `/agents/save` + launch | (Was about to try this when session ended) |

**PhantomBuster API field reference (from Swagger spec):**

Launch endpoint (`/agents/launch`) accepts:
- `id` — phantom ID
- `argument` — full argument (JSON string or object), overrides saved argument for this run
- `bonusArgument` — one-time merge on top of saved argument
- `saveArgument` — boolean, if true saves the argument permanently
- `manualLaunch` — boolean

Save endpoint (`/agents/save`) accepts:
- `id`, `argument`, `fileMgmt` (`"folders"`, `"mix"`, `"delete"`), `launchType` (`"manually"`, `"repeatedly"`, `"once"`, `"after agent"`), `name`, `notifications`, etc.

Script argument schema (from `/api/v2/scripts/fetch?id=5251160215300729`):
- `inputType` — enum: `["linkedinCompanyUrl", "linkedinProfileUrl", "linkedinPostUrl", "linkedinPostSearch"]`
- `companyUrl` — the primary URL field (shown as "Enter the LinkedIn URL to scrape" in UI)
- `linkedinPostUrl` — URL field for single post mode
- `linkedinCompanyUrl` — URL field for company mode
- `linkedinProfileUrl` — URL field for profile mode
- `sessionCookie` — LinkedIn session cookie
- `userAgent` — browser user agent
- `postEngagersToExtract` — array: `["commenters", "likers"]`
- `shouldOnlyRetrievePostsPublishedFromDate` — boolean
- `postsPublishedFromDate` — string, format `"MM-DD-YYYY"`
- `excludeOwnProfileFromResult` — boolean
- `pushResultToCRM` — boolean

**Current state of the phantom (as of end of session 2026-02-19):**
- `fileMgmt` is set to `"delete"` (was changed during debugging)
- `launchType` is `"repeatedly"` (auto-launch ON — required for API launches)
- The saved argument has BOTH `linkedinPostUrl` and `companyUrl` set to Shubh's test post URL
- The ON/OFF toggle in the PhantomBuster dashboard is ON
- The phantom's "Leads" tab still shows the old 941 profiles from the Dima Bilous post
- The result CSV is currently empty (cleared by fileMgmt=delete)

### FIRST THING TO DO NEXT SESSION:

**The PhantomBuster scraping problem is the ONLY blocker.** Everything else works (Slack bot, Prospeo, title filter, Instantly push, Slack summary). Fix this one thing and the pipeline is fully operational.

**Approach 1 — Try the full argument in launch call (most promising, was about to test):**
```python
# Save complete argument with inputType and all required fields
new_arg = {
    'sessionCookie': '<keep existing>',
    'userAgent': '<keep existing>',
    'inputType': 'linkedinPostUrl',
    'linkedinPostUrl': NEW_URL,
    'companyUrl': NEW_URL,
    'postEngagersToExtract': ['likers', 'commenters'],
    'shouldOnlyRetrievePostsPublishedFromDate': False,
    'postsPublishedFromDate': '01-01-2020',
    'excludeOwnProfileFromResult': True,
    'pushResultToCRM': False,
}
# Then launch with argument= and saveArgument=True
```

**Approach 2 — Clear the phantom's internal leads database:**
The "Leads" tab in PhantomBuster dashboard still has 941 old profiles. These might be preventing the phantom from re-scraping. Ask Shubh to manually delete all leads from the phantom's Leads tab in the PhantomBuster UI, THEN try launching. There is NO API endpoint to clear these leads (the org-storage API returned 0 for this phantom).

**Approach 3 — Create a brand new phantom:**
If the old phantom is too polluted with cached data, create a fresh "LinkedIn Post Commenter and Liker Scraper" phantom through the PhantomBuster UI, connect Shubh's LinkedIn, and use the new phantom ID. Then update `PHANTOM_ID` in pipeline.py.

**Approach 4 — Set `fileMgmt` back to `"mix"` and don't pass `inputType`:**
The original phantom worked WITHOUT `inputType` in the argument. Maybe the script's default mode (when `inputType` is missing) knows how to handle `companyUrl`. With `fileMgmt: "delete"` AND no old cached data (after clearing leads), the phantom might scrape fresh. The key is that `inputType` might be changing the script's behavior in unexpected ways.

**After fixing PhantomBuster, update the pipeline code:**
Once we know the correct way to launch the phantom (which fields, which API params), update `_phantombuster_launch()` in `pipeline.py` to use the working approach. The current code only sets `linkedinPostUrl` and `companyUrl` — it may also need `inputType`, `postsPublishedFromDate`, `bonusArgument` in launch, `fileMgmt: "delete"`, etc.

**Also don't forget:**
- Set `fileMgmt` back to `"mix"` or `"delete"` as appropriate after testing
- The auto-launch schedule (once daily at 12:17 AM IST) is still active — consider disabling after pipeline works, OR leave it since it won't cause harm if there's no new data
- Clean up test data from Instantly campaign
- Test the full end-to-end flow from Slack (not just the PhantomBuster step)

### Test files (can be deleted after deployment):
- `test_pipeline.py` — basic pipeline test script
- `test_pipeline_100.py` — 100-profile capped test script
- `enrichment_log.csv` — log of enrichment results from test runs

---

## How to explain things to Shubh

### DO:
- Use analogies: "This is like putting your house key under the mat — the `.env` file is where the app looks for all its keys"
- Give one step at a time, wait for confirmation
- Provide exact copy-paste commands for Terminal
- Tell him what he should SEE after each step (so he knows it worked)
- If something fails, ask him to paste the error message so you can help

### DON'T:
- Use words like "endpoint", "middleware", "environment variable", "daemon" without explaining them
- Give him 10 steps at once
- Assume he knows what Terminal output means
- Skip explaining WHY something is needed

### Example of good explanation:
"Run this command in Terminal. It creates a safe little bubble (called a virtual environment) so the packages we install don't mess with anything else on your Mac:
```
python3 -m venv venv
```
You won't see any output — that's normal. It worked silently."

### Example of bad explanation:
"Create a venv and install the dependencies from requirements.txt."

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
