#!/usr/bin/env python3
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "traffic.log"
seq = 1
while True:
    item = {"id": 1000000 + seq, "account": f"traffic-{seq % 7}",
            "amount_cents": seq * 13, "memo": f"continuous-{seq}",
            "created_at": f"2026-07-19T12:{(seq // 60) % 60:02d}:{seq % 60:02d}Z",
            "currency": "USD"}
    status = 0
    response = ""
    try:
        request = urllib.request.Request(
            "http://127.0.0.1:8765/entries",
            data=json.dumps(item).encode(),
            headers={"content-type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as result:
            status = result.status
            response = result.read(1000).decode(errors="replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        response = exc.read(1000).decode(errors="replace")
    except Exception as exc:
        response = str(exc)
    event = {"seq": seq, "id": item["id"], "status": status,
             "acknowledged": 200 <= status < 300, "response": response[:300],
             "observed_at": time.time()}
    with LOG.open("a") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
        handle.flush()
    seq += 1
    time.sleep(0.35)
