"""Conversation extraction: "pop out" a session or project from the DB into a
single, well-compressed, optionally-encrypted file.

Container format (`.llmx`):
    b"LLMX1\n" + <json header line> + b"\n" + <body bytes>
The header is always cleartext (it says how to read the body); the body is
`<compression>(<plaintext>)` optionally wrapped by `<encryption>`.

Plaintext is the conversation bundle (JSON): project + sessions, each with
their events, exchanges, and turns — everything needed to reconstruct the
conversation elsewhere.

Encryption modes (all AEAD via AES-256-GCM):
  passphrase — key = KDF(passphrase, salt); KDF ∈ {scrypt, argon2id, pbkdf2}
  publickey  — hybrid: X25519 (raw base64 recipient key) or RSA-OAEP (PEM);
               a random content key encrypts the body, wrapped to the recipient.
Compression ∈ {xz, gzip, none}.
"""

from __future__ import annotations

import base64
import gzip
import json
import lzma
import os
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"LLMX1\n"


# ---------------- bundle assembly ----------------

def build_bundle(trace, library, *, session: str | None = None,
                 project_id: str | None = None,
                 include_upstream: bool = True) -> dict[str, Any]:
    if session:
        sessions = [s for s in library.sessions() if s["session"] == session]
    elif project_id:
        sessions = library.sessions(project_id=project_id)
    else:
        raise ValueError("specify session or project_id")

    bundle_sessions = []
    for s in sessions:
        sid = s["session"]
        exchanges = trace.exchanges(session=sid, n=100000)
        if not include_upstream:
            exchanges = [e for e in exchanges if e.get("kind") != "upstream"]
        bundle_sessions.append({
            "session": sid,
            "title": s.get("title"),
            "project_id": s.get("project_id"),
            "turns": library_turns(trace, sid),
            "events": [e for e in trace.recent(100000) if e.get("session") == sid],
            "exchanges": exchanges,
            # Generated prose is a derived index over immutable exchanges.
            # Keep its occurrence pointers in exports so a restored bundle can
            # retain the readable history view without re-sending content to a
            # summarizer.  Older databases simply produce an empty list.
            "message_summaries": library_message_summaries(trace, sid),
            "step_summaries": library_step_summaries(trace, sid),
        })
    return {
        "schema": "conflux/conversation-bundle@1",
        "exported_at": time.time(),
        "project_id": project_id,
        "session": session,
        "sessions": bundle_sessions,
    }


def library_turns(trace, sid: str) -> list[dict]:
    try:
        return trace._conn.execute(  # history table lives in same db
            "SELECT turn_no, ts, task, response, score FROM turns WHERE session=? "
            "ORDER BY turn_no", (sid,)).fetchall()
    except sqlite3.OperationalError:
        return []


def library_message_summaries(trace, sid: str) -> list[dict[str, Any]]:
    """Return current generated summaries plus their exact source pointers.

    Summary tables are deliberately optional: existing databases and exports
    remain valid before the summary backfill has ever been run.
    """
    try:
        cursor = trace._conn.execute(
            """SELECT src.exchange_id, src.json_pointer, src.boundary,
                      src.ordinal, src.task, src.role, src.tool_call_id,
                      src.input_sha256, src.prompt_version, src.ts,
                      summary.headline, summary.summary, summary.generator,
                      summary.model, summary.source_chars, summary.created_ts
                 FROM message_summary_sources AS src
                 JOIN message_summaries AS summary
                   ON summary.input_sha256=src.input_sha256
                  AND summary.prompt_version=src.prompt_version
                WHERE src.session=?
                ORDER BY src.ts, src.exchange_id, src.ordinal""",
            (sid,),
        )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except sqlite3.OperationalError:
        return []


def library_step_summaries(trace, sid: str) -> list[dict[str, Any]]:
    """Return the three-level UI metadata for each exported logical step."""
    try:
        cursor = trace._conn.execute(
            """SELECT session, task, short_summary, node_label, long_summary,
                      generator, prompt_version, created_ts, updated_ts
                 FROM step_summaries
                WHERE session=?
                ORDER BY created_ts, task""",
            (sid,),
        )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except sqlite3.OperationalError:
        return []


# ---------------- KDF ----------------

def _derive_key(passphrase: str, salt: bytes, kdf: str, params: dict) -> bytes:
    pw = passphrase.encode()
    if kdf == "scrypt":
        n = 2 ** int(params.get("n", 16))
        return Scrypt(salt=salt, length=32, n=n,
                      r=int(params.get("r", 8)), p=int(params.get("p", 1))).derive(pw)
    if kdf == "pbkdf2":
        return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                          iterations=int(params.get("iterations", 600_000))).derive(pw)
    if kdf == "argon2id":
        try:
            from argon2.low_level import Type, hash_secret_raw
        except ImportError as e:
            raise RuntimeError("argon2id KDF requires the argon2-cffi package "
                               "(pip install 'conflux[argon2]')") from e
        return hash_secret_raw(
            pw, salt,
            time_cost=int(params.get("time_cost", 3)),
            memory_cost=int(params.get("memory_cost", 65536)),
            parallelism=int(params.get("parallelism", 4)),
            hash_len=32, type=Type.ID)
    raise ValueError(f"unknown KDF {kdf!r}")


# ---------------- compression ----------------

def _compress(data: bytes, mode: str, level: int) -> bytes:
    if mode == "xz":
        return lzma.compress(data, preset=level | lzma.PRESET_EXTREME)
    if mode == "gzip":
        return gzip.compress(data, compresslevel=level)
    if mode == "none":
        return data
    raise ValueError(f"unknown compression {mode!r}")


def _decompress(data: bytes, mode: str) -> bytes:
    if mode == "xz":
        return lzma.decompress(data)
    if mode == "gzip":
        return gzip.decompress(data)
    return data


# ---------------- public-key helpers ----------------

def _load_recipient(public_key: str):
    pk = public_key.strip()
    if pk.startswith("-----BEGIN"):
        return ("rsa", serialization.load_pem_public_key(pk.encode()))
    raw = base64.b64decode(pk)
    return ("x25519", x25519.X25519PublicKey.from_public_bytes(raw))


# ---------------- encrypt / write ----------------

def pack(bundle: dict, settings: dict, *, passphrase: str | None = None) -> bytes:
    plaintext = json.dumps(bundle, default=str).encode()
    comp = settings.get("compression", "xz")
    body = _compress(plaintext, comp, int(settings.get("compression_level", 9)))

    header: dict[str, Any] = {
        "version": 1,
        "created": time.time(),
        "compression": comp,
        "encryption": settings.get("encryption", "none"),
        "raw_bytes": len(plaintext),
    }
    enc = settings.get("encryption", "none")

    if enc == "none":
        pass
    elif enc == "passphrase":
        if not passphrase:
            raise ValueError("passphrase encryption requires a passphrase")
        salt = os.urandom(16)
        kdf = settings.get("kdf", "scrypt")
        params = settings.get("kdf_params", {})
        key = _derive_key(passphrase, salt, kdf, params)
        nonce = os.urandom(12)
        body = AESGCM(key).encrypt(nonce, body, None)
        header.update(kdf=kdf, kdf_params=params,
                      salt=base64.b64encode(salt).decode(),
                      nonce=base64.b64encode(nonce).decode())
    elif enc == "publickey":
        kind, recipient = _load_recipient(settings.get("public_key", ""))
        content_key = os.urandom(32)
        nonce = os.urandom(12)
        body = AESGCM(content_key).encrypt(nonce, body, None)
        if kind == "x25519":
            eph = x25519.X25519PrivateKey.generate()
            shared = eph.exchange(recipient)
            wrap_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                            info=b"conflux-x25519").derive(shared)
            wrap_nonce = os.urandom(12)
            wrapped = AESGCM(wrap_key).encrypt(wrap_nonce, content_key, None)
            header.update(
                pk_kind="x25519", nonce=base64.b64encode(nonce).decode(),
                ephemeral=base64.b64encode(eph.public_key().public_bytes(
                    serialization.Encoding.Raw,
                    serialization.PublicFormat.Raw)).decode(),
                wrap_nonce=base64.b64encode(wrap_nonce).decode(),
                wrapped_key=base64.b64encode(wrapped).decode())
        else:  # rsa
            wrapped = recipient.encrypt(
                content_key,
                padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                             algorithm=hashes.SHA256(), label=None))
            header.update(pk_kind="rsa", nonce=base64.b64encode(nonce).decode(),
                          wrapped_key=base64.b64encode(wrapped).decode())
    else:
        raise ValueError(f"unknown encryption {enc!r}")

    return MAGIC + json.dumps(header).encode() + b"\n" + body


def unpack(blob: bytes, *, passphrase: str | None = None,
           private_key: str | None = None) -> dict:
    if not blob.startswith(MAGIC):
        raise ValueError("not an conflux export (bad magic)")
    rest = blob[len(MAGIC):]
    nl = rest.index(b"\n")
    header = json.loads(rest[:nl])
    body = rest[nl + 1:]
    enc = header.get("encryption", "none")

    if enc == "passphrase":
        key = _derive_key(passphrase or "", base64.b64decode(header["salt"]),
                          header["kdf"], header.get("kdf_params", {}))
        body = AESGCM(key).decrypt(base64.b64decode(header["nonce"]), body, None)
    elif enc == "publickey":
        if not private_key:
            raise ValueError("publickey export requires the private key to read")
        if header["pk_kind"] == "x25519":
            priv = x25519.X25519PrivateKey.from_private_bytes(
                base64.b64decode(private_key))
            shared = priv.exchange(x25519.X25519PublicKey.from_public_bytes(
                base64.b64decode(header["ephemeral"])))
            wrap_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                            info=b"conflux-x25519").derive(shared)
            content_key = AESGCM(wrap_key).decrypt(
                base64.b64decode(header["wrap_nonce"]),
                base64.b64decode(header["wrapped_key"]), None)
        else:
            priv = serialization.load_pem_private_key(private_key.encode(), password=None)
            content_key = priv.decrypt(
                base64.b64decode(header["wrapped_key"]),
                padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                             algorithm=hashes.SHA256(), label=None))
        body = AESGCM(content_key).decrypt(base64.b64decode(header["nonce"]), body, None)

    return json.loads(_decompress(body, header.get("compression", "none")))


# ---------------- destinations ----------------

def deliver(blob: bytes, name: str, settings: dict) -> str:
    """Write the export to its configured destination; return a location string."""
    dest = settings.get("destination", "dir")
    if dest == "dir":
        d = Path(os.path.expanduser(settings.get("directory", "~/conflux-exports")))
        d.mkdir(parents=True, exist_ok=True)
        path = d / name
        path.write_bytes(blob)
        return str(path)
    if dest == "command":
        # Stage to a temp file, then run the user's command with {file}/{name}.
        tmp = Path(os.path.expanduser("~/.cache/conflux"))
        tmp.mkdir(parents=True, exist_ok=True)
        staged = tmp / name
        staged.write_bytes(blob)
        cmd = settings.get("command", "").format(file=str(staged), name=name)
        if not cmd.strip():
            raise ValueError("destination=command but no command configured")
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"destination command failed: {proc.stderr[:300]}")
        return f"command: {cmd} (ok)"
    raise ValueError(f"unknown destination {dest!r}")


# ---------------- top-level ----------------

def export(trace, library, *, session: str | None = None,
           project_id: str | None = None, passphrase: str | None = None) -> dict:
    """Build → pack → deliver, using the project's effective settings."""
    pid = project_id
    if session and not pid:
        s = next((x for x in library.sessions() if x["session"] == session), None)
        pid = (s or {}).get("project_id", "default")
    settings = library.effective_settings(pid or "default")
    bundle = build_bundle(trace, library, session=session, project_id=project_id,
                          include_upstream=settings.get("include_upstream", True))
    blob = pack(bundle, settings, passphrase=passphrase)
    stamp = str(int(bundle["exported_at"]))
    ext = ".llmx" if settings.get("encryption") != "none" else {
        "xz": ".json.xz", "gzip": ".json.gz", "none": ".json"}[settings["compression"]]
    label = session or project_id or "export"
    name = f"conflux-{label}-{stamp}{ext}"
    location = deliver(blob, name, settings)
    return {"name": name, "bytes": len(blob), "raw_bytes": bundle_raw_size(bundle),
            "location": location, "encryption": settings.get("encryption"),
            "compression": settings.get("compression")}


def bundle_raw_size(bundle: dict) -> int:
    return len(json.dumps(bundle, default=str).encode())
