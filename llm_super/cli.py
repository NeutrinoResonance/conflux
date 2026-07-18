"""CLI: serve the proxy, probe provider logprobs capability, run a demo turn."""

from __future__ import annotations

import argparse
import asyncio
import json


def main() -> None:
    p = argparse.ArgumentParser(prog="llm-super")
    p.add_argument("--config", default="models.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the OpenAI-compatible proxy")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8055)

    sub.add_parser("probe", help="verify each registry model's logprobs capability")

    d = sub.add_parser("demo", help="run one supervised turn and print the report")
    d.add_argument("prompt", nargs="?", default=(
        "Write a Python function `median(xs)` that returns the median of a "
        "non-empty list of numbers. Include 3 doctest examples. Reply with "
        "only the code block."
    ))

    e = sub.add_parser("export", help="extract a conversation or project to a file")
    e.add_argument("--db", default="traces.db")
    g = e.add_mutually_exclusive_group(required=True)
    g.add_argument("--session")
    g.add_argument("--project")
    e.add_argument("--passphrase", help="for passphrase-encrypted projects")

    ls = sub.add_parser("sessions", help="list stored conversations")
    ls.add_argument("--db", default="traces.db")

    pr = sub.add_parser("prune", help="apply retention policy to the trace db now")
    pr.add_argument("--db", default="traces.db")
    pr.add_argument("--dry-run", action="store_true",
                    help="show current table stats without deleting")

    rp = sub.add_parser("report", help="efficiency report: spend by role, "
                                       "repair vs first-pass (SPEC §8 KPIs)")
    rp.add_argument("--db", default="traces.db")
    rp.add_argument("--days", type=float, default=30.0)

    sm = sub.add_parser(
        "summarize-history",
        help="build readable Sonnet summaries for every stored message",
    )
    sm.add_argument("--db", default="traces.db")
    sm.add_argument("--model", default="sonnet")
    sm.add_argument("--batch-chars", type=int, default=220_000)
    sm.add_argument("--batch-size", type=int, default=80)
    sm.add_argument("--max-budget-usd", type=float, default=1.0,
                    help="per-Claude-process safety ceiling")
    sm.add_argument("--force", action="store_true",
                    help="regenerate already summarized message hashes")
    sm.add_argument("--claude-command", default="claude",
                    help=argparse.SUPPRESS)

    args = p.parse_args()
    if args.cmd == "serve":
        import socket
        import sys

        # Fail loudly if the port is taken — a silently-failed bind while an
        # old server keeps answering is a debugging trap (stale code served).
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # match uvicorn's bind semantics, or TIME_WAIT sockets from a
        # recently-stopped server false-positive this check
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((args.host, args.port))
        except OSError:
            sys.exit(
                f"llm-super: port {args.port} on {args.host} is already in use.\n"
                f"Another llm-super (or something else) is running there — "
                f"find it with: lsof -i :{args.port}"
            )
        finally:
            probe.close()

        import uvicorn

        from . import proxy

        proxy.state["config_path"] = args.config
        uvicorn.run(proxy.app, host=args.host, port=args.port)
    elif args.cmd == "probe":
        asyncio.run(_probe(args.config))
    elif args.cmd == "demo":
        asyncio.run(_demo(args.config, args.prompt))
    elif args.cmd == "export":
        from . import export as export_mod
        from .library import Library
        from .trace import Trace

        result = export_mod.export(
            Trace(args.db), Library(args.db),
            session=args.session, project_id=args.project,
            passphrase=args.passphrase)
        print(f"{result['name']}\n  {result['bytes']/1024:.1f}KB from "
              f"{result['raw_bytes']/1024:.1f}KB "
              f"({round(100*result['bytes']/max(result['raw_bytes'],1))}%) · "
              f"{result['encryption']} · {result['compression']}\n  → {result['location']}")
    elif args.cmd == "sessions":
        from .library import Library

        for s in Library(args.db).sessions():
            print(f"{s['session'][:12]}  [{s['project_id']}]  turns={s['turns']}  "
                  f"{(s['title'] or '')[:60]}")
    elif args.cmd == "prune":
        from . import retention
        from .library import Library

        settings = Library(args.db).retention_settings()
        st = retention.stats(args.db)
        print(f"db: {st['db_bytes']/1024:.0f}KB | " + " | ".join(
            f"{t}: {v['rows']} rows"
            + (f" (oldest {v['oldest_days']}d)" if v["oldest_days"] else "")
            for t, v in st["tables"].items()))
        if args.dry_run:
            print("retention:", settings)
        else:
            rep = retention.prune(args.db, settings)
            print("deleted:", rep["deleted"],
                  f"| reclaimed {rep['reclaimed_bytes']/1024:.0f}KB"
                  + ("" if rep.get("vacuumed", True) else " (vacuum deferred: db busy)"))
    elif args.cmd == "report":
        from . import report as report_mod

        print(report_mod.format_text(report_mod.efficiency(args.db, args.days)))
    elif args.cmd == "summarize-history":
        import sys

        from . import message_summaries

        try:
            result = message_summaries.backfill(
                args.db,
                model=args.model,
                batch_chars=args.batch_chars,
                batch_size=args.batch_size,
                max_budget_usd=args.max_budget_usd,
                force=args.force,
                command=args.claude_command,
                progress=lambda event: print(_summary_progress(event), flush=True),
            )
        except (message_summaries.SummaryError, ValueError) as exc:
            sys.exit(f"llm-super: history summary backfill failed: {exc}")
        print(
            "history summaries complete: "
            f"{result['summarized']}/{result['unique']} distinct messages · "
            f"{result['occurrences']} placements · "
            f"{result['generated']} generated this run · "
            f"${result['cost_usd']:.6f} reported usage"
        )


def _summary_progress(event: dict) -> str:
    """Format progress without ever interpolating message-derived content."""
    kind = event.get("event")
    if kind == "indexed":
        return (
            f"indexed {event.get('occurrences', 0)} placements from "
            f"{event.get('exchanges', 0)} exchanges "
            f"({event.get('unique', 0)} distinct messages)"
        )
    if kind == "authenticated":
        return (
            "Claude authenticated · "
            f"{event.get('provider', 'unknown')} / "
            f"{event.get('subscription', 'unknown')}"
        )
    if kind == "batch_start":
        return (
            f"batch {event.get('batch')} started · {event.get('items', 0)} messages · "
            f"{event.get('chars', 0)} sanitized characters"
        )
    if kind == "batch_split":
        return (
            f"batch {event.get('batch')} did not validate; retrying its "
            f"{event.get('items', 0)} messages in smaller batches"
        )
    if kind == "batch_complete":
        return (
            f"batch {event.get('batch')} complete · {event.get('items', 0)} messages · "
            f"{event.get('duration_ms', 0) / 1000:.1f}s · "
            f"${event.get('cost_usd', 0.0):.6f}"
        )
    if kind == "complete":
        return (
            f"verified coverage {event.get('summarized', 0)}/"
            f"{event.get('unique', 0)}"
        )
    return "history summary backfill progressing"


async def _probe(config_path: str) -> None:
    from .config import load
    from .providers import Client, ProviderError

    cfg = load(config_path)
    client = Client(cfg)
    samples = 3  # logprobs presence is flaky on aggregators — sample, don't spot-check
    try:
        for name, model in cfg.models.items():
            hits, errs = 0, 0
            for _ in range(samples):
                try:
                    res = await client.chat(
                        model,
                        [{"role": "user", "content": "Reply with only the integer 7."}],
                        max_tokens=2000,
                        temperature=0.0,
                        logprobs=True,
                    )
                    if res.logprob_content and res.logprob_content[0].get("top_logprobs"):
                        hits += 1
                except ProviderError:
                    errs += 1
            observed = hits > 0
            flag = "OK      " if observed == model.logprobs else "MISMATCH"
            note = f" ({errs} errors)" if errs else ""
            print(f"{flag} {name:20s} logprobs {hits}/{samples}{note} "
                  f"(registry says {model.logprobs})")
    finally:
        await client.aclose()


async def _demo(config_path: str, prompt: str) -> None:
    from .config import load
    from .control import ControlState
    from .orchestrator import Orchestrator
    from .providers import Client
    from .trace import Trace

    cfg = load(config_path)
    client = Client(cfg)
    try:
        orch = Orchestrator(cfg, client, Trace(":memory:"), ControlState())
        report = await orch.run_turn("demo", [{"role": "user", "content": prompt}])
        print(report.text)
        print(report.trailer())
        if report.verify:
            print("\nper-criterion:", json.dumps(
                {c.criterion: {"expected": round(c.expected, 2), "continuous": c.continuous}
                 for c in report.verify.criteria}, indent=2))
    finally:
        await client.aclose()


if __name__ == "__main__":
    main()
