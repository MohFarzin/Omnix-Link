from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    google_sub: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    discord_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    relays: Mapped[list[Relay]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Relay(Base):
    __tablename__ = "relays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120))
    # Legacy inbound push (optional). Preferred: egg dials out with tunnel_token.
    base_url: Mapped[str] = mapped_column(String(512), default="")
    pairing_code: Mapped[str] = mapped_column(String(128), default="")
    tunnel_token: Mapped[str] = mapped_column(String(96), unique=True, index=True, default="")
    link_status: Mapped[str] = mapped_column(String(32), default="waiting")
    # waiting | pending_confirm | linked | rejected
    pending_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_ua: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pending_node_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pending_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    linked_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    job_queue_json: Mapped[str] = mapped_column(Text, default="[]")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_push_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    platforms_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped[User] = relationship(back_populates="relays")

    @property
    def platforms(self) -> dict:
        try:
            return json.loads(self.platforms_json or "{}")
        except json.JSONDecodeError:
            return {}

    def set_platform(self, name: str, connected: bool) -> None:
        data = self.platforms
        data[name] = {"connected": connected, "at": _utcnow().isoformat()}
        self.platforms_json = json.dumps(data)


engine = None
SessionLocal = None


def _migrate_sqlite(eng) -> None:
    with eng.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(relays)")).fetchall()}
        alters = {
            "tunnel_token": "ALTER TABLE relays ADD COLUMN tunnel_token VARCHAR(96) DEFAULT ''",
            "link_status": "ALTER TABLE relays ADD COLUMN link_status VARCHAR(32) DEFAULT 'waiting'",
            "pending_ip": "ALTER TABLE relays ADD COLUMN pending_ip VARCHAR(64)",
            "pending_ua": "ALTER TABLE relays ADD COLUMN pending_ua VARCHAR(512)",
            "pending_node_name": "ALTER TABLE relays ADD COLUMN pending_node_name VARCHAR(120)",
            "pending_version": "ALTER TABLE relays ADD COLUMN pending_version VARCHAR(64)",
            "pending_at": "ALTER TABLE relays ADD COLUMN pending_at DATETIME",
            "last_seen_at": "ALTER TABLE relays ADD COLUMN last_seen_at DATETIME",
            "linked_ip": "ALTER TABLE relays ADD COLUMN linked_ip VARCHAR(64)",
            "job_queue_json": "ALTER TABLE relays ADD COLUMN job_queue_json TEXT DEFAULT '[]'",
        }
        for name, sql in alters.items():
            if name not in cols:
                conn.execute(text(sql))


def init_db() -> None:
    global engine, SessionLocal
    settings = get_settings()
    data_dir = Path(__file__).resolve().parents[1] / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    url = settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    if url.startswith("sqlite"):
        _migrate_sqlite(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
