# Omnix Link

[![License: MIT](https://img.shields.io/badge/License-MIT-0B3D91.svg)](LICENSE)
[![Site](https://img.shields.io/badge/site-relaylink.omnixstudio.xyz-111111)](https://relaylink.omnixstudio.xyz)
[![Repo](https://img.shields.io/badge/GitHub-Omnix--Link-181717?logo=github)](https://github.com/MohFarzin/Omnix-Link)

Companion service for **[Omnix StreamRelay](https://github.com/MohFarzin/Omnix-StreamRelay)**. Sign in on the web, pair your egg with a tunnel token, Connect platforms here, and deliver sealed credentials to the node that dials **out** — no public URL required on the StreamRelay side.

| | |
|---|---|
| Product | Omnix Link · Relay Link |
| Live | [relaylink.omnixstudio.xyz](https://relaylink.omnixstudio.xyz) |
| Stack | FastAPI · SQLite · Pterodactyl Python egg |
| Contact | [admin@omnixstudio.xyz](mailto:admin@omnixstudio.xyz) |

StreamRelay already supports local Connect (tokens stay on the egg). Link is optional for operators who want web Connect while the panel sits behind CGNAT or a private network.

```
Streamer browser ──HTTPS──► Omnix Link
                               ▲
                               │ hello / poll (outbound)
                               │
                         StreamRelay egg
```

---

## Setup

### Use the hosted site

1. Open [relaylink.omnixstudio.xyz](https://relaylink.omnixstudio.xyz) and sign in (email, Google, or Discord).
2. Copy the **tunnel token** from your Link account.
3. In the StreamRelay panel, paste the token under Omnix Link / Relay Link and save.
4. Confirm the pending connection on Link (shown IP / account status).
5. **Connect** YouTube / Twitch / Kick on Link. The egg pulls sealed jobs on its next poll.

### Run your own instance

```bash
git clone https://github.com/MohFarzin/Omnix-Link.git
cd Omnix-Link
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Fill at least:

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Long random secret |
| `APP_URL` | Public HTTPS origin (e.g. `https://relaylink.example.com`) |
| `GOOGLE_*` / `DISCORD_*` | Site login clients |
| `YOUTUBE_*` / `TWITCH_*` / `KICK_*` | Platform Connect clients (handoff only) |

```bash
python app.py
```

Panel: import [`egg-omnix-link.json`](egg-omnix-link.json), point `GIT_ADDRESS` at this repo (or upload files), set `PY_FILE=app.py`, allocate an HTTP port, place HTTPS in front ([Cloudflare notes](docs/CLOUDFLARE.md)).

### Environment sketch

```env
APP_NAME=Omnix Link
APP_URL=https://relaylink.omnixstudio.xyz
SECRET_KEY=…
DATABASE_URL=sqlite:///./data/omnix_link.sqlite
```

Never commit `.env`. Runtime data lands under `data/`.

---

## Reference

### Pairing model

1. Link mints a tunnel token for the signed-in owner.
2. The egg stores that token and opens outbound HTTPS to Link.
3. `POST /api/v1/agent/hello` presents the token → connection enters **pending confirm**.
4. The owner confirms on the site (IP / identity check).
5. Platform Connect on Link enqueues **AES-256-GCM** jobs keyed from the tunnel token.
6. `POST /api/v1/agent/poll` heartbeats and drains jobs; the egg decrypts and stores tokens locally.

Transit is HTTPS; payload sealing is independent of TLS. Revoking the tunnel token invalidates further pulls.

### Agent API

| Method | Path | Role |
|--------|------|------|
| `POST` | `/api/v1/agent/hello` | Register / refresh session with tunnel token |
| `POST` | `/api/v1/agent/poll` | Heartbeat · fetch sealed credential jobs |

### Repository

```
app.py                 Entrypoint (egg: python /home/container/app.py)
app/
  main.py              FastAPI application
  config.py            Settings from env
  db.py                SQLite access
  security.py          Auth helpers
  services/
    tunnel_crypto.py   AES-256-GCM seal / open
    agent_jobs.py      Outbound job queue
    platform_oauth.py  YouTube · Twitch · Kick Connect
    push.py            Delivery helpers
docs/                  Cloudflare · tunnel origin notes
egg-omnix-link.json    Pterodactyl / Jexactyl egg
requirements.txt
.env.example
```

Egg volume layout:

```
/home/container/
  app.py
  requirements.txt
  app/
  .env          # secrets — chmod 600
  data/         # sqlite
```

### Production checklist

- Serve only over HTTPS; set `APP_URL` to that origin.
- Terminate TLS at Cloudflare, Caddy, or nginx — egg ports alone are not enough behind orange-cloud DNS ([docs/CLOUDFLARE.md](docs/CLOUDFLARE.md), [docs/CLOUDFLARE-TUNNEL.md](docs/CLOUDFLARE-TUNNEL.md)).
- Separate OAuth apps for **site login** vs **platform Connect**.
- Keep StreamRelay and Link credentials isolated per operator; never copy tunnel tokens between nodes.

### Related

| Resource | |
|----------|--|
| [Omnix StreamRelay](https://github.com/MohFarzin/Omnix-StreamRelay) | Relay · dashboard · egg |
| [Connect platforms](https://github.com/MohFarzin/Omnix-StreamRelay/blob/main/docs/CONNECT-PLATFORMS.md) | Panel-side Connect |
| [Privacy: Connect](https://github.com/MohFarzin/Omnix-StreamRelay/blob/main/docs/PRIVACY-CONNECT.md) | Token custody |

---

## License

[MIT](LICENSE) · © 2026 OmnixStudio / MohFarzin · [admin@omnixstudio.xyz](mailto:admin@omnixstudio.xyz)
