# Omnix Link (Relay Link)

Optional companion site for [Omnix StreamRelay](https://github.com/MohFarzin/Omnix-StreamRelay).

Public site: **https://relaylink.omnixstudio.xyz**  
Repo: **https://github.com/MohFarzin/Omnix-Link**

## What it does

1. You sign up (email, Google, or Discord)
2. Omnix Link creates a **tunnel token** (~56 characters)
3. You paste that token into your StreamRelay panel
4. Your egg **connects out** to Omnix Link (works behind CGNAT / phone hotspot — no public IP on your side)
5. You confirm the connection (IP, Discord/Google status) on this site
6. Connect YouTube / Twitch / Kick here; tokens are handed off **encrypted (AES-256-GCM)** for your egg to pull

Default StreamRelay path remains local Connect (tokens never leave your machine). Omnix Link is optional.

This is **not** called a “broker” in product language — it is **Omnix Link** / **Relay Link**.

## Layout (Pterodactyl Python egg)

```
/home/container/
  app.py              ← egg runs: python /home/container/app.py
  requirements.txt
  app/                ← FastAPI package
  .env                ← secrets (never commit)
  data/               ← sqlite (runtime)
```

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# fill SECRET_KEY, APP_URL, and OAuth client IDs
python app.py
```

## Agent API (egg → Link)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/agent/hello` | Present tunnel token; enter `pending_confirm` |
| POST | `/api/v1/agent/poll` | Heartbeat + pull sealed token jobs |

Jobs use AES-256-GCM keyed by the tunnel token (plus HTTPS in transit).

## Production

Deploy behind HTTPS (`APP_URL=https://relaylink.omnixstudio.xyz`). Set Google/Discord login + YouTube/Twitch/Kick Connect client credentials in `.env`.
