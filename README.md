# Slack Integration

A FastAPI webhook server that listens for Bolna voice call events and sends a formatted Slack alert whenever a call is completed.

## What It Does

When a Bolna call ends, Bolna sends a webhook event to this server. The server:

1. Receives the webhook payload from Bolna
2. Filters only `completed` calls — all other statuses are ignored
3. Extracts the call `id`, `agent_id`, `duration`, and `transcript`
4. Sends a formatted Slack message to your configured channel
5. Handles duplicate events — the same call will never trigger two alerts

## Slack Alert Format

Each alert contains:
- **Call ID** — unique identifier for the call
- **Agent ID** — the Bolna agent that handled the call
- **Duration** — length of the call in seconds
- **Time** — UTC timestamp of when the alert was sent
- **Transcript** — full conversation transcript (truncated at 2800 characters if too long)

## Project Structure

```
├── main.py            # FastAPI webhook server
├── test_main.py       # Unit tests (16 tests)
├── requirements.txt   # Python dependencies
├── Procfile           # Railway/Heroku deployment config
├── .env.example       # Environment variable template
└── .gitignore
```

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set your Slack Incoming Webhook URL:

```
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
```

To get a Slack webhook URL:
- Go to [api.slack.com/apps](https://api.slack.com/apps)
- Create a new app → enable **Incoming Webhooks**
- Add webhook to a channel and copy the URL

### 3. Run the server

```bash
uvicorn main:app --reload --port 8000
```

### 4. Expose publicly (local development)

```bash
ngrok http 8000
```

Use the generated URL as your Bolna webhook: `https://your-ngrok-url/webhook`

### 5. Configure Bolna

- Go to [platform.bolna.ai](https://platform.bolna.ai) → open your agent
- Navigate to the **Analytics** tab
- Paste your webhook URL in **"Push all execution data to webhook"**
- Click **Save agent**

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/webhook` | Receives Bolna call events |

## Running Tests

```bash
pytest test_main.py -v
```

## Deployment

This project is configured for Railway deployment via the `Procfile`. Set the `SLACK_WEBHOOK_URL` environment variable in your Railway dashboard and deploy directly from this GitHub repository.

## Tech Stack

- **FastAPI** — web framework
- **Pydantic** — request validation
- **httpx** — async HTTP client for Slack requests
- **python-dotenv** — environment variable management
- **uvicorn** — ASGI server
