"""Push platform tokens to a linked StreamRelay egg (one-shot handoff)."""

from __future__ import annotations

import httpx


async def verify_relay(base_url: str, pairing_code: str) -> dict:
    url = base_url.rstrip("/") + "/api/v1/oauth/link/verify"
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        res = await client.post(url, json={"pairingCode": pairing_code})
        data = res.json() if res.content else {}
        if res.status_code >= 400:
            raise RuntimeError(data.get("error") or f"verify failed ({res.status_code})")
        return data


async def push_tokens(
    base_url: str,
    pairing_code: str,
    platform: str,
    access_token: str,
    refresh_token: str | None,
    expires_in: int | None,
    extra: dict | None = None,
) -> dict:
    url = base_url.rstrip("/") + "/api/v1/oauth/link/push"
    body = {
        "pairingCode": pairing_code,
        "platform": platform,
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresIn": expires_in,
        "extra": extra or {},
    }
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        res = await client.post(url, json=body)
        data = res.json() if res.content else {}
        if res.status_code >= 400:
            raise RuntimeError(data.get("error") or f"push failed ({res.status_code})")
        return data
