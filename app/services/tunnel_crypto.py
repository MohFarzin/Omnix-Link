"""AES-256-GCM envelopes keyed by the tunnel token (extra layer on top of HTTPS)."""

from __future__ import annotations

import base64
import hashlib
import json
import os


def derive_key(tunnel_token: str) -> bytes:
    return hashlib.sha256(f"omnix-relay-link:v1:{tunnel_token}".encode("utf-8")).digest()


def seal(tunnel_token: str, payload: dict) -> str:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as e:
        raise RuntimeError("cryptography package required") from e
    key = derive_key(tunnel_token)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, json.dumps(payload, separators=(",", ":")).encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ct).decode("ascii").rstrip("=")


def unseal(tunnel_token: str, blob: str) -> dict:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as e:
        raise RuntimeError("cryptography package required") from e
    pad = "=" * (-len(blob) % 4)
    raw = base64.urlsafe_b64decode((blob + pad).encode("ascii"))
    if len(raw) < 13:
        raise ValueError("ciphertext too short")
    nonce, ct = raw[:12], raw[12:]
    pt = AESGCM(derive_key(tunnel_token)).decrypt(nonce, ct, None)
    return json.loads(pt.decode("utf-8"))


def new_tunnel_token() -> str:
    """~56 char URL-safe token."""
    return base64.urlsafe_b64encode(os.urandom(42)).decode("ascii").rstrip("=")
