from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from llm_super.history_view import (
    AcceptanceAnchor,
    EndeavorGrouping,
    HistoryView,
    NETBSD_ARM64_ENDEAVOR,
)
from llm_super.message_summaries import PROMPT_VERSION, index_sources


def _response(*, finish: str = "stop", call_id: str | None = None,
              command: str = "") -> dict:
    message: dict = {"role": "assistant", "content": "done"}
    if call_id:
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {
                    "name": "terminal",
                    "arguments": json.dumps({"command": command}),
                },
            }],
        }
    return {
        "id": f"response-{call_id or 'final'}",
        "choices": [{"finish_reason": finish, "message": message}],
        "logprobs": {"raw_diagnostic_marker": "MUST_NOT_LEAK"},
    }


class HistoryViewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "trace.db"
        self.conn = sqlite3.connect(self.db)
        self.conn.executescript(
            """
            CREATE TABLE events (
              ts REAL NOT NULL, session TEXT NOT NULL, task TEXT NOT NULL,
              kind TEXT NOT NULL, model TEXT, fm_id TEXT,
              tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0,
              cost_usd REAL DEFAULT 0, data TEXT
            );
            CREATE TABLE exchanges (
              id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
              session TEXT NOT NULL, task TEXT NOT NULL, kind TEXT NOT NULL,
              model TEXT, payload TEXT NOT NULL
            );
            CREATE TABLE sessions (
              session TEXT PRIMARY KEY, project_id TEXT, title TEXT,
              created_ts REAL NOT NULL, last_ts REAL NOT NULL,
              turns INTEGER DEFAULT 0
            );
            CREATE TABLE session_aliases (
              alias TEXT PRIMARY KEY, target TEXT NOT NULL, ts REAL NOT NULL
            );
            """
        )
        self.now = 1_000.0

    def tearDown(self) -> None:
        self.conn.close()
        self.temp.cleanup()

    def session(self, sid: str, *, title: str | None = None,
                project: str = "default", ts: float | None = None) -> None:
        when = self.now if ts is None else ts
        self.conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?)",
            (sid, project, title or f"title {sid}", when, when, 1),
        )
        self.conn.commit()

    def event(self, sid: str, task: str, kind: str, *, ts: float | None = None,
              tokens_in: int = 0, tokens_out: int = 0, cost: float = 0.0,
              data: dict | None = None) -> None:
        when = self.now if ts is None else ts
        self.now = max(self.now, when) + 1
        self.conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
            (when, sid, task, kind, "model-a", None, tokens_in, tokens_out,
             cost, json.dumps(data) if data is not None else None),
        )
        self.conn.execute(
            "UPDATE sessions SET last_ts=MAX(last_ts, ?) WHERE session=?",
            (when, sid),
        )
        self.conn.commit()

    def exchange(self, sid: str, task: str, kind: str, payload: dict,
                 *, ts: float | None = None) -> None:
        when = self.now if ts is None else ts
        self.now = max(self.now, when) + 1
        self.conn.execute(
            "INSERT INTO exchanges (ts,session,task,kind,model,payload) "
            "VALUES (?,?,?,?,?,?)",
            (when, sid, task, kind, "model-a", json.dumps(payload)),
        )
        self.conn.execute(
            "UPDATE sessions SET last_ts=MAX(last_ts, ?) WHERE session=?",
            (when, sid),
        )
        self.conn.commit()

    def task_exchanges(self, sid: str, task: str, request: dict,
                       response: dict) -> None:
        self.exchange(sid, task, "client_request", request)
        upstream_request = dict(request)
        upstream_request["model"] = "provider/model-a"
        self.exchange(sid, task, "upstream", {
            "request": upstream_request,
            "response": response,
            "provider_debug": "RAW_UPSTREAM_MUST_NOT_LEAK",
        })
        self.exchange(sid, task, "client_response", response)

    def view(self, *, groupings=(), fixture: bool = False) -> HistoryView:
        return HistoryView(
            self.db,
            groupings=groupings,
            include_documented_fixtures=fixture,
        )

    def add_summary(self, exchange_id: int, pointer: str, headline: str,
                    summary: str) -> None:
        row = self.conn.execute(
            "SELECT input_sha256, role FROM message_summary_sources "
            "WHERE exchange_id=? AND json_pointer=?",
            (exchange_id, pointer),
        ).fetchone()
        self.assertIsNotNone(row)
        self.conn.execute(
            """INSERT OR REPLACE INTO message_summaries
                 (input_sha256,prompt_version,role,headline,summary,generator,
                  model,source_chars,created_ts)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (row[0], PROMPT_VERSION, row[1], headline, summary, "claude-cli",
             "claude-sonnet-test", 10, self.now),
        )
        self.now += 1
        self.conn.commit()

    def test_explicit_grouping_safe_fallback_alias_and_cursor_pagination(self) -> None:
        for index in range(5):
            self.session(f"s{index}", title="identical title", ts=100 + index)
            self.event(f"s{index}", f"t{index}", "turn_end", ts=200 + index)
        self.conn.execute(
            "INSERT INTO session_aliases VALUES ('s2','s3',300)"
        )
        self.conn.commit()
        explicit = EndeavorGrouping(
            id="manual", title="Manually grouped", sessions=("s0", "s1")
        )

        with self.view(groupings=(explicit,)) as view:
            first = view.list_endeavors(limit=2)
            self.assertEqual(first["total"], 3)
            self.assertEqual(len(first["items"]), 2)
            self.assertIsNotNone(first["next_cursor"])
            second = view.list_endeavors(cursor=first["next_cursor"], limit=2)
            self.assertEqual(len(second["items"]), 1)
            self.assertIsNone(second["next_cursor"])
            ids = {row["id"] for row in first["items"] + second["items"]}
            self.assertIn("manual", ids)
            self.assertIn("conversation:s2", ids)
            self.assertIn("session:s4", ids)

            # Opaque cursors are scoped and cannot silently page another view.
            with self.assertRaises(ValueError):
                view.list_runs("manual", cursor=first["next_cursor"], limit=2)
            with self.assertRaises(ValueError):
                view.list_endeavors(
                    status="succeeded", cursor=first["next_cursor"], limit=2
                )

    def test_terminal_states_never_leave_dead_legacy_runs_running(self) -> None:
        for sid in ("failed", "interrupted", "complete"):
            self.session(sid)
        self.event("failed", "tf", "agent_turn")
        self.event("failed", "tf", "executor_error", data={"error": "HTTP 401 secret"})

        self.event("interrupted", "ti", "agent_turn")
        self.event("interrupted", "ti", "tool_step")
        self.task_exchanges(
            "interrupted", "ti", {"messages": [{"role": "user", "content": "go"}]},
            _response(finish="tool_calls", call_id="missing", command="uname -a"),
        )

        self.event("complete", "tc", "turn_start")
        self.event("complete", "tc", "turn_end")
        grouping = EndeavorGrouping(
            id="states", title="States", sessions=("failed", "interrupted", "complete")
        )
        with self.view(groupings=(grouping,)) as view:
            runs = view.list_runs("states", limit=10)["items"]
        statuses = {row["session_id"]: row["status"] for row in runs}
        self.assertEqual(statuses, {
            "failed": "failed",
            "interrupted": "interrupted",
            "complete": "succeeded",
        })
        self.assertNotIn("running", statuses.values())

    def test_observed_terminal_failure_wins_over_legacy_status(self) -> None:
        for sid in ("escalated", "not-passed", "clean"):
            self.session(sid)
        self.event(
            "escalated", "te", "turn_end",
            data={"score": 0.0, "escalated": "quality bar was not reached"},
        )
        self.event(
            "not-passed", "tn", "agent_end",
            data={"passed": False, "escalated": ""},
        )
        self.event(
            "clean", "tc", "turn_end",
            data={"passed": True, "escalated": ""},
        )
        grouping = EndeavorGrouping(
            id="terminal-evidence",
            title="Terminal evidence",
            sessions=("escalated", "not-passed", "clean"),
            run_statuses={
                "escalated": "succeeded",
                "not-passed": "succeeded",
                "clean": "failed",
            },
        )

        with self.view(groupings=(grouping,)) as view:
            runs = view.list_runs("terminal-evidence", limit=10)["items"]
            timeline = view.timeline(
                "terminal-evidence", collapse_polling=False, limit=10
            )["items"]

        self.assertEqual(
            {run["session_id"]: run["status"] for run in runs},
            {"escalated": "failed", "not-passed": "failed", "clean": "succeeded"},
        )
        self.assertEqual(
            {step["session_id"]: step["status"] for step in timeline},
            {"escalated": "failed", "not-passed": "failed", "clean": "succeeded"},
        )

    def test_fallback_summaries_never_use_prompt_preview_as_title(self) -> None:
        secret = "PROMPT_SECRET_MUST_NOT_APPEAR"
        self.session("safe-title", title=secret)
        self.event(
            "safe-title", "task", "agent_turn",
            data={"task_preview": secret},
        )

        with self.view() as view:
            listing = view.list_endeavors(limit=10)
            detail = view.get_endeavor("session:safe-title")
            runs = view.list_runs("session:safe-title", limit=10)

        encoded = json.dumps({"listing": listing, "detail": detail, "runs": runs})
        self.assertNotIn(secret, encoded)
        self.assertEqual(listing["items"][0]["title"], "Conversation safe-title")
        self.assertEqual(runs["items"][0]["title"], "Run safe-title")

    def test_provider_errors_and_monitor_findings_are_separate(self) -> None:
        self.session("taxonomy")
        self.event("taxonomy", "task", "fm_event", data={"fm_id": "FM-X.1"})
        self.event("taxonomy", "task", "executor_error", data={"error": "outage"})
        self.event("taxonomy", "task", "provider_error", data={"error": "timeout"})
        self.event("taxonomy", "task", "turn_end", data={"passed": True})

        with self.view() as view:
            detail = view.get_endeavor("session:taxonomy")
            run = view.list_runs("session:taxonomy", limit=10)["items"][0]
            step = view.timeline(
                "session:taxonomy", collapse_polling=False, limit=10
            )["items"][0]

        for summary in (detail, run):
            self.assertEqual(summary["provider_errors"], 2)
            self.assertEqual(summary["monitor_findings"], 1)
            self.assertEqual(summary["errors"]["total"], 2)
        self.assertEqual(step["error_count"], 2)
        self.assertEqual(step["monitor_finding_count"], 1)
        self.assertEqual(step["severity"], "warning")

    def test_delta_and_duplicate_boundary_metadata_omit_raw_payloads(self) -> None:
        self.session("delta")
        tools = [{
            "type": "function",
            "function": {"name": "terminal", "description": "RAW_TOOL_SECRET"},
        }]
        first_messages = [
            {"role": "system", "content": "RAW_SYSTEM_SECRET"},
            {"role": "user", "content": "start"},
        ]
        first_response = _response(
            finish="tool_calls", call_id="call-1", command="printf hidden"
        )
        self.event("delta", "one", "agent_turn", data={"raw": "RAW_EVENT_SECRET"})
        self.event("delta", "one", "tool_step")
        self.task_exchanges(
            "delta", "one", {"messages": first_messages, "tools": tools}, first_response
        )

        appended = [
            first_response["choices"][0]["message"],
            {"role": "tool", "tool_call_id": "call-1", "content": json.dumps({
                "ok": True, "exit_code": 0, "stdout": "RAW_RESULT_SECRET",
            })},
        ]
        second_messages = first_messages + appended
        second_response = _response()
        self.event("delta", "two", "agent_turn")
        self.event("delta", "two", "agent_end")
        self.task_exchanges(
            "delta", "two", {"messages": second_messages, "tools": tools}, second_response
        )

        with self.view() as view:
            timeline = view.timeline("session:delta", collapse_polling=False, limit=10)
        self.assertEqual(timeline["total"], 2)
        one, two = timeline["items"]
        self.assertEqual(one["message_delta"]["relation"], "initial")
        self.assertEqual(one["message_delta"]["delta_messages"], 2)
        self.assertEqual(two["message_delta"]["relation"], "continuation")
        self.assertEqual(two["message_delta"]["total_messages"], 4)
        self.assertEqual(two["message_delta"]["delta_messages"], 2)
        self.assertEqual(two["message_delta"]["delta_roles"], ["assistant", "tool"])
        self.assertFalse(two["message_delta"]["system_prompt_changed"])
        self.assertFalse(two["message_delta"]["tool_schema_changed"])

        duplicate = one["duplicate_boundaries"]
        self.assertTrue(duplicate["request_messages_identical"])
        self.assertTrue(duplicate["request_tools_identical"])
        self.assertTrue(duplicate["response_identical"])
        self.assertEqual(duplicate["raw_copy_count"], 3)
        self.assertEqual(len(one["source_event_ids"]), 2)
        self.assertEqual(len(two["source_event_ids"]), 2)

        encoded = json.dumps(timeline)
        for forbidden in (
            '"payload"', '"data"', "RAW_SYSTEM_SECRET", "RAW_TOOL_SECRET",
            "RAW_RESULT_SECRET", "RAW_EVENT_SECRET", "MUST_NOT_LEAK",
            "RAW_UPSTREAM_MUST_NOT_LEAK",
        ):
            self.assertNotIn(forbidden, encoded)
        self.assertLess(len(encoded), 10_000)

    def test_generated_summaries_supply_context_decisions_and_tool_results(self) -> None:
        self.session("summarized")
        first_response = _response(
            finish="tool_calls", call_id="compile-1", command="make release"
        )
        self.event("summarized", "one", "agent_turn")
        self.event("summarized", "one", "tool_step")
        self.task_exchanges(
            "summarized", "one",
            {"messages": [{"role": "user", "content": "RAW_BUILD_REQUEST"}]},
            first_response,
        )
        second_messages = [
            {"role": "user", "content": "RAW_BUILD_REQUEST"},
            first_response["choices"][0]["message"],
            {"role": "tool", "tool_call_id": "compile-1", "content": json.dumps({
                "exit_code": 0, "stdout": "RAW_BUILD_OUTPUT",
            })},
        ]
        self.event("summarized", "two", "agent_turn")
        self.event("summarized", "two", "agent_end")
        self.task_exchanges(
            "summarized", "two", {"messages": second_messages}, _response()
        )
        index_sources(self.db)

        client_requests = self.conn.execute(
            "SELECT id,task FROM exchanges WHERE kind='client_request' ORDER BY id"
        ).fetchall()
        client_responses = self.conn.execute(
            "SELECT id,task FROM exchanges WHERE kind='client_response' ORDER BY id"
        ).fetchall()
        request_ids = {task: identifier for identifier, task in client_requests}
        response_ids = {task: identifier for identifier, task in client_responses}
        self.add_summary(
            request_ids["one"], "/messages/0", "Compile NetBSD",
            "The user asks for a cross-architecture NetBSD build.",
        )
        request_hash, request_role = self.conn.execute(
            "SELECT input_sha256,role FROM message_summary_sources "
            "WHERE exchange_id=? AND json_pointer='/messages/0'",
            (request_ids["one"],),
        ).fetchone()
        self.conn.execute(
            "INSERT INTO message_summaries VALUES (?,?,?,?,?,?,?,?,?)",
            (request_hash, "obsolete-prompt", request_role, "Stale context",
             "This must not be selected.", "claude-cli", "old-model", 10,
             self.now + 1_000),
        )
        self.conn.commit()
        self.add_summary(
            response_ids["one"], "/choices/0/message", "Start compilation",
            "The agent launches the release build.",
        )
        self.add_summary(
            request_ids["two"], "/messages/2", "Compilation succeeded",
            "The build command completed with exit code zero.",
        )
        self.add_summary(
            response_ids["two"], "/choices/0/message", "Build complete",
            "The agent reports that the requested work is done.",
        )

        with self.view() as view:
            detail = view.get_endeavor("session:summarized")
            run = view.list_runs("session:summarized", limit=10)["items"][0]
            timeline = view.timeline(
                "session:summarized", collapse_polling=False, limit=10
            )["items"]

        self.assertEqual(detail["context_summary"]["headline"], "Compile NetBSD")
        self.assertEqual(run["context_summary"]["headline"], "Compile NetBSD")
        self.assertGreater(detail["message_summary_coverage"]["occurrences"], 4)
        self.assertEqual(timeline[0]["message_delta"]["summaries"][0]["headline"],
                         "Compile NetBSD")
        self.assertEqual(timeline[0]["response_summary"]["headline"],
                         "Start compilation")
        self.assertEqual(timeline[0]["provider_summaries"], [])
        self.assertEqual(timeline[0]["tool_calls"][0]["result_summary"]["headline"],
                         "Compilation succeeded")
        self.assertEqual(timeline[1]["response_summary"]["headline"], "Build complete")
        encoded = json.dumps({"detail": detail, "run": run, "timeline": timeline})
        self.assertNotIn("RAW_BUILD_REQUEST", encoded)
        self.assertNotIn("RAW_BUILD_OUTPUT", encoded)

    def test_tool_results_are_scoped_to_their_recovery_session(self) -> None:
        for sid in ("alpha", "beta"):
            self.session(sid)

        shared_call_id = "provider-reused-call-id"
        for sid, exit_code in (("alpha", 0), ("beta", 7)):
            self.event(sid, "command", "agent_turn")
            self.event(sid, "command", "tool_step")
            self.task_exchanges(
                sid,
                "command",
                {"messages": [{"role": "user", "content": "run it"}]},
                _response(
                    finish="tool_calls",
                    call_id=shared_call_id,
                    command="make release",
                ),
            )
            self.event(sid, "result", "agent_turn")
            self.event(
                sid,
                "result",
                "turn_end",
                data={"passed": exit_code == 0, "escalated": ""},
            )
            self.task_exchanges(
                sid,
                "result",
                {"messages": [{
                    "role": "tool",
                    "tool_call_id": shared_call_id,
                    "content": json.dumps({"ok": exit_code == 0, "exit_code": exit_code}),
                }]},
                _response(),
            )

        grouping = EndeavorGrouping(
            id="reused-call-id",
            title="Reused provider call ID",
            sessions=("alpha", "beta"),
        )
        with self.view(groupings=(grouping,)) as view:
            steps = view.timeline(
                "reused-call-id", collapse_polling=False, limit=10
            )["items"]

        command_steps = {
            step["session_id"]: step
            for step in steps
            if step["task_id"] == "command"
        }
        self.assertEqual(
            command_steps["alpha"]["tool_calls"][0]["result"]["exit_code"], 0
        )
        self.assertEqual(
            command_steps["beta"]["tool_calls"][0]["result"]["exit_code"], 7
        )
        self.assertEqual(command_steps["alpha"]["status"], "succeeded")
        self.assertEqual(command_steps["beta"]["status"], "failed")

    def test_consecutive_polling_and_repeated_warnings_are_folded(self) -> None:
        self.session("polls")
        warning = "bash: warning: cannot change locale (C.UTF-8)"
        secret_warning = "/private/build/token.c:99: warning: API_TOKEN=do-not-leak"
        messages = [{"role": "user", "content": "watch job"}]
        previous_response: dict | None = None
        previous_call: str | None = None

        for index in range(1, 4):
            if previous_response and previous_call:
                messages = messages + [
                    previous_response["choices"][0]["message"],
                    {"role": "tool", "tool_call_id": previous_call,
                     "content": json.dumps({
                         "ok": True, "exit_code": 0,
                         "stdout": (
                             f"still building {index}\n{warning}\n{secret_warning}\n"
                         ),
                     })},
                ]
            call_id = f"poll-{index}"
            response = _response(
                finish="tool_calls", call_id=call_id,
                command="tail -n 2 /tmp/release.log",
            )
            task = f"p{index}"
            self.event("polls", task, "agent_turn", tokens_in=100, cost=0.01)
            self.event("polls", task, "tool_step")
            self.task_exchanges("polls", task, {"messages": messages}, response)
            previous_response, previous_call = response, call_id

        # The fourth request supplies the third result and then terminates.
        messages = messages + [
            previous_response["choices"][0]["message"],
            {"role": "tool", "tool_call_id": previous_call,
             "content": json.dumps({
                 "ok": True, "exit_code": 0,
                 "stdout": f"still building 4\n{warning}\n{secret_warning}\n",
             })},
        ]
        self.event("polls", "final", "agent_turn")
        self.event("polls", "final", "agent_end")
        self.task_exchanges("polls", "final", {"messages": messages}, _response())

        with self.view() as view:
            folded = view.timeline("session:polls", limit=10)
            expanded = view.timeline(
                "session:polls", collapse_polling=False, limit=10
            )
        self.assertEqual(expanded["total"], 4)
        self.assertEqual(folded["total"], 2)
        self.assertEqual(folded["summary"]["collapsed_steps"], 2)
        group = folded["items"][0]
        self.assertEqual(group["type"], "poll_group")
        self.assertEqual(group["member_count"], 3)
        self.assertEqual(group["poll_categories"], {"log_tail": 3})
        self.assertAlmostEqual(group["cost_usd"], 0.03)
        locale_group = next(
            item for item in group["warning_groups"]
            if item["category"] == "locale_initialization"
        )
        self.assertEqual(locale_group["text"], "Locale initialization warning")
        self.assertEqual(locale_group["count"], 3)
        self.assertEqual(len(locale_group["fingerprint"]), 64)
        warning_group = next(
            item for item in folded["summary"]["warning_groups"]
            if item["category"] == "locale_initialization"
        )
        self.assertEqual(warning_group["count"], 3)
        self.assertEqual(warning_group["results"], 3)
        encoded = json.dumps(folded)
        self.assertNotIn("API_TOKEN", encoded)
        self.assertNotIn("/private/build", encoded)
        self.assertEqual(len(group["source_event_ids"]), 6)
        self.assertEqual(len(group["source_exchange_ids"]), 9)

        source_id = expanded["items"][0]["source_exchange_ids"][0]
        with self.view() as view:
            raw = view.raw_exchange(source_id)
        self.assertEqual(raw["id"], source_id)
        self.assertIn("payload", raw)

    def test_documented_netbsd_fixture_is_exact_and_controls_are_curated(self) -> None:
        anchor_kinds = {
            anchor.session: anchor.kind
            for anchor in NETBSD_ARM64_ENDEAVOR.acceptance_anchors
        }
        for index, sid in enumerate(NETBSD_ARM64_ENDEAVOR.sessions):
            self.session(sid, ts=2_000 + index)
            self.event(sid, f"task-{index}", "agent_turn", ts=2_100 + index)
            if sid in anchor_kinds:
                self.event(
                    sid, f"task-{index}", anchor_kinds[sid],
                    ts=2_200 + index, data={"passed": True, "escalated": ""},
                )
        for milestone in NETBSD_ARM64_ENDEAVOR.control_milestones:
            self.conn.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
                (milestone.ts, milestone.session, "-", "control", None, None,
                 0, 0, 0.0, json.dumps({"command": milestone.command})),
            )
        # Same command nearby must not be swept in by a broad time range.
        self.conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
            (NETBSD_ARM64_ENDEAVOR.control_milestones[0].ts + 0.1,
             "unrelated", "-", "control", None, None, 0, 0, 0.0,
             json.dumps({"command": "!gate off"})),
        )
        self.conn.commit()

        with self.view(fixture=True) as view:
            endeavor = view.get_endeavor(NETBSD_ARM64_ENDEAVOR.id)
            runs = view.list_runs(NETBSD_ARM64_ENDEAVOR.id, limit=20)["items"]
            timeline = view.timeline(
                NETBSD_ARM64_ENDEAVOR.id, collapse_polling=False, limit=50
            )
        self.assertEqual(endeavor["run_count"], 8)
        self.assertEqual(endeavor["control_event_count"], 7)
        self.assertEqual(endeavor["status"], "accepted")
        evidence = endeavor["metadata"]["evidence"]
        self.assertEqual(evidence["source_revision"], "netbsd-10")
        self.assertEqual(len(evidence["artifacts"]), 5)
        self.assertEqual(evidence["artifacts"][0]["bytes"], 303_656_165)
        self.assertEqual(
            {run["session_id"]: run["status"] for run in runs},
            dict(NETBSD_ARM64_ENDEAVOR.run_statuses),
        )
        controls = [item for item in timeline["items"] if item["type"] == "control"]
        self.assertEqual(len(controls), 7)
        self.assertNotIn("unrelated", {item["session_id"] for item in controls})
        self.assertTrue(all(item["source_event_ids"] for item in controls))

    def test_documented_fixture_is_unknown_when_incomplete(self) -> None:
        first = NETBSD_ARM64_ENDEAVOR.sessions[0]
        self.session(first)
        self.event(first, "partial", "agent_turn")

        with self.view(fixture=True) as view:
            endeavor = view.get_endeavor(NETBSD_ARM64_ENDEAVOR.id)

        self.assertEqual(endeavor["status"], "unknown")
        self.assertEqual(endeavor["session_count"], 1)
        self.assertEqual(endeavor["expected_session_count"], 8)
        self.assertEqual(endeavor["missing_session_count"], 7)
        self.assertFalse(endeavor["acceptance_anchors_satisfied"])

    def test_invalid_limits_and_grouping_conflicts_are_rejected(self) -> None:
        self.session("one")
        with self.view() as view:
            with self.assertRaises(ValueError):
                view.list_endeavors(limit=0)
            with self.assertRaises(ValueError):
                view.list_endeavors(limit=201)
            with self.assertRaises(ValueError):
                view.list_endeavors(cursor="not-a-cursor")
            with self.assertRaises(ValueError):
                view.raw_exchange(1 << 80)
            with self.assertRaises(ValueError):
                view.raw_exchange(-1)
        with self.assertRaises(ValueError):
            self.view(groupings=(
                EndeavorGrouping("a", "A", ("one",)),
                EndeavorGrouping("b", "B", ("one",)),
            ))
        with self.assertRaises(ValueError):
            self.view(groupings=(
                EndeavorGrouping(
                    "bad-anchor", "Bad anchor", ("one",),
                    acceptance_anchors=(AcceptanceAnchor("other", "turn_end"),),
                ),
            ))


if __name__ == "__main__":
    unittest.main()
