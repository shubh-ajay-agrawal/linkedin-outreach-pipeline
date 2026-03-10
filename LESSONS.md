# LESSONS.md — Mistakes & Rules

Things that went wrong and what to do instead. Read this before making changes.

---

## Ark AI API rules (learned the hard way)

1. **ALWAYS include `"page": 0`** in every `/people/export` request body. It's required even though it seems optional.

2. **NEVER send more than 300 LinkedIn URLs** in `contact.linkedin.any.include`. The API returns 400 if you exceed this. Always batch at 300.

3. **Ark AI webhooks are NOT reliable for every batch.** In our test with 7 batches, only 1 webhook arrived within 15 minutes. Always have a fallback (resend via `PATCH /people/notify`).

4. **Log the full error response body** from Ark AI, not just the HTTP status. The error messages are descriptive (e.g., "contact.linkedin.any.include size must be less or equal than 300").

5. **The `address` field in `email.output[]` only exists when `found: true`.** Don't assume it's always present.

---

## General pipeline rules (from all sessions)

6. **NEVER use `campaign_id` with Instantly v2 API.** Use `campaign` instead. `campaign_id` is silently ignored — leads vanish into nothing.

7. **NEVER use the old combined PhantomBuster phantom** (ID: `5647257991330907`). It's corrupted. Use the two separate phantoms (likers: `7700895230156471`, commenters: `6672845611180416`).

8. **Always check `containerId` when polling PhantomBuster.** The fetch-output endpoint returns the LATEST run's output, which might be from an old run, not yours.

9. **Slack wraps URLs as `<url|display_text>`.** Always split on `|` and take the first part when extracting URLs from Slack messages.

10. **PhantomBuster `launchType` must be `"repeatedly"`** for API-triggered launches to work.

---

## Deployment rules

11. **Always verify `.env` is in `.gitignore` before pushing.** API keys must never be committed.

12. **Railway env vars must be set in the dashboard.** Pushing `.env` to GitHub does nothing for Railway — the env vars live in Railway's dashboard separately.

13. **If Railway doesn't pick up a new commit**, push another commit to force it. Sometimes Railway gets stuck on an old deploy.
