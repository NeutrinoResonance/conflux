from __future__ import annotations

import sqlite3
from types import SimpleNamespace
import unittest

from llm_super.export import library_message_summaries


class ExportedMessageSummariesTest(unittest.TestCase):
    def test_optional_summary_tables_are_exported_with_source_pointer(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE message_summaries (
              input_sha256 TEXT, prompt_version TEXT, role TEXT,
              headline TEXT, summary TEXT, generator TEXT, model TEXT,
              source_chars INTEGER, created_ts REAL,
              PRIMARY KEY (input_sha256, prompt_version)
            );
            CREATE TABLE message_summary_sources (
              exchange_id INTEGER, json_pointer TEXT, boundary TEXT,
              ordinal INTEGER, task TEXT, role TEXT, tool_call_id TEXT,
              input_sha256 TEXT, prompt_version TEXT, ts REAL, session TEXT,
              PRIMARY KEY (exchange_id, json_pointer)
            );
            """
        )
        conn.execute(
            "INSERT INTO message_summaries VALUES (?,?,?,?,?,?,?,?,?)",
            ("hash", "v1", "user", "Build NetBSD", "Cross-compile it.",
             "claude-cli", "sonnet", 20, 2.0),
        )
        conn.execute(
            "INSERT INTO message_summary_sources VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (7, "/messages/0", "client_request", 0, "task-1", "user", None,
             "hash", "v1", 1.0, "session-1"),
        )

        rows = library_message_summaries(SimpleNamespace(_conn=conn), "session-1")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exchange_id"], 7)
        self.assertEqual(rows[0]["json_pointer"], "/messages/0")
        self.assertEqual(rows[0]["headline"], "Build NetBSD")
        self.assertEqual(rows[0]["model"], "sonnet")

    def test_database_without_summary_tables_exports_an_empty_list(self) -> None:
        conn = sqlite3.connect(":memory:")
        self.assertEqual(
            library_message_summaries(SimpleNamespace(_conn=conn), "session-1"),
            [],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
