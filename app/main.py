from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .config import get_settings
from .db import Relay, User, get_db, init_db
from .security import (
    dump_oauth_state,
    dump_session,
    hash_password,
    load_oauth_state,
    load_session,
    verify_password,
)
from .services import agent_jobs
from .services import platform_oauth as poauth
from .services.tunnel_crypto import new_tunnel_token

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

app = FastAPI(title="Omnix Link")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def render(request: Request, name: str, **ctx):
    """Starlette 0.40+ wants (request, name, context)."""
    ctx.setdefault("settings", get_settings())
    return templates.TemplateResponse(request, name, ctx)


@app.on_event("startup")
def _startup() -> None:
    import os

    init_db()
    settings = get_settings()
    port = os.environ.get("SERVER_PORT") or os.environ.get("PORT") or "8080"
    dash = (settings.app_url or "").strip().rstrip("/") or f"http://0.0.0.0:{port}"
    # "Server is running" must appear — python-generic egg done-detect looks for that substring
    print("==========================================", flush=True)
    print(" Omnix Link", flush=True)
    print(" Server is running", flush=True)
    print(f" Dashboard:      {dash}", flush=True)
    print("==========================================", flush=True)


def current_user(request: Request, db: Session) -> User | None:
    uid = load_session(request.cookies.get("omnix_link"))
    if not uid:
        return None
    return db.get(User, uid)


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = current_user(request, db)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def set_login_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        "omnix_link",
        dump_session(user_id),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user:
        return RedirectResponse("/app", status_code=303)
    return render(request, "landing.html", user=None)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return RedirectResponse("/app", status_code=303)
    s = get_settings()
    return render(
        request,
        "login.html",
        user=None,
        error=None,
        google_ready=bool(s.google_client_id and s.google_client_secret),
        discord_ready=bool(s.discord_client_id and s.discord_client_secret),
    )


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return RedirectResponse("/app", status_code=303)
    return render(request, "register.html", user=None, error=None)


@app.post("/register")
def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    if len(password) < 8:
        resp = render(request, "register.html", user=None, error="Password must be at least 8 characters.")
        resp.status_code = 400
        return resp
    if db.query(User).filter(User.email == email).first():
        resp = render(request, "register.html", user=None, error="Email already registered. Log in instead.")
        resp.status_code = 400
        return resp
    user = User(email=email, password_hash=hash_password(password), display_name=name.strip() or email.split("@")[0])
    db.add(user)
    db.commit()
    resp = RedirectResponse("/app", status_code=303)
    set_login_cookie(resp, user.id)
    return resp


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    s = get_settings()
    if not user or not verify_password(password, user.password_hash):
        resp = render(
            request,
            "login.html",
            user=None,
            error="Invalid email or password.",
            google_ready=bool(s.google_client_id and s.google_client_secret),
            discord_ready=bool(s.discord_client_id and s.discord_client_secret),
        )
        resp.status_code = 400
        return resp
    resp = RedirectResponse("/app", status_code=303)
    set_login_cookie(resp, user.id)
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("omnix_link")
    return resp


@app.get("/auth/google/start")
def auth_google_start():
    s = get_settings()
    if not (s.google_client_id and s.google_client_secret):
        raise HTTPException(400, "Google login not configured")
    state = dump_oauth_state({"kind": "login_google"})
    return RedirectResponse(poauth.login_google_url(state), status_code=303)


@app.get("/auth/google/callback")
async def auth_google_callback(code: str = "", state: str = "", db: Session = Depends(get_db)):
    try:
        load_oauth_state(state)
        info = await poauth.exchange_login_google(code)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    email = (info.get("email") or "").lower()
    sub = info.get("sub")
    if not email or not sub:
        raise HTTPException(400, "Google did not return email")
    user = db.query(User).filter((User.google_sub == sub) | (User.email == email)).first()
    if not user:
        user = User(
            email=email,
            google_sub=sub,
            display_name=info.get("name") or email.split("@")[0],
            password_hash=None,
        )
        db.add(user)
    else:
        user.google_sub = sub
        if not user.display_name:
            user.display_name = info.get("name") or user.display_name
    db.commit()
    resp = RedirectResponse("/app", status_code=303)
    set_login_cookie(resp, user.id)
    return resp


@app.get("/auth/discord/start")
def auth_discord_start():
    s = get_settings()
    if not (s.discord_client_id and s.discord_client_secret):
        raise HTTPException(400, "Discord login not configured")
    state = dump_oauth_state({"kind": "login_discord"})
    return RedirectResponse(poauth.login_discord_url(state), status_code=303)


@app.get("/auth/discord/callback")
async def auth_discord_callback(code: str = "", state: str = "", db: Session = Depends(get_db)):
    try:
        load_oauth_state(state)
        info = await poauth.exchange_login_discord(code)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    did = str(info.get("id") or "")
    email = (info.get("email") or f"discord_{did}@users.omnix.link").lower()
    if not did:
        raise HTTPException(400, "Discord did not return user id")
    user = db.query(User).filter((User.discord_id == did) | (User.email == email)).first()
    if not user:
        user = User(
            email=email,
            discord_id=did,
            display_name=info.get("global_name") or info.get("username") or "Discord user",
            password_hash=None,
        )
        db.add(user)
    else:
        user.discord_id = did
    db.commit()
    resp = RedirectResponse("/app", status_code=303)
    set_login_cookie(resp, user.id)
    return resp


@app.get("/app", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    relays = db.query(Relay).filter(Relay.user_id == user.id).order_by(Relay.id.desc()).all()
    if len(relays) == 1:
        return RedirectResponse(f"/app/relays/{relays[0].id}", status_code=303)
    flash = request.query_params.get("msg")
    err = request.query_params.get("err")
    return render(
        request,
        "dashboard.html",
        user=user,
        relays=relays,
        flash=flash,
        error=err,
        can_connect=len(relays) == 0,
    )


@app.post("/app/relays")
async def add_relay(
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    existing = db.query(Relay).filter(Relay.user_id == user.id).first()
    if existing:
        return RedirectResponse(
            f"/app/relays/{existing.id}?err=Only+one+relay+per+account",
            status_code=303,
        )
    token = new_tunnel_token()
    relay = Relay(
        user_id=user.id,
        name="My StreamRelay",
        base_url="",
        pairing_code="",
        tunnel_token=token,
        link_status="waiting",
        verified=False,
    )
    db.add(relay)
    db.commit()
    return RedirectResponse(
        f"/app/relays/{relay.id}?msg=Paste+this+token+into+StreamRelay+then+wait+for+confirm",
        status_code=303,
    )


@app.post("/app/relays/{relay_id}/confirm")
def confirm_relay(relay_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    relay = db.get(Relay, relay_id)
    if not relay or relay.user_id != user.id:
        raise HTTPException(404)
    if relay.link_status != "pending_confirm":
        return RedirectResponse(f"/app/relays/{relay_id}?err=Nothing+to+confirm", status_code=303)
    relay.link_status = "linked"
    relay.verified = True
    relay.linked_ip = relay.pending_ip
    if relay.pending_node_name:
        relay.name = relay.pending_node_name[:120]
    db.commit()
    return RedirectResponse(f"/app/relays/{relay_id}?msg=Relay+connected", status_code=303)


@app.post("/app/relays/{relay_id}/reject")
def reject_relay(relay_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    relay = db.get(Relay, relay_id)
    if not relay or relay.user_id != user.id:
        raise HTTPException(404)
    relay.link_status = "rejected"
    relay.pending_ip = None
    relay.pending_ua = None
    relay.pending_node_name = None
    relay.pending_version = None
    relay.pending_at = None
    db.commit()
    return RedirectResponse(f"/app/relays/{relay_id}?msg=Connection+rejected", status_code=303)


@app.post("/app/relays/{relay_id}/rotate-token")
def rotate_token(relay_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    relay = db.get(Relay, relay_id)
    if not relay or relay.user_id != user.id:
        raise HTTPException(404)
    relay.tunnel_token = new_tunnel_token()
    relay.link_status = "waiting"
    relay.verified = False
    relay.pending_ip = None
    relay.linked_ip = None
    agent_jobs.save_jobs(relay, [])
    db.commit()
    return RedirectResponse(f"/app/relays/{relay_id}?msg=New+tunnel+token+-+paste+into+StreamRelay", status_code=303)


@app.get("/app/relays/{relay_id}", response_class=HTMLResponse)
def relay_detail(relay_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    relay = db.get(Relay, relay_id)
    if not relay or relay.user_id != user.id:
        raise HTTPException(404)
    s = get_settings()
    return render(
        request,
        "relay.html",
        user=user,
        relay=relay,
        flash=request.query_params.get("msg"),
        error=request.query_params.get("err"),
        yt_ready=bool((s.youtube_client_id or s.google_client_id) and (s.youtube_client_secret or s.google_client_secret)),
        twitch_ready=bool(s.twitch_client_id and s.twitch_client_secret),
        kick_ready=bool(s.kick_client_id and s.kick_client_secret),
        discord_linked=bool(user.discord_id),
        google_linked=bool(user.google_sub),
    )


@app.post("/app/relays/{relay_id}/delete")
def delete_relay(relay_id: int, request: Request, db: Session = Depends(get_db)):
    """One relay per account — public users cannot delete to free the slot."""
    _ = (relay_id, request, db)
    return RedirectResponse("/app?err=Relay+cannot+be+removed+-+one+per+account", status_code=303)


@app.post("/app/relays/{relay_id}/disconnect/{platform}")
def disconnect_platform(relay_id: int, platform: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    relay = db.get(Relay, relay_id)
    if not relay or relay.user_id != user.id:
        raise HTTPException(404)
    platform = platform.lower()
    if platform not in ("youtube", "twitch", "kick"):
        raise HTTPException(400, "unknown platform")
    if relay.link_status == "linked" and relay.tunnel_token:
        try:
            agent_jobs.enqueue_revoke_tokens(relay, platform=platform)
        except Exception as e:
            return RedirectResponse(f"/app/relays/{relay_id}?err={str(e)[:120]}", status_code=303)
    relay.set_platform(platform, False)
    db.commit()
    return RedirectResponse(f"/app/relays/{relay_id}?msg={platform}+access+removed", status_code=303)


@app.get("/app/relays/{relay_id}/connect/{platform}")
def connect_start(relay_id: int, platform: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    relay = db.get(Relay, relay_id)
    if not relay or relay.user_id != user.id:
        raise HTTPException(404)
    platform = platform.lower()
    if platform == "youtube":
        s0 = get_settings()
        if not ((s0.youtube_client_id or s0.google_client_id) and (s0.youtube_client_secret or s0.google_client_secret)):
            return RedirectResponse(f"/app/relays/{relay_id}?err=YouTube+not+configured", status_code=303)
        state = dump_oauth_state({"kind": "platform", "platform": platform, "relay_id": relay.id, "uid": user.id})
        return RedirectResponse(poauth.youtube_auth_url(state), status_code=303)
    if platform == "twitch":
        if not get_settings().twitch_client_id:
            return RedirectResponse(f"/app/relays/{relay_id}?err=Twitch+not+configured", status_code=303)
        state = dump_oauth_state({"kind": "platform", "platform": platform, "relay_id": relay.id, "uid": user.id})
        return RedirectResponse(poauth.twitch_auth_url(state), status_code=303)
    if platform == "kick":
        if not get_settings().kick_client_id:
            return RedirectResponse(f"/app/relays/{relay_id}?err=Kick+not+configured", status_code=303)
        verifier, challenge = poauth.make_pkce()
        state = dump_oauth_state(
            {
                "kind": "platform",
                "platform": platform,
                "relay_id": relay.id,
                "uid": user.id,
                "code_verifier": verifier,
            }
        )
        return RedirectResponse(poauth.kick_auth_url(state, challenge), status_code=303)
    raise HTTPException(400, "unknown platform")


async def _finish_platform(request: Request, platform: str, code: str, state: str, db: Session):
    try:
        payload = load_oauth_state(state)
    except Exception as e:
        raise HTTPException(400, f"Invalid state: {e}") from e
    if payload.get("kind") != "platform" or payload.get("platform") != platform:
        raise HTTPException(400, "State mismatch")
    user = current_user(request, db)
    if not user or user.id != payload.get("uid"):
        raise HTTPException(401, "Login required")
    relay = db.get(Relay, int(payload["relay_id"]))
    if not relay or relay.user_id != user.id:
        raise HTTPException(404)

    if platform == "youtube":
        body = await poauth.exchange_youtube(code)
        extra = {}
    elif platform == "twitch":
        body = await poauth.exchange_twitch(code)
        extra = body.pop("_extra", {})
    else:
        verifier = str(payload.get("code_verifier") or "")
        if not verifier:
            raise HTTPException(400, "Kick PKCE verifier missing — try Connect Kick again")
        body = await poauth.exchange_kick(code, verifier)
        extra = body.pop("_extra", {})

    if relay.link_status != "linked" or not relay.tunnel_token:
        return RedirectResponse(
            f"/app/relays/{relay.id}?err=Relay+not+linked+yet+-+confirm+the+egg+connection+first",
            status_code=303,
        )
    try:
        agent_jobs.enqueue_deliver_tokens(
            relay,
            platform=platform,
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            expires_in=body.get("expires_in"),
            extra=extra,
        )
    except Exception as e:
        return RedirectResponse(f"/app/relays/{relay.id}?err={str(e)[:140]}", status_code=303)

    relay.set_platform(platform, True)
    relay.last_push_at = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse(
        f"/app/relays/{relay.id}?msg={platform}+connected+-+encrypted+handoff+queued+for+your+egg",
        status_code=303,
    )


@app.get("/oauth/youtube/callback")
async def yt_cb(request: Request, code: str = "", state: str = "", db: Session = Depends(get_db)):
    return await _finish_platform(request, "youtube", code, state, db)


@app.get("/oauth/twitch/callback")
async def tw_cb(request: Request, code: str = "", state: str = "", db: Session = Depends(get_db)):
    return await _finish_platform(request, "twitch", code, state, db)


@app.get("/oauth/kick/callback")
async def kick_cb(request: Request, code: str = "", state: str = "", db: Session = Depends(get_db)):
    return await _finish_platform(request, "kick", code, state, db)


@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request, db: Session = Depends(get_db)):
    return render(request, "privacy.html", user=current_user(request, db))


@app.get("/terms", response_class=HTMLResponse)
def terms(request: Request, db: Session = Depends(get_db)):
    return render(request, "terms.html", user=current_user(request, db))


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class AgentHelloBody(BaseModel):
    tunnelToken: str = Field(min_length=16)
    nodeName: str = ""
    version: str = ""


class AgentPollBody(BaseModel):
    tunnelToken: str = Field(min_length=16)
    ackJobIds: list[str] = Field(default_factory=list)


def _relay_by_token(db: Session, token: str) -> Relay | None:
    return db.query(Relay).filter(Relay.tunnel_token == token.strip()).first()


@app.post("/api/v1/agent/hello")
def agent_hello(body: AgentHelloBody, request: Request, db: Session = Depends(get_db)):
    """Egg dials out — no public URL required on the StreamRelay side."""
    relay = _relay_by_token(db, body.tunnelToken)
    if not relay:
        raise HTTPException(401, "Invalid tunnel token")
    ip = _client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:500]
    now = datetime.now(timezone.utc)
    relay.last_seen_at = now
    if relay.link_status == "linked" and relay.linked_ip and relay.linked_ip != ip:
        # Same token, new IP — ask owner to re-confirm
        relay.link_status = "pending_confirm"
        relay.verified = False
    if relay.link_status in ("waiting", "rejected", "pending_confirm") or not relay.verified:
        relay.link_status = "pending_confirm"
        relay.pending_ip = ip
        relay.pending_ua = ua
        relay.pending_node_name = (body.nodeName or "")[:120]
        relay.pending_version = (body.version or "")[:64]
        relay.pending_at = now
    db.commit()
    owner = db.get(User, relay.user_id)
    return {
        "ok": True,
        "status": relay.link_status,
        "relayName": relay.name,
        "ownerEmailMasked": _mask_email(owner.email) if owner else None,
        "discordLinked": bool(owner and owner.discord_id),
        "googleLinked": bool(owner and owner.google_sub),
        "yourIp": ip,
        "message": (
            "Waiting for the Omnix Link owner to confirm this connection."
            if relay.link_status == "pending_confirm"
            else "Linked — keep polling for encrypted token handoffs."
            if relay.link_status == "linked"
            else relay.link_status
        ),
    }


@app.post("/api/v1/agent/poll")
def agent_poll(body: AgentPollBody, request: Request, db: Session = Depends(get_db)):
    relay = _relay_by_token(db, body.tunnelToken)
    if not relay:
        raise HTTPException(401, "Invalid tunnel token")
    relay.last_seen_at = datetime.now(timezone.utc)
    if body.ackJobIds:
        agent_jobs.ack_jobs(relay, body.ackJobIds)
    jobs: list[dict] = []
    if relay.link_status == "linked":
        jobs = agent_jobs.take_jobs(relay)
    db.commit()
    return {
        "ok": True,
        "status": relay.link_status,
        "relayName": relay.name,
        "jobs": jobs,
        "encrypt": "aes-256-gcm",
        "hint": "Unseal each job.sealed with the same tunnel token (AES-256-GCM).",
    }


def _mask_email(email: str) -> str:
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    keep = local[:2] if len(local) > 2 else local[:1]
    return f"{keep}***@{domain}"
