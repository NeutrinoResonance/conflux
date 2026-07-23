"""Durable per-run summary job ledger + incremental pending detection."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from llm_super import step_summary_backfill, summary_jobs


def _seed_step_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE exchanges (
             id INTEGER PRIMARY KEY, ts REAL, session TEXT, task TEXT,
             kind TEXT, model TEXT, payload TEXT
           )"""
    )
    conn.execute(
        "INSERT INTO exchanges VALUES (1, 1.0, 'session', 'kernel', "
        "'client_request', NULL, ?)",
        (json.dumps({"messages": [{"role": "user", "content": "Build it"}]}),),
    )
    conn.execute(
        "INSERT INTO exchanges VALUES (2, 2.0, 'session', 'kernel', "
        "'client_response', NULL, ?)",
        (json.dumps({"choices": [{"message": {
            "role": "assistant", "content": "Build succeeded."}}]}),),
    )
    conn.commit()
    conn.close()


def _fake_summarizer(batch, _model, _budget):
    return ([{
        "id": item["id"],
        "short_summary": "A build request elicited a successful result.",
        "node_label": "Build step",
        "long_summary": "The user asked for a build; the response reported "
                        "success and named the artifact.",
    } for item in batch], {"model": "test", "cost_usd": 0.02})


class SummaryJobLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "trace.db"
        _seed_step_db(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_successful_run_records_job_row(self) -> None:
        self.assertEqual(summary_jobs.pending_counts(self.db)["steps"], 1)
        result = summary_jobs.run_summary_job(
            self.db, "steps", trigger="incremental",
            summarizer=_fake_summarizer)
        self.assertEqual(result["generated"], 1)
        jobs = summary_jobs.list_jobs(self.db)
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["scope"], "steps")
        self.assertEqual(job["trigger"], "incremental")
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["generated"], 1)
        self.assertEqual(job["id"], result["job_id"])
        self.assertIsNotNone(job["finished_ts"])
        self.assertEqual(summary_jobs.pending_counts(self.db)["steps"], 0)

    def test_failed_run_is_recorded_and_reraised(self) -> None:
        def broken(batch, model, budget):
            raise step_summary_backfill.SummaryError("model refused")

        with self.assertRaises(step_summary_backfill.SummaryError):
            summary_jobs.run_summary_job(
                self.db, "steps", trigger="manual", summarizer=broken)
        job = summary_jobs.list_jobs(self.db)[0]
        self.assertEqual(job["status"], "failed")
        self.assertIn("model refused", job["error"])

    def test_unknown_scope_rejected(self) -> None:
        with self.assertRaises(ValueError):
            summary_jobs.run_summary_job(self.db, "everything")

    def test_second_run_generates_nothing_but_is_still_ledgered(self) -> None:
        summary_jobs.run_summary_job(
            self.db, "steps", summarizer=_fake_summarizer)
        result = summary_jobs.run_summary_job(
            self.db, "steps", summarizer=_fake_summarizer)
        self.assertEqual(result["generated"], 0)
        jobs = summary_jobs.list_jobs(self.db)
        self.assertEqual(len(jobs), 2)
        self.assertTrue(all(j["status"] == "succeeded" for j in jobs))


if __name__ == "__main__":
    unittest.main()
