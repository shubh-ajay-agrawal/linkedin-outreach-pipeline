# STATUS.md — Current Project State

**Last updated:** 2026-03-10 (end of session 5)

---

## Current state: TWO PARALLEL TRACKS

### Track 1: Prospeo — emailed their team about bad enrichment
### Track 2: Ark AI migration — deployed, not yet tested end-to-end

---

## Session 5 summary (2026-03-10)

### What we did:
Ran a Prospeo enrichment test to diagnose why enrichment rates were so bad.

### What we found:
- Tested against a LinkedIn post with **1,880 engagers**
- **419 emails found** (22.3% enrichment rate)
- **1,461 returned HTTP 400 errors** (not "no email found" — actual errors)
- **Root cause:** PhantomBuster returns two types of LinkedIn URLs:
  - Normal slugs like `linkedin.com/in/john-doe` — Prospeo handles these fine
  - Encoded IDs like `linkedin.com/in/ACoAABQuLHEB...` — Prospeo rejects ALL of these with HTTP 400
- **78% of scraped profiles** come as encoded IDs, which Prospeo can't handle
- So the real enrichment rate for URLs Prospeo accepts is much higher — it's just rejecting most of the input

### What Shubh did:
- Emailed the Prospeo team with these findings and the raw CSV file
- Waiting to hear back from them

### Files created this session:
- `prospeo_test.py` — standalone script that scrapes a LinkedIn post and enriches via Prospeo, outputs a CSV with results and enrichment rate
- `prospeo_test_20260310_122124.csv` — the actual test results (1,880 rows) shared with Prospeo team

### Test post used:
```
https://www.linkedin.com/posts/vihaarnandigala_we-built-something-a-little-dangerous-for-activity-7435067509197844481-ED9C
```

---

## What needs to happen next

### If Prospeo responds with a fix:
1. Re-run `prospeo_test.py` with the same post URL to verify encoded URLs now work
2. If enrichment rate jumps significantly, consider switching back to Prospeo (simpler — synchronous, no webhook complexity)

### If Prospeo can't/won't fix it:
1. Continue with Ark AI migration (Track 2 below)

### Ark AI migration (Track 2 — unchanged from session 4):
1. **TEST the current deployed code** — Drop a LinkedIn post URL in `#linkedin-scraper` and see if the webhook resend fallback works. The latest commit (f7484b1) is already deployed to Railway.
2. **If it works** — Update STATUS.md and CLAUDE.md to mark as complete.
3. **If webhook resend still fails** — Possible next steps:
   - Check Railway logs for the resend response
   - Try fetching results directly via Ark AI's "Find Emails by Track ID" endpoint as a secondary fallback
   - Consider if Flask's single-threaded dev server is the issue — might need gunicorn with multiple workers

---

## What's working (unchanged)

- PhantomBuster scraping (likers + commenters) — fully working
- Ark AI export requests — correctly batched at 300 URLs
- Ark AI webhook endpoint (`/webhook/ark`) — receives webhooks
- Ark AI webhook resend fallback — deployed, **not yet tested**
- Title filter — working
- Instantly push — working
- Slack bot — working
- Railway deployment — auto-deploys from GitHub

## What's NOT working (yet)

- **Prospeo:** rejects 78% of LinkedIn URLs (encoded format). Emailed their team.
- **Ark AI end-to-end:** has not completed successfully. Last test: 7 batches launched, 1 webhook arrived, batch 1 timed out. Resend fallback fix deployed but untested.

---

## Full session history

| Session | Date | What happened |
|---|---|---|
| 1 | 2026-02-18 | Built pipeline, local testing, fixed 7 bugs |
| 2 | 2026-02-19 | Deployed to Railway, Slack integration, fixed 4 bugs |
| 3 | 2026-02-19/20 | Fixed corrupted phantom, sped up Prospeo, pipeline working end-to-end |
| 4 | 2026-03-09 | Replaced Prospeo with Ark AI, deployed, 3 bugs found/fixed, not yet working |
| 5 | 2026-03-10 | Diagnosed Prospeo issue (78% URLs rejected), emailed Prospeo team, waiting for response |

---

## Git commits (sessions 4-5):
1. `5db74db` — Replace Prospeo with Ark AI for email enrichment
2. `f02557c` — Fix: add missing page field to Ark AI export request
3. `a4678b6` — Fix: split Ark AI requests into batches of 300
4. `f7484b1` — Fix: add webhook resend fallback when Ark AI webhook doesn't arrive
5. `61c9ca1` — Update docs: session 4 status, bugs, lessons, Ark AI reference
