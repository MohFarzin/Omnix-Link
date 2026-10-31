"""Product OAuth for YouTube / Twitch / Kick — handoff to StreamRelay only."""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx

from ..config import get_settings

YT_SCOPES = " ".join(
    [
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.force-ssl",
        "https://www.googleapis.com/auth/youtube.upload",
    ]
)
# channel:manage:broadcast required for Helix PATCH /channels (Live Manager titles/game)
TWITCH_SCOPES = (
    "chat:read chat:edit user:read:email channel:read:stream_key channel:manage:broadcast"
)
# Must match Kick app checkboxes: user + channel + stream key + chat send
KICK_SCOPES = "user:read channel:read channel:write streamkey:read chat:write"


def make_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for Kick OAuth 2.1 S256."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _app_url() -> str:
    return get_settings().app_url.rstrip("/")


def _youtube_client() -> tuple[str, str]:
    s = get_settings()
    cid = s.youtube_client_id or s.google_client_id
    secret = s.youtube_client_secret or s.google_client_secret
    return cid, secret


def youtube_auth_url(state: str) -> str:
    cid, _ = _youtube_client()
    q = urlencode(
        {
            "client_id": cid,
            "redirect_uri": f"{_app_url()}/oauth/youtube/callback",
            "response_type": "code",
            "scope": YT_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{q}"


def twitch_auth_url(state: str) -> str:
    s = get_settings()
    q = urlencode(
        {
            "client_id": s.twitch_client_id,
            "redirect_uri": f"{_app_url()}/oauth/twitch/callback",
            "response_type": "code",
            "scope": TWITCH_SCOPES,
            "state": state,
            "force_verify": "true",
        }
    )
    return f"https://id.twitch.tv/oauth2/authorize?{q}"


def kick_auth_url(state: str, code_challenge: str) -> str:
    s = get_settings()
    q = urlencode(
        {
            "client_id": s.kick_client_id,
            "redirect_uri": f"{_app_url()}/oauth/kick/callback",
            "response_type": "code",
            "scope": KICK_SCOPES,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"https://id.kick.com/oauth/authorize?{q}"


async def exchange_youtube(code: str) -> dict:
    cid, secret = _youtube_client()
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": cid,
                "client_secret": secret,
                "redirect_uri": f"{_app_url()}/oauth/youtube/callback",
                "grant_type": "authorization_code",
            },
        )
        body = res.json()
        if res.status_code >= 400 or "access_token" not in body:
            raise RuntimeError(body.get("error_description") or body.get("error") or "YouTube token failed")
        return body


async def exchange_twitch(code: str) -> dict:
    s = get_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": s.twitch_client_id,
                "client_secret": s.twitch_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": f"{_app_url()}/oauth/twitch/callback",
            },
        )
        body = res.json()
        if res.status_code >= 400 or "access_token" not in body:
            raise RuntimeError(body.get("message") or "Twitch token failed")
        user = await client.get(
            "https://api.twitch.tv/helix/users",
            headers={
                "Authorization": f"Bearer {body['access_token']}",
                "Client-Id": s.twitch_client_id,
            },
        )
        u = (user.json().get("data") or [{}])[0]
        extra = {
            "channel": u.get("login") or "",
            "user_id": u.get("id") or "",
            "client_id": s.twitch_client_id or "",
        }
        # Fetch stream key on Link so the egg does not need TWITCH_CLIENT_ID
        try:
            uid = u.get("id") or ""
            if uid:
                key_res = await client.get(
                    f"https://api.twitch.tv/helix/streams/key?broadcaster_id={uid}",
                    headers={
                        "Authorization": f"Bearer {body['access_token']}",
                        "Client-Id": s.twitch_client_id,
                    },
                )
                if key_res.status_code < 400:
                    sk = ((key_res.json().get("data") or [{}])[0]).get("stream_key") or ""
                    if sk:
                        extra["stream_key"] = sk
                        extra["rtmp_url"] = "rtmp://live.twitch.tv/app"
        except Exception:
            pass
        body["_extra"] = extra
        return body


async def exchange_kick(code: str, code_verifier: str) -> dict:
    s = get_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(
            "https://id.kick.com/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": s.kick_client_id,
                "client_secret": s.kick_client_secret,
                "redirect_uri": f"{_app_url()}/oauth/kick/callback",
                "code": code,
                "code_verifier": code_verifier,
            },
        )
        body = res.json()
        if res.status_code >= 400 or "access_token" not in body:
            raise RuntimeError(body.get("error") or body.get("message") or "Kick token failed")
        extra: dict = {}
        headers = {
            "Authorization": f"Bearer {body['access_token']}",
            "Accept": "application/json",
        }
        try:
            me = await client.get("https://api.kick.com/public/v1/users", headers=headers)
            if me.status_code < 400:
                data = (me.json().get("data") or [{}])[0]
                extra = {
                    "channel": data.get("name") or data.get("username") or "",
                    "user_id": str(data.get("user_id") or data.get("id") or ""),
                }
        except Exception:
            pass
        # streamkey:read — key lives on channel.stream (or dedicated stream-key routes)
        try:
            ch = await client.get("https://api.kick.com/public/v1/channels", headers=headers)
            if ch.status_code < 400:
                row = (ch.json().get("data") or [{}])[0]
                stream = row.get("stream") or {}
                sk = stream.get("key") or stream.get("stream_key") or ""
                url = stream.get("url") or stream.get("rtmp_url") or ""
                if sk:
                    extra["stream_key"] = sk
                    if url:
                        extra["rtmp_url"] = url
            if "stream_key" not in extra:
                for path in ("/public/v1/stream-key", "/public/v1/streamkey"):
                    sk_res = await client.get(f"https://api.kick.com{path}", headers=headers)
                    if sk_res.status_code >= 400:
                        continue
                    payload = sk_res.json().get("data")
                    row = payload[0] if isinstance(payload, list) else (payload or {})
                    sk = row.get("stream_key") or row.get("key") or ""
                    url = row.get("rtmp_url") or row.get("url") or ""
                    if sk:
                        extra["stream_key"] = sk
                        if url:
                            extra["rtmp_url"] = url
                        break
        except Exception:
            pass
        body["_extra"] = extra
        return body


def login_google_url(state: str) -> str:
    s = get_settings()
    q = urlencode(
        {
            "client_id": s.google_client_id,
            "redirect_uri": f"{_app_url()}/auth/google/callback",
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{q}"


async def exchange_login_google(code: str) -> dict:
    s = get_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        tok = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "redirect_uri": f"{_app_url()}/auth/google/callback",
                "grant_type": "authorization_code",
            },
        )
        body = tok.json()
        if tok.status_code >= 400 or "access_token" not in body:
            raise RuntimeError(body.get("error_description") or "Google login failed")
        info = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        return info.json()


def login_discord_url(state: str) -> str:
    s = get_settings()
    q = urlencode(
        {
            "client_id": s.discord_client_id,
            "redirect_uri": f"{_app_url()}/auth/discord/callback",
            "response_type": "code",
            "scope": "identify email",
            "state": state,
        }
    )
    return f"https://discord.com/api/oauth2/authorize?{q}"


async def exchange_login_discord(code: str) -> dict:
    s = get_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        tok = await client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": s.discord_client_id,
                "client_secret": s.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{_app_url()}/auth/discord/callback",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        body = tok.json()
        if tok.status_code >= 400 or "access_token" not in body:
            raise RuntimeError(body.get("error_description") or "Discord login failed")
        me = await client.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        return me.json()
