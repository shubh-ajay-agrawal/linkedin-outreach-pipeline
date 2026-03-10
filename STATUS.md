# STATUS.md — Current Project State

**Last updated:** 2026-03-10 (end of session 4)

---

## Current state: ARK AI MIGRATION — NOT YET TESTED SUCCESSFULLY

The code is written, deployed to Railway, and has been tested 3 times. Each test revealed a bug that was fixed and redeployed. The latest fix (webhook resend fallback) has **NOT been tested yet**.

---

## What's working

- PhantomBuster scraping (likers + commenters) — fully working, tested
- Ark AI export requests — now correctly batched at 300 URLs, `page: 0` included
- Ark AI webhook endpoint (`/webhook/ark`) — receives and processes webhooks correctly
- Ark AI webhook resend fallback — code deployed, **not yet tested**
- Title filter — unchanged, working
- Instantly push — unchanged, working
- Slack bot — unchanged, working
- Railway deployment — auto-deploys from GitHub, health check passes

## What's NOT working (yet)

- **Full end-to-end pipeline with Ark AI** — has not completed successfully yet
- The 3rd test got the furthest: PhantomBuster scraped 1,878 profiles, Ark AI accepted 7 batches, one batch's webhook arrived (295 people, 141 emails found — that's 48%), but batch 1's webhook never arrived within 15 minutes

## What needs to happen next

1. **TEST the current deployed code** — Drop a LinkedIn post URL in `#linkedin-scraper` and see if the webhook resend fallback works. The latest commit (f7484b1) is already deployed to Railway.

2. **If it works** — Celebrate! Update STATUS.md and CLAUDE.md to mark as complete.

3. **If webhook resend still fails** — Possible next steps:
   - Check Railway logs for the resend response (HTTP status + body)
   - Try fetching results directly via the "Find Emails by Track ID" endpoint (`/reference/people-email-finder-by-track-id`) as a secondary fallback
   - Consider if Flask's single-threaded dev server is the issue (multiple webhooks arriving concurrently) — might need to switch to gunicorn with multiple workers
   - Consider reducing batch count by increasing batch size (check if Ark AI has a higher limit for some filter types)

---

## Session 4 timeline (2026-03-09)

### What we did:
1. Replaced Prospeo with Ark AI in `pipeline.py` — removed `_prospeo_enrich()`, added `_ark_enrich_batch()` and `_parse_ark_results()`
2. Added `/webhook/ark` endpoint to `main.py` — receives Ark AI webhook, signals pipeline thread
3. Added shared state (`_ark_results`, `_ark_events`, `_ark_lock`) for thread-safe communication between Flask webhook handler and pipeline thread
4. Updated `.env.example` and `.env` — replaced `PROSPEO_API_KEY` with `ARK_AI_API_KEY`, added `BASE_URL`
5. Updated CLAUDE.md with all Ark AI details

### Bugs found and fixed:
| # | Bug | Fix | Commit | Tested? |
|---|---|---|---|---|
| 18 | 400: missing `page` field | Added `"page": 0` to payload | f02557c | Yes — led to bug 19 |
| 19 | 400: batch size > 300 | Split URLs into batches of 300 | a4678b6 | Yes — led to bug 20 |
| 20 | Webhook not received for batch 1 (15 min timeout) | Added resend fallback via `PATCH /people/notify`, waits 3 more min | f7484b1 | **NO — NOT TESTED YET** |

### Railway environment variables (already set):
- `ARK_AI_API_KEY` — set
- `BASE_URL` — set to `https://web-production-e430.up.railway.app`
- `PROSPEO_API_KEY` — removed

### Test post used:
```
https://www.linkedin.com/posts/vihaarnandigala_we-built-something-a-little-dangerous-for-activity-7435067509197844481-ED9C?utm_source=share&utm_medium=member_desktop&rcm=ACoAACxh_IMBBR8Ju48kO-SA5t82QfcHERfixkc
```
This post is large (1,878 engagers = 7 batches). Consider using a smaller post for the first successful test.

---

## Git commits this session:
1. `5db74db` — Replace Prospeo with Ark AI for email enrichment (initial implementation)
2. `f02557c` — Fix: add missing page field to Ark AI export request
3. `a4678b6` — Fix: split Ark AI requests into batches of 300
4. `f7484b1` — Fix: add webhook resend fallback when Ark AI webhook doesn't arrive
