#!/usr/bin/env python3
import hashlib
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "ledger.db"

def canonical(values):
    return "|".join(str(value) for value in values)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def send_json(self, status, value):
        body = json.dumps(value, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, json.loads((ROOT / "health-decoy.json").read_text()))
            return
        if self.path == "/ledger-stats":
            with sqlite3.connect(DB, timeout=15) as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                columns = [row[1] for row in db.execute("PRAGMA table_info(entries)")]
                rows = db.execute("SELECT count(*) FROM entries").fetchone()[0]
            self.send_json(200, {"user_version": version, "columns": columns,
                                 "row_count": rows})
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/entries":
            self.send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            item = json.loads(self.rfile.read(length))
            with sqlite3.connect(DB, timeout=15) as db:
                db.execute("PRAGMA busy_timeout=15000")
                columns = [row[1] for row in db.execute("PRAGMA table_info(entries)")]
                base = (int(item["id"]), str(item["account"]),
                        int(item["amount_cents"]), str(item["memo"]),
                        str(item["created_at"]))
                if "entry_hash" in columns:
                    currency = str(item.get("currency", "USD"))
                    digest = hashlib.sha256(
                        canonical(base + (currency,)).encode()
                    ).hexdigest()
                    db.execute(
                        "INSERT INTO entries "
                        "(id,account,amount_cents,memo,created_at,currency,entry_hash) "
                        "VALUES (?,?,?,?,?,?,?)", base + (currency, digest),
                    )
                else:
                    db.execute(
                        "INSERT INTO entries "
                        "(id,account,amount_cents,memo,created_at) VALUES (?,?,?,?,?)", base,
                    )
                db.commit()
            self.send_json(201, {"accepted": True, "id": base[0]})
        except Exception as exc:
            self.send_json(500, {"accepted": False, "error": str(exc)[:300]})

ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
