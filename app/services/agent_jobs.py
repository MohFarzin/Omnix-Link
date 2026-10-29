"""Outbound job queue — StreamRelay eggs pull encrypted jobs (no public egg URL)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .tunnel_crypto import seal


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_jobs(relay) -> list[dict]:
    try:
        data = json.loads(relay.job_queue_json or "[]")
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def save_jobs(relay, jobs: list[dict]) -> None:
    relay.job_queue_json = json.dumps(jobs)


def _enqueue(relay, inner: dict) -> str:
    job_id = str(uuid.uuid4())
    inner = {**inner, "jobId": job_id, "createdAt": _utcnow().isoformat()}
    jobs = load_jobs(relay)
    jobs.append(
        {
            "id": job_id,
            "sealed": seal(relay.tunnel_token, inner),
            "createdAt": inner["createdAt"],
        }
    )
    save_jobs(relay, jobs)
    return job_id


def enqueue_deliver_tokens(
    relay,
    *,
    platform: str,
    access_token: str,
    refresh_token: str | None,
    expires_in: int | None,
    extra: dict | None,
) -> str:
    return _enqueue(
        relay,
        {
            "type": "deliver_tokens",
            "platform": platform,
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresIn": expires_in,
            "extra": extra or {},
        },
    )


def enqueue_revoke_tokens(relay, *, platform: str) -> str:
    return _enqueue(relay, {"type": "revoke_tokens", "platform": platform})


def take_jobs(relay, limit: int = 8) -> list[dict]:
    jobs = load_jobs(relay)
    if not jobs:
        return []
    batch = jobs[:limit]
    return [{"id": j["id"], "sealed": j["sealed"]} for j in batch]


def ack_jobs(relay, job_ids: list[str]) -> None:
    if not job_ids:
        return
    wanted = set(job_ids)
    save_jobs(relay, [j for j in load_jobs(relay) if j.get("id") not in wanted])
