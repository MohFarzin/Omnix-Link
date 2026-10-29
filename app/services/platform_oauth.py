"""Product OAuth for YouTube / Twitch / Kick — handoff to StreamRelay only."""

from __future__ import annotations

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
TWITCH_SCOPES = "chat:read chat:edit user:read:email channel:read:stream_key"
KICK_SCOPES = "user:read channel:read chat:write"


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


def kick_auth_url(state: str) -> str:
    s = get_settings()
    q = urlencode(
        {
            "client_id": s.kick_client_id,
            "redirect_uri": f"{_app_url()}/oauth/kick/callback",
            "response_type": "code",
            "scope": KICK_SCOPES,
            "state": state,
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
        body["_extra"] = {"channel": u.get("login") or "", "user_id": u.get("id") or ""}
        return body


async def exchange_kick(code: str) -> dict:
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
            },
        )
        body = res.json()
        if res.status_code >= 400 or "access_token" not in body:
            raise RuntimeError(body.get("error") or "Kick token failed")
        body["_extra"] = {}
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
