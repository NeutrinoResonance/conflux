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
