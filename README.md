# LinkedIn Signal-Based Outreach Pipeline

A Slack bot that monitors `#linkedin-scraper` for LinkedIn post URLs and automatically:
1. Scrapes all engagers from the post via PhantomBuster
2. Enriches their details via Prospeo (verified emails only)
3. Filters leads by job title (decision-makers only)
4. Pushes clean leads to an Instantly campaign
5. Sends a summary back to Slack

## Setup

### 1. Create your `.env` file

```bash
cp .env.example .env
```

Fill in every value:

| Variable | Where to get it |
|---|---|
| `PHANTOMBUSTER_API_KEY` | PhantomBuster dashboard → API Keys |
| `PROSPEO_API_KEY` | Prospeo dashboard → API |
| `INSTANTLY_API_KEY` | Instantly → Settings → API → Generate Key |
| `SLACK_BOT_TOKEN` | Slack API → Your App → OAuth & Permissions → Bot User OAuth Token (starts with `xoxb-`) |
| `SLACK_SIGNING_SECRET` | Slack API → Your App → Basic Information → Signing Secret |

### 2. Create your Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. **OAuth & Permissions** — add these Bot Token Scopes:
   - `chat:write` (send messages)
   - `channels:history` (read messages in public channels)
   - `channels:read` (list channels)
3. **Event Subscriptions** — enable and set the Request URL to:
   ```
   https://your-railway-url.up.railway.app/slack/events
   ```
4. Under **Subscribe to bot events**, add:
   - `message.channels`
5. Install the app to your workspace and copy the Bot Token
6. Invite the bot to `#linkedin-scraper`:
   ```
   /invite @YourBotName
   ```

### 3. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Test locally

```bash
python main.py
```

The server starts on port 3000. To receive Slack events locally, you'll need a tunnel:

```bash
# Using ngrok
ngrok http 3000
```

Then set the ngrok URL as your Slack Event Subscription Request URL:
```
https://xxxx.ngrok.io/slack/events
```

### 5. Deploy to Railway

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub Repo**
3. Select this repository
4. Go to **Variables** and add all 5 environment variables from your `.env`
5. Railway auto-detects the `Procfile` and deploys
6. Copy your Railway public URL and update the Slack Event Subscription Request URL to:
   ```
   https://your-app.up.railway.app/slack/events
   ```

## How it works

Paste a LinkedIn post URL into `#linkedin-scraper`:
```
https://www.linkedin.com/posts/someone_topic-activity-1234567890
```

The bot will scrape engagers, enrich emails, filter by title, push to Instantly, and post a summary like:

```
✅ Pipeline complete for:
https://www.linkedin.com/posts/...

👥 Engagers scraped: 127
📧 Emails enriched by Prospeo: 89 (70%)
🎯 Passed title filter: 54
🚫 Filtered out by title: 35
⏭️ Skipped (no email found): 38
➕ Added to Instantly campaign: 52
🔁 Duplicates skipped: 2
⏱ Total time: 14 mins 32 secs
```

## File structure

| File | Purpose |
|---|---|
| `main.py` | Flask app, Slack event listener, signature verification |
| `pipeline.py` | Full scrape → enrich → filter → push orchestration |
| `title_filter.py` | Job title filtering logic |
| `enrichment_log.csv` | Auto-generated log of all enrichment results |
| `.env.example` | Template for required environment variables |
| `requirements.txt` | Python dependencies |
| `Procfile` | Railway deployment command |
