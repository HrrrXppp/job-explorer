from __future__ import annotations

import base64
import logging
import os
import re
from collections.abc import Mapping
from typing import Any, Protocol

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from job_explorer.models import PreviousState
from job_explorer.state import STATE_FILENAME, decode_state, empty_state, merge_previous_states

logger = logging.getLogger(__name__)

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]
SEARCH_QUERY = 'subject:"[job-explorer]" filename:job-explorer-state.json'
PREVIOUS_EMAIL_LIMIT = 3
FILENAME_RE = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";\r\n]+)"?', re.I)


class GmailPort(Protocol):
    def fetch_previous_state(self) -> PreviousState: ...

    def send_raw(self, mime_bytes: bytes) -> None: ...


class GmailClient:
    def __init__(self, service: Any, user_id: str = "me") -> None:
        self._service = service
        self._user_id = user_id

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> GmailClient:
        environ = env if env is not None else os.environ
        required = ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN", "GMAIL_USER")
        missing = [name for name in required if not environ.get(name)]
        if missing:
            raise RuntimeError("missing environment variables: " + ", ".join(missing))
        creds = Credentials(
            token=None,
            refresh_token=environ["GMAIL_REFRESH_TOKEN"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=environ["GMAIL_CLIENT_ID"],
            client_secret=environ["GMAIL_CLIENT_SECRET"],
            scopes=GMAIL_SCOPES,
        )
        creds.refresh(Request())
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return cls(service)

    def fetch_previous_state(self) -> PreviousState:
        listing = (
            self._service.users()
            .messages()
            .list(userId=self._user_id, q=SEARCH_QUERY, maxResults=PREVIOUS_EMAIL_LIMIT)
            .execute()
        )
        messages = listing.get("messages") or []
        if not messages:
            return empty_state()
        states = [self._state_from_message(message["id"]) for message in messages]
        return merge_previous_states(states)

    def _state_from_message(self, message_id: str) -> PreviousState:
        message = (
            self._service.users()
            .messages()
            .get(userId=self._user_id, id=message_id, format="full")
            .execute()
        )
        part = _find_named_part(message.get("payload") or {}, STATE_FILENAME)
        if part is None:
            logger.warning("job-explorer email %s has no %s attachment", message_id, STATE_FILENAME)
            return empty_state()
        raw = self._part_bytes(message_id, part)
        if not raw:
            logger.warning("job-explorer email %s has no %s attachment", message_id, STATE_FILENAME)
            return empty_state()
        try:
            decoded = base64.urlsafe_b64decode(raw + "===")
        except (ValueError, TypeError) as exc:
            logger.warning("ignoring undecodable state attachment: %s", exc)
            return empty_state()
        return decode_state(decoded)

    def send_raw(self, mime_bytes: bytes) -> None:
        encoded = base64.urlsafe_b64encode(mime_bytes).decode("ascii")
        self._service.users().messages().send(userId=self._user_id, body={"raw": encoded}).execute()

    def _part_bytes(self, message_id: str, part: dict[str, Any]) -> str | None:
        body = part.get("body") or {}
        data = body.get("data")
        if data:
            return data
        attachment_id = body.get("attachmentId")
        if not attachment_id:
            return None
        attachment = (
            self._service.users()
            .messages()
            .attachments()
            .get(userId=self._user_id, messageId=message_id, id=attachment_id)
            .execute()
        )
        return attachment.get("data")


def _find_named_part(payload: dict[str, Any], filename: str) -> dict[str, Any] | None:
    if _part_name(payload) == filename:
        return payload
    for part in payload.get("parts") or []:
        found = _find_named_part(part, filename)
        if found is not None:
            return found
    return None


def _part_name(payload: dict[str, Any]) -> str:
    name = (payload.get("filename") or "").strip()
    if name:
        return name.split("/")[-1].strip().strip('"')
    for header in payload.get("headers") or []:
        if (header.get("name") or "").lower() != "content-disposition":
            continue
        match = FILENAME_RE.search(header.get("value") or "")
        if match:
            return match.group(1).split("/")[-1].strip().strip('"')
    return ""
