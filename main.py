from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import httpx
import os
import logging
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Bolna-Slack Integration")

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

seen_call_ids: set[str] = set()

TRANSCRIPT_LIMIT = 2800


class TelephonyData(BaseModel):
    duration: Optional[int] = None
    to_number: Optional[str] = None
    from_number: Optional[str] = None
    recording_url: Optional[str] = None
    call_type: Optional[str] = None
    provider: Optional[str] = None
    hangup_by: Optional[str] = None
    hangup_reason: Optional[str] = None


class BolnaWebhookPayload(BaseModel):
    id: str
    agent_id: str
    status: str
    transcript: Optional[str] = None
    conversation_time: Optional[int] = None
    telephony_data: Optional[TelephonyData] = None
    created_at: Optional[str] = None
    batch_id: Optional[str] = None
    total_cost: Optional[float] = None
    error_message: Optional[str] = None
    answered_by_voice_mail: Optional[bool] = None


def build_slack_body(call_id: str, agent_id: str, duration: int, transcript: str) -> dict:
    if len(transcript) > TRANSCRIPT_LIMIT:
        transcript = transcript[:TRANSCRIPT_LIMIT] + "\n...[truncated]"

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return {
        "text": f"Bolna call completed — ID: {call_id}",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Bolna Call Completed", "emoji": True}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Call ID:*\n`{call_id}`"},
                    {"type": "mrkdwn", "text": f"*Agent ID:*\n`{agent_id}`"},
                    {"type": "mrkdwn", "text": f"*Duration:*\n{duration}s"},
                    {"type": "mrkdwn", "text": f"*Time:*\n{timestamp}"},
                ]
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Transcript:*\n```{transcript}```"
                }
            }
        ]
    }


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/webhook")
async def handle_webhook(payload: BolnaWebhookPayload):
    if payload.status != "completed":
        logger.info(f"Ignoring event with status: {payload.status!r} for call {payload.id}")
        return JSONResponse({"ignored": True, "status": payload.status})

    if payload.id in seen_call_ids:
        logger.warning(f"Duplicate completed event for call {payload.id} — skipping")
        return JSONResponse({"ignored": True, "reason": "duplicate"})

    seen_call_ids.add(payload.id)

    duration = (
        payload.telephony_data.duration
        if payload.telephony_data and payload.telephony_data.duration is not None
        else (payload.conversation_time or 0)
    )
    transcript = payload.transcript or "No transcript available"

    if not SLACK_WEBHOOK_URL:
        logger.error("SLACK_WEBHOOK_URL is not configured")
        raise HTTPException(status_code=500, detail="Slack webhook URL not configured")

    slack_body = build_slack_body(payload.id, payload.agent_id, duration, transcript)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(SLACK_WEBHOOK_URL, json=slack_body)
            response.raise_for_status()
        logger.info(f"Slack alert sent for call {payload.id}")
    except httpx.HTTPStatusError as e:
        logger.error(f"Slack returned error {e.response.status_code}: {e.response.text}")
    except httpx.RequestError as e:
        logger.error(f"Network error sending Slack alert: {e}")

    return JSONResponse({"ok": True, "call_id": payload.id})
