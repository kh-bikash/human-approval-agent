from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Request:
    id: str
    action: str
    payload: dict
    status: str
    created_at: float


class ApprovalStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, action TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, request_id TEXT NOT NULL, actor TEXT NOT NULL, event TEXT NOT NULL, at REAL NOT NULL)")
            if "expires_at" not in {row[1] for row in db.execute("PRAGMA table_info(requests)")}:
                db.execute("ALTER TABLE requests ADD COLUMN expires_at REAL")
            db.execute("CREATE TABLE IF NOT EXISTS request_keys(key TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES requests(id))")

    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def propose(self, action: str, payload: dict, *, confidence: float, threshold: float = 0.8,
                ttl_seconds: float = 86400, idempotency_key: str | None = None) -> Request:
        if not 0 <= confidence <= 1 or not 0 <= threshold <= 1:
            raise ValueError("confidence and threshold must be between 0 and 1")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        now, request_id = time.time(), str(uuid.uuid4())
        status = "approved" if confidence >= threshold else "pending"
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                old = db.execute("SELECT r.id,r.action,r.payload,r.status,r.created_at FROM request_keys k JOIN requests r ON r.id=k.request_id WHERE k.key=?", (idempotency_key,)).fetchone()
                if old:
                    if old[1] != action or old[2] != encoded:
                        raise ValueError("idempotency key reused with different request")
                    return Request(old[0], old[1], json.loads(old[2]), old[3], old[4])
            db.execute("INSERT INTO requests(id,action,payload,digest,status,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,?,?,?)", (request_id, action, encoded, hashlib.sha256(encoded.encode()).hexdigest(), status, now, now, now + ttl_seconds))
            if idempotency_key:
                db.execute("INSERT INTO request_keys(key,request_id) VALUES(?,?)", (idempotency_key, request_id))
            db.execute("INSERT INTO audit(request_id,actor,event,at) VALUES(?,?,?,?)", (request_id, "system", "proposed:" + status, now))
        return Request(request_id, action, payload, status, now)

    def decide(self, request_id: str, *, actor: str, approve: bool) -> str:
        if not actor.strip():
            raise ValueError("actor required")
        status = "approved" if approve else "rejected"
        with self._db() as db:
            now = time.time()
            expired = db.execute("UPDATE requests SET status='expired',updated_at=? WHERE id=? AND status='pending' AND expires_at<=?", (now, request_id, now)).rowcount
            updated = db.execute("UPDATE requests SET status=?,updated_at=? WHERE id=? AND status='pending' AND expires_at>?", (status, now, request_id, now)).rowcount
            if expired:
                db.execute("INSERT INTO audit(request_id,actor,event,at) VALUES(?,?,?,?)", (request_id, "system", "expired", now))
            if updated:
                db.execute("INSERT INTO audit(request_id,actor,event,at) VALUES(?,?,?,?)", (request_id, actor, status, now))
        if not updated:
            raise ValueError("request absent, expired, or already decided")
        return status

    def resume(self, request_id: str, *, executor: Callable[[str, dict], object]) -> object:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT action,payload,digest,status,expires_at FROM requests WHERE id=?", (request_id,)).fetchone()
            if row is None or row[3] != "approved" or row[4] <= time.time():
                raise PermissionError("request is not approved")
            action, encoded, digest, _, _expires_at = row
            if hashlib.sha256(encoded.encode()).hexdigest() != digest:
                raise ValueError("request payload changed")
            db.execute("UPDATE requests SET status='executing',updated_at=? WHERE id=?", (time.time(), request_id))
        try:
            result = executor(action, json.loads(encoded))
        except Exception:
            with self._db() as db:
                db.execute("UPDATE requests SET status='failed',updated_at=? WHERE id=?", (time.time(), request_id))
                db.execute("INSERT INTO audit(request_id,actor,event,at) VALUES(?,?,?,?)", (request_id, "system", "execution_failed", time.time()))
            raise
        with self._db() as db:
            db.execute("UPDATE requests SET status='completed',updated_at=? WHERE id=?", (time.time(), request_id))
            db.execute("INSERT INTO audit(request_id,actor,event,at) VALUES(?,?,?,?)", (request_id, "system", "completed", time.time()))
        return result

    def history(self, request_id: str) -> list[tuple[str, str, float]]:
        with self._db() as db:
            return db.execute("SELECT actor,event,at FROM audit WHERE request_id=? ORDER BY id", (request_id,)).fetchall()
