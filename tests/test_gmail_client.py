from __future__ import annotations

import base64
import json
from email.message import EmailMessage
from types import SimpleNamespace

from job_explorer.gmail_client import GmailClient
from job_explorer.report import build_message
from job_explorer.state import STATE_FILENAME, encode_state


class FakeMessages:
    def __init__(self, listing=None, message=None, attachments=None) -> None:
        self.listing = listing or {"messages": []}
        self.message = message
        self.attachments_by_id = attachments or {}
        self.sent: list[dict] = []

    def list(self, **kwargs):
        return SimpleNamespace(execute=lambda: self.listing)

    def get(self, **kwargs):
        return SimpleNamespace(execute=lambda: self.message)

    def send(self, **kwargs):
        self.sent.append(kwargs["body"])
        return SimpleNamespace(execute=lambda: {"id": "sent-1"})

    def attachments(self):
        by_id = self.attachments_by_id

        class _Attachments:
            def get(self_inner, **kwargs):
                payload = by_id[kwargs["id"]]
                return SimpleNamespace(execute=lambda: payload)

        return _Attachments()


class FakeService:
    def __init__(self, messages: FakeMessages) -> None:
        self._messages = messages

    def users(self):
        messages = self._messages

        class _Users:
            def messages(self_inner):
                return messages

        return _Users()


def _state_message(payload: dict) -> dict:
    raw = json.dumps(payload).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii")
    return {
        "id": "m1",
        "payload": {
            "parts": [
                {
                    "filename": STATE_FILENAME,
                    "mimeType": "application/json",
                    "body": {"data": encoded},
                }
            ]
        },
    }


def test_zero_messages_empty_state() -> None:
    client = GmailClient(FakeService(FakeMessages()))
    state = client.fetch_previous_state()
    assert state.position_ids == set()
    assert state.positions == []


def test_fetches_json_attachment() -> None:
    payload = json.loads(encode_state({"primary": "sha256:z"}, []))
    payload["positions"] = [
        {"id": "example:1", "title": "T", "url": "u", "source_id": "example", "scores": {"primary": 1.0}}
    ]
    messages = FakeMessages(
        listing={"messages": [{"id": "m1"}]},
        message=_state_message(payload),
    )
    client = GmailClient(FakeService(messages))
    state = client.fetch_previous_state()
    assert "example:1" in state.position_ids
    assert state.resume_fingerprints["primary"] == "sha256:z"


def test_fetches_json_via_attachment_id() -> None:
    payload = json.loads(encode_state({"primary": "sha256:z"}, []))
    payload["positions"] = [
        {"id": "example:1", "title": "T", "url": "u", "source_id": "example", "scores": {"primary": 1.0}}
    ]
    raw = json.dumps(payload).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii")
    messages = FakeMessages(
        listing={"messages": [{"id": "m1"}]},
        message={
            "id": "m1",
            "payload": {
                "parts": [
                    {
                        "filename": STATE_FILENAME,
                        "mimeType": "application/json",
                        "body": {"attachmentId": "att-1", "size": len(raw)},
                    }
                ]
            },
        },
        attachments={"att-1": {"data": encoded}},
    )
    client = GmailClient(FakeService(messages))
    state = client.fetch_previous_state()
    assert "example:1" in state.position_ids
    assert state.resume_fingerprints["primary"] == "sha256:z"


def test_bad_json_attachment_empty() -> None:
    messages = FakeMessages(
        listing={"messages": [{"id": "m1"}]},
        message={
            "payload": {
                "parts": [
                    {
                        "filename": STATE_FILENAME,
                        "mimeType": "application/json",
                        "body": {"data": base64.urlsafe_b64encode(b"not-json").decode()},
                    }
                ]
            }
        },
    )
    client = GmailClient(FakeService(messages))
    state = client.fetch_previous_state()
    assert state.positions == []


def test_send_raw() -> None:
    messages = FakeMessages()
    client = GmailClient(FakeService(messages))
    email = EmailMessage()
    email["Subject"] = "t"
    email["From"] = "a@b.c"
    email["To"] = "a@b.c"
    email.set_content("hi")
    client.send_raw(bytes(email))
    assert messages.sent
    raw = messages.sent[0]["raw"]
    decoded = base64.urlsafe_b64decode(raw + "===")
    assert b"hi" in decoded


def test_build_message_round_trip_attachment() -> None:
    message = build_message(
        sender="me@example.com",
        to=["me@example.com"],
        new_rows=[],
        previous_rows=[],
        fingerprints={"primary": "sha256:x"},
    )
    found = False
    for part in message.iter_attachments():
        if part.get_filename() == STATE_FILENAME:
            found = True
            body = part.get_content()
            if isinstance(body, bytes):
                body = body.decode()
            assert "resume_fingerprints" in body
    assert found
