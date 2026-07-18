"""Conversation library: projects, sessions, and inheritable per-project
extraction settings. Shares traces.db with the trace/history/exchange stores.

A session is a conversation (the proxy's conversation-prefix hash). Sessions
belong to a project; projects carry export/extraction settings that fall back
field-by-field to a single editable global default — the UI shows, per field,
whether a value is inherited or overridden.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

# The extraction settings schema. Each key is independently inheritable:
# a project stores only the keys it overrides; unset keys resolve to default.
DEFAULT_SETTINGS: dict[str, Any] = {
    "compression": "xz",          # xz | gzip | none
    "compression_level": 9,       # 0-9
    "encryption": "none",         # none | passphrase | publickey
    "kdf": "scrypt",              # scrypt | argon2id | pbkdf2   (passphrase mode)
    "kdf_params": {"n": 16, "r": 8, "p": 1},  # scrypt: n=log2(N)
    "public_key": "",             # recipient key (X25519 base64 or RSA PEM) — publickey mode
    "destination": "dir",         # dir | command
    "directory": "~/llm-super-exports",
    "command": "",                # e.g. "gcloud storage cp {file} gs://bucket/"
    "include_upstream": True,     # include full provider exchanges (large)
}

# Which settings keys are secret-ish and should never be echoed wholesale.
_LONG_KEYS = {"public_key"}


class Library:
    def __init__(self, path: str | Path = "traces.db"):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_ts REAL NOT NULL,
                settings TEXT              -- JSON of overridden keys only
            )"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                session TEXT PRIMARY KEY,
                project_id TEXT,
                title TEXT,
                created_ts REAL NOT NULL,
                last_ts REAL NOT NULL,
                turns INTEGER DEFAULT 0
            )"""
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)"
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS session_aliases (
                alias TEXT PRIMARY KEY,    -- client-computed session id
                target TEXT NOT NULL,      -- conversation it continues
                ts REAL NOT NULL
            )"""
        )
        self._conn.commit()
        self._ensure_default_project()

    # ---- projects ----

    def _ensure_default_project(self) -> None:
        cur = self._conn.execute("SELECT COUNT(*) FROM projects WHERE id='default'")
        if cur.fetchone()[0] == 0:
            self._conn.execute(
                "INSERT INTO projects VALUES (?,?,?,?)",
                ("default", "Default", time.time(), None),
            )
            self._conn.commit()

    def create_project(self, name: str) -> str:
        pid = uuid.uuid4().hex[:12]
        self._conn.execute("INSERT INTO projects VALUES (?,?,?,?)",
                           (pid, name, time.time(), None))
        self._conn.commit()
        return pid

    def rename_project(self, pid: str, name: str) -> None:
        self._conn.execute("UPDATE projects SET name=? WHERE id=?", (name, pid))
        self._conn.commit()

    def delete_project(self, pid: str) -> None:
        if pid == "default":
            raise ValueError("cannot delete the default project")
        # reassign its sessions to default rather than orphaning them
        self._conn.execute("UPDATE sessions SET project_id='default' WHERE project_id=?", (pid,))
        self._conn.execute("DELETE FROM projects WHERE id=?", (pid,))
        self._conn.commit()

    def projects(self) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT id, name, created_ts, settings FROM projects ORDER BY created_ts")
        out = []
        for pid, name, ts, settings in cur.fetchall():
            overrides = json.loads(settings) if settings else {}
            out.append({"id": pid, "name": name, "created_ts": ts,
                        "overrides": list(overrides)})
        return out

    # ---- settings with inheritance ----

    def global_default(self) -> dict[str, Any]:
        cur = self._conn.execute(
            "SELECT value FROM app_settings WHERE key='default_extraction'")
        row = cur.fetchone()
        base = dict(DEFAULT_SETTINGS)
        if row:
            base.update(json.loads(row[0]))
        return base

    def set_global_default(self, patch: dict[str, Any]) -> None:
        cur = dict(self.global_default())
        cur.update({k: v for k, v in patch.items() if k in DEFAULT_SETTINGS})
        self._conn.execute(
            "INSERT OR REPLACE INTO app_settings VALUES ('default_extraction', ?)",
            (json.dumps(cur),))
        self._conn.commit()

    def project_overrides(self, pid: str) -> dict[str, Any]:
        cur = self._conn.execute("SELECT settings FROM projects WHERE id=?", (pid,))
        row = cur.fetchone()
        return json.loads(row[0]) if row and row[0] else {}

    def set_project_override(self, pid: str, key: str, value: Any) -> None:
        if key not in DEFAULT_SETTINGS:
            raise KeyError(key)
        ov = self.project_overrides(pid)
        ov[key] = value
        self._conn.execute("UPDATE projects SET settings=? WHERE id=?",
                           (json.dumps(ov), pid))
        self._conn.commit()

    def clear_project_override(self, pid: str, key: str) -> None:
        ov = self.project_overrides(pid)
        ov.pop(key, None)
        self._conn.execute("UPDATE projects SET settings=? WHERE id=?",
                           (json.dumps(ov) if ov else None, pid))
        self._conn.commit()

    def resolved_settings(self, pid: str) -> dict[str, dict[str, Any]]:
        """Every setting with its effective value AND its source, so the UI
        can show inherited-vs-overridden per field."""
        default = self.global_default()
        overrides = self.project_overrides(pid)
        out = {}
        for key, dval in default.items():
            if key in overrides:
                out[key] = {"value": overrides[key], "source": "project"}
            else:
                out[key] = {"value": dval, "source": "default"}
        return out

    def effective_settings(self, pid: str) -> dict[str, Any]:
        base = self.global_default()
        base.update(self.project_overrides(pid))
        return base

    # ---- retention settings (global; stored beside the extraction default) ----

    def retention_settings(self) -> dict[str, Any]:
        from .retention import DEFAULT_RETENTION

        cur = self._conn.execute(
            "SELECT value FROM app_settings WHERE key='retention'")
        row = cur.fetchone()
        base = dict(DEFAULT_RETENTION)
        if row:
            base.update(json.loads(row[0]))
        return base

    def set_retention(self, patch: dict[str, Any]) -> None:
        from .retention import DEFAULT_RETENTION

        cur = self.retention_settings()
        cur.update({k: v for k, v in patch.items() if k in DEFAULT_RETENTION})
        self._conn.execute(
            "INSERT OR REPLACE INTO app_settings VALUES ('retention', ?)",
            (json.dumps(cur),))
        self._conn.commit()

    # ---- sessions ----

    def has_session(self, session: str) -> bool:
        """Whether a conversation has been accepted before.

        Unlike the process-local new-session gate set, this survives a proxy
        restart.  Agentic conversations may have many persisted exchanges but
        no rows in ``History.turns`` until they produce a final text answer,
        so the sessions table is the durable knownness source.
        """
        row = self._conn.execute(
            "SELECT 1 FROM sessions WHERE session=? LIMIT 1", (session,)
        ).fetchone()
        return row is not None

    def touch_session(self, session: str, title: str) -> None:
        cur = self._conn.execute("SELECT session FROM sessions WHERE session=?", (session,))
        now = time.time()
        if cur.fetchone():
            self._conn.execute(
                "UPDATE sessions SET last_ts=?, turns=turns+1, "
                "title=COALESCE(NULLIF(title,''), ?) WHERE session=?",
                (now, title[:120], session))
        else:
            self._conn.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?)",
                (session, "default", title[:120], now, now, 1))
        self._conn.commit()

    def set_session_project(self, session: str, pid: str) -> None:
        self._conn.execute("UPDATE sessions SET project_id=? WHERE session=?", (pid, session))
        self._conn.commit()

    def set_session_title(self, session: str, title: str) -> None:
        self._conn.execute("UPDATE sessions SET title=? WHERE session=?", (title[:120], session))
        self._conn.commit()

    def delete_session(self, session: str) -> None:
        self._conn.execute("DELETE FROM sessions WHERE session=?", (session,))
        for t in ("events", "exchanges", "turns"):
            try:
                self._conn.execute(f"DELETE FROM {t} WHERE session=?", (session,))
            except sqlite3.OperationalError:
                pass
        self._conn.commit()

    # ---- session aliases (!attach): a client thread whose first message
    # hashes differently can be pinned onto an existing conversation ----

    def resolve_alias(self, session: str) -> str:
        cur = self._conn.execute(
            "SELECT target FROM session_aliases WHERE alias=?", (session,))
        row = cur.fetchone()
        return row[0] if row else session

    def set_alias(self, alias: str, target: str) -> None:
        """Targets are resolved before storing, so chains stay one hop."""
        target = self.resolve_alias(target)
        if alias == target:
            raise ValueError("a conversation cannot attach to itself")
        self._conn.execute(
            "INSERT INTO session_aliases VALUES (?,?,?) "
            "ON CONFLICT(alias) DO UPDATE SET target=excluded.target, ts=excluded.ts",
            (alias, target, time.time()))
        self._conn.commit()

    def drop_alias(self, alias: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM session_aliases WHERE alias=?", (alias,))
        self._conn.commit()
        return cur.rowcount > 0

    def sessions(self, project_id: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT session, project_id, title, created_ts, last_ts, turns FROM sessions"
        args: list[Any] = []
        if project_id:
            q += " WHERE project_id=?"
            args.append(project_id)
        q += " ORDER BY last_ts DESC"
        cur = self._conn.execute(q, args)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
