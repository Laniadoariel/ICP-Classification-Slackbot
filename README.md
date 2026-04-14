# ICP Classification Slackbot

Slack bot that classifies a company into **Tier 1 / Tier 2 / Tier 3** when mentioned with a website URL, and replies in-thread with a structured result.

Includes a small local portal (FastAPI + SQLite) to manage the active ICP definition and view/search classification history.

## Prereqs
- Python 3.8+
- Git (optional, to clone)
- A Slack App configured for **Socket Mode**
  - **Event Subscriptions**: `app_mention`
  - **Bot token scopes**: `app_mentions:read`, `chat:write`, `channels:history`, `users:read`
  - **App-level token**: `connections:write` (Socket Mode)
- OpenAI API key (for real LLM mode)

## Download the project
Option A clone with Git:

```bash
git clone https://github.com/Laniadoariel/ICP-Classification-Slackbot.git
cd "ICP-Classification-Slackbot"
```

Option B: download ZIP from GitHub and extract it, then `cd` into the folder.

- [Download ZIP (main)](https://github.com/Laniadoariel/ICP-Classification-Slackbot/archive/refs/heads/main.zip)

## Setup
Install dependencies:

```bash
python -m pip install -e ".[dev]"
```

Notes:
- The portal displays timestamps in Israel local time (`Asia/Jerusalem`).

## Environment variables
- **`SLACK_BOT_TOKEN`**: Bot token (`xoxb-...`)
- **`SLACK_APP_TOKEN`**: App-level token (`xapp-...`) for Socket Mode
- **`OPENAI_API_KEY`**: OpenAI API key 
- **`OPENAI_MODEL`**: Model name
- **`SQLITE_PATH`**: SQLite DB path (default: `data/icp.db`)
- **`SEED_ICP_ON_STARTUP`**: (optional) `true` to seed the DB with `config/icp_definition.json` when empty
- **`ICP_DEFINITION_JSON`**: (optional) JSON string override for ICP 

## Set environment variables locally (Windows PowerShell)
Set the variables in the same terminal session where you run the bot.

```powershell
$env:SLACK_BOT_TOKEN="xoxb-..."
$env:SLACK_APP_TOKEN="xapp-..."
$env:OPENAI_API_KEY="sk-..."
$env:OPENAI_MODEL="gpt-4o"
$env:SQLITE_PATH="data/icp.db"
```

Then run the bot:

```powershell
python run_bot.py
```

## Run the bot

```bash
python run_bot.py
```

## Run the ICP portal (localhost:3000)

```bash
python -m uvicorn portal.app:app --host 127.0.0.1 --port 3000 --reload
```

Open:
- `http://127.0.0.1:3000/` (ICP form)
- `http://127.0.0.1:3000/history` (searchable history; auto-refresh)

What gets stored in SQLite:
- **Active ICP definition**: stored in `icp_definition`
- **Classifications**: stored in `classifications` (URL, tier, timestamp, Slack user id, Slack display name when available)

## How to test
### 1) Test in Slack
- Invite the bot to a channel:
  - `/invite @icp-bot`
- Mention it with a URL:
  - `@icp-bot https://example.com`
  - Only **public `https://`** URLs are supported (non-HTTPS and internal/private targets are blocked for safety).

### 2) Test the LLM
- Ensure `OPENAI_API_KEY` is set
- Run `python run_bot.py`

## GitHub Secrets (recommended)
If you run anything via **GitHub Actions** (CI, scheduled tests, deployments), store secrets in GitHub instead of committing them.

In your GitHub repo:
- Go to **Settings → Secrets and variables → Actions**
- Add these secrets:
  - `SLACK_BOT_TOKEN`
  - `SLACK_APP_TOKEN`
  - `OPENAI_API_KEY`
- Add these variables (optional):
  - `OPENAI_MODEL` (e.g. `gpt-4o`)
  - `SQLITE_PATH` (e.g. `data/icp.db`)

Then, in a workflow, you can map them like:

```yaml
env:
  SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
  SLACK_APP_TOKEN: ${{ secrets.SLACK_APP_TOKEN }}
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  OPENAI_MODEL: ${{ vars.OPENAI_MODEL }}
  SQLITE_PATH: ${{ vars.SQLITE_PATH }}
```

## Common troubleshooting
- **No response in Slack**
  - Confirm the bot is running (`python run_bot.py`) and shows “Bolt app is running!”
  - Make sure you invited the bot to the channel (`/invite @icp-bot`)
  - Reinstall the Slack app after changing scopes
- **History search fails / page breaks**
  - Restart the portal (uvicorn) and refresh the page
- **Make the ICP form empty again**
  - Stop portal + bot, delete `data/icp.db`, then restart the portal

## Known limitations (prompt injection)
- The bot scrapes **untrusted website text** and sends it to an LLM. A malicious website can try to influence the model’s output (prompt injection).
- The bot does **not** trust the model’s tier. Final tiering is computed **deterministically** from criteria matches.
- Free-text fields (company name / reasoning / buying signals) are **sanitized after the LLM call** (trimmed: instruction-like content, URLs, and emails are dropped or replaced).
- Treat LLM-generated text as **assistive** and review it before acting on it.
