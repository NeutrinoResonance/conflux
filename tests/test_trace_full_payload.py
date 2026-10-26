import json
import sqlite3
import time

from conflux import retention
from conflux.trace import Trace


def _request(n: int, size: int) -> dict:
    return {"model": "m", "messages": [
        {"role": "user" if i == 0 else "tool", "content": f"{i}:" + "x" * size}
        for i in range(n)
    ]}


def test_oversized_request_keeps_head_row_and_full_copy(tmp_path):
    trace = Trace(tmp_path / "t.db")
    payload = _request(30, 20_000)  # ~600k chars, over MAX_PAYLOAD
    trace.record_exchange("s", "t", "client_request", None, payload)

    stored = json.loads(trace.connection.execute(
        "SELECT payload FROM exchanges").fetchone()[0])
    assert stored["truncated"] and stored["full"]
    assert len(stored["head"]) == Trace.MAX_PAYLOAD

    exchange_id = trace.connection.execute("SELECT id FROM exchanges").fetchone()[0]
    assert trace.full_payload(exchange_id) == payload
    # The tail message that a head-only row loses is present.
    assert trace.last_client_request("s")[-1]["content"].startswith("29:")


def test_small_and_legacy_rows_read_unchanged(tmp_path):
    trace = Trace(tmp_path / "t.db")
    trace.record_exchange("s", "t", "client_request", None, _request(2, 10))
    small_id = trace.connection.execute("SELECT max(id) FROM exchanges").fetchone()[0]
    assert trace.full_payload(small_id) == _request(2, 10)
    assert trace.connection.execute("SELECT count(*) FROM exchange_full").fetchone()[0] == 0

    legacy = {"truncated": True, "chars": 900_000, "head": "{"}
    trace.connection.execute(
        "INSERT INTO exchanges (ts, session, task, kind, model, payload) VALUES (?,?,?,?,?,?)",
        (time.time(), "s", "t", "client_request", None, json.dumps(legacy)))
    trace.connection.commit()
    assert trace.last_client_request("s") is None  # unparseable legacy row, as before
    assert trace.full_payload(10_000) is None


def test_retention_drops_full_copies_with_their_exchange(tmp_path):
    path = tmp_path / "t.db"
    trace = Trace(path)
    trace.record_exchange("s", "t", "client_request", None, _request(30, 20_000))
    trace.connection.execute("UPDATE exchanges SET ts = ts - 30 * 86400")
    trace.connection.commit()

    report = retention.prune(path, {"exchanges_days": 14, "vacuum": False})
    assert report["deleted"]["exchange_full"] == 1
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT count(*) FROM exchange_full").fetchone()[0] == 0
