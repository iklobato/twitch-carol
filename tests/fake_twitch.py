"""A stateful fake that plays the Twitch API for end-to-end tests.

Injected through the single core.twitch._http seam, it answers OAuth token
grants, Helix /users and /streams, and EventSub subscription management,
including calling BACK into the app with the signed webhook verification
challenge, exactly like real Twitch does. It also emits signed event
notifications into the app's webhook endpoint.
"""

import json
import secrets
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx

from core.eventsub import (
    HEADER_MESSAGE_ID,
    HEADER_MESSAGE_TYPE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    compute_signature,
)

FAKE_USER = {"id": "990077001", "login": "iklobat_fake", "display_name": "Iklobat Fake"}
TOKEN_TTL_SECONDS = 14400


class FakeTwitch:
    def __init__(self, webhook_client, eventsub_secret: str) -> None:
        self._webhook_client = webhook_client
        self._eventsub_secret = eventsub_secret
        self.user = dict(FAKE_USER)
        self.authorization_codes: set[str] = set()
        self.user_tokens: dict[str, str] = {}  # access token -> user id
        self.refresh_tokens: set[str] = set()
        self.app_tokens: set[str] = set()
        self.subscriptions: list[dict] = []
        self.stream_info: dict | None = None  # helix /streams payload for the user
        self.followers: list[dict] = []  # helix /channels/followers backfill
        self.user_profiles: dict[str, dict] = {}  # helix /users?id=... enrichment
        self.channel_infos: dict[str, dict] = {}  # helix /channels?broadcaster_id=...
        self.videos: list[dict] = []  # helix /videos backfill
        self.vips: list[dict] = []  # helix /channels/vips backfill
        self.goals: list[dict] = []  # helix /goals backfill
        self.subscriptions_list: list[dict] = []  # helix /subscriptions backfill
        self.bits_leaders: list[dict] = []  # helix /bits/leaderboard backfill
        self.client = httpx.Client(transport=httpx.MockTransport(self._handle))

    # --- consent / webhook emission helpers -------------------------------

    def authorize(self) -> str:
        """The 'user clicked Authorize' step: issues an authorization code."""
        code = secrets.token_hex(12)
        self.authorization_codes.add(code)
        return code

    def send_event(self, sub_type: str, event: dict, version: str = "1") -> int:
        body = json.dumps(
            {
                "subscription": {
                    "id": str(uuid.uuid4()),
                    "type": sub_type,
                    "version": version,
                },
                "event": event,
            }
        ).encode()
        return self._signed_post(body, "notification")

    def _send_challenge(self, subscription: dict) -> bool:
        challenge = secrets.token_hex(8)
        body = json.dumps(
            {"challenge": challenge, "subscription": subscription}
        ).encode()
        message_id = str(uuid.uuid4())
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        response = self._webhook_client.post(
            "/eventsub/callback",
            content=body,
            headers={
                HEADER_MESSAGE_ID: message_id,
                HEADER_TIMESTAMP: timestamp,
                HEADER_MESSAGE_TYPE: "webhook_callback_verification",
                HEADER_SIGNATURE: compute_signature(
                    self._eventsub_secret, message_id, timestamp, body
                ),
            },
        )
        return response.status_code == 200 and response.text == challenge

    def _signed_post(self, body: bytes, message_type: str) -> int:
        message_id = str(uuid.uuid4())
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        response = self._webhook_client.post(
            "/eventsub/callback",
            content=body,
            headers={
                HEADER_MESSAGE_ID: message_id,
                HEADER_TIMESTAMP: timestamp,
                HEADER_MESSAGE_TYPE: message_type,
                HEADER_SIGNATURE: compute_signature(
                    self._eventsub_secret, message_id, timestamp, body
                ),
            },
        )
        return response.status_code

    # --- the fake Twitch API ----------------------------------------------

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "id.twitch.tv" and path == "/oauth2/token":
            return self._handle_token(request)
        if path == "/helix/users":
            return self._handle_users(request)
        if path == "/helix/streams":
            data = [self.stream_info] if self.stream_info else []
            return httpx.Response(200, json={"data": data})
        if path == "/helix/channels":
            ids = request.url.params.get_list("broadcaster_id")
            data = [self.channel_infos[i] for i in ids if i in self.channel_infos]
            return httpx.Response(200, json={"data": data})
        if path == "/helix/channels/followers":
            return httpx.Response(200, json={"data": self.followers, "pagination": {}})
        if path == "/helix/videos":
            return httpx.Response(200, json={"data": self.videos})
        if path == "/helix/channels/vips":
            return httpx.Response(200, json={"data": self.vips, "pagination": {}})
        if path == "/helix/goals":
            return httpx.Response(200, json={"data": self.goals})
        if path == "/helix/subscriptions":
            return httpx.Response(
                200, json={"data": self.subscriptions_list, "pagination": {}}
            )
        if path == "/helix/bits/leaderboard":
            return httpx.Response(200, json={"data": self.bits_leaders})
        if path == "/helix/eventsub/subscriptions":
            if request.method == "GET":
                return httpx.Response(200, json={"data": self.subscriptions})
            return self._handle_subscribe(request)
        return httpx.Response(404, json={"error": f"unhandled fake route {path}"})

    def _issue_user_tokens(self) -> dict:
        access = f"acc-{secrets.token_hex(8)}"
        refresh = f"ref-{secrets.token_hex(8)}"
        self.user_tokens[access] = self.user["id"]
        self.refresh_tokens.add(refresh)
        from core.twitch import OAUTH_SCOPES

        return {
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": TOKEN_TTL_SECONDS,
            "scope": list(OAUTH_SCOPES),
        }

    def _handle_token(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        grant = form.get("grant_type")
        if grant == "authorization_code":
            if form.get("code") not in self.authorization_codes:
                return httpx.Response(
                    400, json={"message": "Invalid authorization code"}
                )
            self.authorization_codes.discard(form["code"])
            return httpx.Response(200, json=self._issue_user_tokens())
        if grant == "refresh_token":
            if form.get("refresh_token") not in self.refresh_tokens:
                return httpx.Response(401, json={"message": "Invalid refresh token"})
            self.refresh_tokens.discard(form["refresh_token"])
            return httpx.Response(200, json=self._issue_user_tokens())
        if grant == "client_credentials":
            token = f"app-{secrets.token_hex(8)}"
            self.app_tokens.add(token)
            return httpx.Response(
                200, json={"access_token": token, "expires_in": TOKEN_TTL_SECONDS}
            )
        return httpx.Response(400, json={"message": "unsupported grant"})

    def _handle_users(self, request: httpx.Request) -> httpx.Response:
        ids = request.url.params.get_list("id")
        if ids:
            # batch Get Users by id (follower enrichment), served from a map
            data = [self.user_profiles[i] for i in ids if i in self.user_profiles]
            return httpx.Response(200, json={"data": data})
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token not in self.user_tokens:
            return httpx.Response(401, json={"message": "invalid token"})
        return httpx.Response(200, json={"data": [self.user]})

    def _handle_subscribe(self, request: httpx.Request) -> httpx.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token not in self.app_tokens:
            return httpx.Response(401, json={"message": "app token required"})
        payload = json.loads(request.content)
        subscription = {
            "id": str(uuid.uuid4()),
            "type": payload["type"],
            "version": payload["version"],
            "condition": payload["condition"],
            "status": "webhook_callback_verification_pending",
        }
        if payload["transport"]["secret"] != self._eventsub_secret:
            return httpx.Response(400, json={"message": "secret mismatch"})
        # like real Twitch: verify the callback echoes the signed challenge
        subscription["status"] = (
            "enabled"
            if self._send_challenge(subscription)
            else "webhook_callback_verification_failed"
        )
        self.subscriptions.append(subscription)
        return httpx.Response(202, json={"data": [subscription]})


def http_seam(fake: FakeTwitch):
    """Drop-in replacement for core.twitch._http routing to the fake."""

    def _fake_http(client: httpx.Client | None):
        return nullcontext(fake.client)

    return _fake_http


def irc_line(channel_login: str, author: str, text: str, sent_at: datetime) -> str:
    tags = (
        f"badges=;display-name={author};emotes=;id={uuid.uuid4()};"
        f"tmi-sent-ts={int(sent_at.timestamp() * 1000)};user-id={abs(hash(author)) % 10_000_000}"
    )
    return f"@{tags} :{author}!{author}@{author}.tmi.twitch.tv PRIVMSG #{channel_login} :{text}"
