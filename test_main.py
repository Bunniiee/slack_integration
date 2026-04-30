import pytest
import respx
import httpx
from fastapi.testclient import TestClient
from unittest.mock import patch
import main
from main import app, seen_call_ids, build_slack_body, TRANSCRIPT_LIMIT

client = TestClient(app)

COMPLETED_PAYLOAD = {
    "id": "call-abc-123",
    "agent_id": "agent-xyz-456",
    "status": "completed",
    "transcript": "Agent: Hello\nUser: Hi there",
    "telephony_data": {"duration": 87},
}


@pytest.fixture(autouse=True)
def clear_seen_ids():
    seen_call_ids.clear()
    yield
    seen_call_ids.clear()


class TestHealthCheck:
    def test_health_returns_ok(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestWebhookFiltering:
    def test_non_completed_status_is_ignored(self):
        for status in ["scheduled", "queued", "ringing", "in-progress", "failed", "no-answer"]:
            payload = {**COMPLETED_PAYLOAD, "status": status}
            response = client.post("/webhook", json=payload)
            assert response.status_code == 200
            body = response.json()
            assert body["ignored"] is True
            assert body["status"] == status

    def test_missing_required_field_returns_422(self):
        response = client.post("/webhook", json={"status": "completed"})
        assert response.status_code == 422

    def test_empty_body_returns_422(self):
        response = client.post("/webhook", json={})
        assert response.status_code == 422


class TestIdempotency:
    def test_duplicate_completed_event_is_ignored(self):
        with patch("main.SLACK_WEBHOOK_URL", "https://hooks.slack.com/fake"):
            with respx.mock:
                respx.post("https://hooks.slack.com/fake").mock(
                    return_value=httpx.Response(200, text="ok")
                )
                first = client.post("/webhook", json=COMPLETED_PAYLOAD)
                second = client.post("/webhook", json=COMPLETED_PAYLOAD)

        assert first.json() == {"ok": True, "call_id": "call-abc-123"}
        assert second.json() == {"ignored": True, "reason": "duplicate"}

    def test_different_call_ids_both_processed(self):
        payload_a = {**COMPLETED_PAYLOAD, "id": "call-001"}
        payload_b = {**COMPLETED_PAYLOAD, "id": "call-002"}

        with patch("main.SLACK_WEBHOOK_URL", "https://hooks.slack.com/fake"):
            with respx.mock:
                respx.post("https://hooks.slack.com/fake").mock(
                    return_value=httpx.Response(200, text="ok")
                )
                r1 = client.post("/webhook", json=payload_a)
                r2 = client.post("/webhook", json=payload_b)

        assert r1.json()["ok"] is True
        assert r2.json()["ok"] is True


class TestFieldExtraction:
    def test_duration_from_telephony_data(self):
        body = build_slack_body("id1", "agent1", 87, "Hello")
        fields = body["blocks"][1]["fields"]
        duration_field = next(f for f in fields if "Duration" in f["text"])
        assert "87s" in duration_field["text"]

    def test_duration_fallback_to_zero_when_missing(self):
        payload = {**COMPLETED_PAYLOAD, "telephony_data": None, "conversation_time": None}
        with patch("main.SLACK_WEBHOOK_URL", "https://hooks.slack.com/fake"):
            with respx.mock:
                respx.post("https://hooks.slack.com/fake").mock(
                    return_value=httpx.Response(200, text="ok")
                )
                response = client.post("/webhook", json=payload)
        assert response.status_code == 200

    def test_duration_fallback_to_conversation_time(self):
        payload = {**COMPLETED_PAYLOAD, "telephony_data": None, "conversation_time": 42}
        body = build_slack_body("id", "agent", 42, "hi")
        fields = body["blocks"][1]["fields"]
        duration_field = next(f for f in fields if "Duration" in f["text"])
        assert "42s" in duration_field["text"]

    def test_null_transcript_uses_fallback(self):
        payload = {**COMPLETED_PAYLOAD, "transcript": None}
        with patch("main.SLACK_WEBHOOK_URL", "https://hooks.slack.com/fake"):
            with respx.mock:
                respx.post("https://hooks.slack.com/fake").mock(
                    return_value=httpx.Response(200, text="ok")
                )
                response = client.post("/webhook", json=payload)
        assert response.status_code == 200
        assert response.json()["ok"] is True


class TestSlackPayloadShape:
    def test_slack_body_has_required_blocks(self):
        body = build_slack_body("id-1", "agent-1", 30, "Hello world")
        assert "blocks" in body
        assert body["blocks"][0]["type"] == "header"
        assert body["blocks"][1]["type"] == "section"
        assert body["blocks"][2]["type"] == "divider"
        assert body["blocks"][3]["type"] == "section"

    def test_slack_body_contains_all_four_fields(self):
        body = build_slack_body("call-id", "agent-id", 60, "transcript text")
        fields = body["blocks"][1]["fields"]
        text_combined = " ".join(f["text"] for f in fields)
        assert "call-id" in text_combined
        assert "agent-id" in text_combined
        assert "60s" in text_combined
        assert "UTC" in text_combined

    def test_transcript_truncated_at_limit(self):
        long_transcript = "x" * (TRANSCRIPT_LIMIT + 100)
        body = build_slack_body("id", "agent", 10, long_transcript)
        transcript_block = body["blocks"][3]["text"]["text"]
        assert "[truncated]" in transcript_block
        assert len(transcript_block) < TRANSCRIPT_LIMIT + 200

    def test_short_transcript_not_truncated(self):
        short = "Agent: Hi\nUser: Hello"
        body = build_slack_body("id", "agent", 10, short)
        transcript_block = body["blocks"][3]["text"]["text"]
        assert "[truncated]" not in transcript_block
        assert short in transcript_block


class TestSlackIntegration:
    def test_slack_failure_still_returns_200(self):
        with patch("main.SLACK_WEBHOOK_URL", "https://hooks.slack.com/fake"):
            with respx.mock:
                respx.post("https://hooks.slack.com/fake").mock(
                    return_value=httpx.Response(500, text="error")
                )
                response = client.post("/webhook", json=COMPLETED_PAYLOAD)
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_missing_slack_url_returns_500(self):
        with patch("main.SLACK_WEBHOOK_URL", None):
            response = client.post("/webhook", json=COMPLETED_PAYLOAD)
        assert response.status_code == 500
