from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from conflux import keys


class TryRefreshTests(unittest.TestCase):
    def test_non_hermes_source_is_not_refreshed(self) -> None:
        with patch("subprocess.run") as run:
            self.assertFalse(keys.try_refresh("opencode:opencode-go"))
        run.assert_not_called()

    def test_nous_requires_shared_oauth_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            with patch.object(keys, "HERMES_SHARED_NOUS_AUTH", missing), \
                    patch.object(keys, "HERMES_PYTHON", missing), \
                    patch("subprocess.run") as run:
                self.assertFalse(keys.try_refresh("hermes:nous"))
        run.assert_not_called()

    def test_nous_uses_forced_hermes_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory) / "nous_auth.json"
            shared.write_text("{}")
            completed = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout='Imported nous OAuth credentials: "device_code"\n',
                stderr="",
            )
            with patch.object(keys, "HERMES_SHARED_NOUS_AUTH", shared), \
                    patch.object(keys, "HERMES_PYTHON", Path(directory) / "none"), \
                    patch("subprocess.run", return_value=completed) as run:
                self.assertTrue(keys.try_refresh("hermes:nous", timeout=30))

        command = run.call_args.args[0]
        self.assertEqual(Path(command[0]).name, "hermes")
        self.assertEqual(command[1:5], ["auth", "add", "nous", "--type"])
        self.assertIn("--no-browser", command)
        self.assertEqual(run.call_args.kwargs["input"], "\n")
        self.assertEqual(run.call_args.kwargs["timeout"], 30)

    def test_status_only_output_does_not_claim_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory) / "nous_auth.json"
            shared.write_text("{}")
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="nous: logged in\n", stderr="")
            with patch.object(keys, "HERMES_SHARED_NOUS_AUTH", shared), \
                    patch.object(keys, "HERMES_PYTHON", Path(directory) / "none"), \
                    patch("subprocess.run", return_value=completed):
                self.assertFalse(keys.try_refresh("hermes:nous"))

    def test_nous_prefers_noninteractive_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory) / "python"
            python.write_text("")
            ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            with patch.object(keys, "HERMES_PYTHON", python), \
                    patch("subprocess.run", return_value=ok) as run:
                self.assertTrue(keys.try_refresh("hermes:nous"))
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertEqual(command[0], str(python))
        self.assertIn("force_refresh=True", command[2])


class ProactiveRefreshTests(unittest.TestCase):
    def _auth(self, directory: str, key: str, expires_in: timedelta) -> Path:
        path = Path(directory) / "auth.json"
        expires = (datetime.now(timezone.utc) + expires_in).isoformat()
        path.write_text(json.dumps({"providers": {"nous": {
            "agent_key": key, "agent_key_expires_at": expires}}}))
        return path

    def test_fresh_key_is_returned_without_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            auth = self._auth(directory, "k1", timedelta(minutes=40))
            with patch.object(keys, "HERMES_AUTH", auth), \
                    patch("subprocess.run") as run:
                self.assertEqual(keys.resolve("hermes:nous"), "k1")
        run.assert_not_called()

    def test_expiring_key_is_renewed_before_use(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            auth = self._auth(directory, "old", timedelta(minutes=2))
            python = Path(directory) / "python"
            python.write_text("")

            def renew(*args, **kwargs):
                self._auth(directory, "new", timedelta(minutes=60))
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

            with patch.object(keys, "HERMES_AUTH", auth), \
                    patch.object(keys, "HERMES_PYTHON", python), \
                    patch("subprocess.run", side_effect=renew):
                self.assertEqual(keys.resolve("hermes:nous"), "new")

    def test_failed_renewal_falls_back_to_current_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            auth = self._auth(directory, "old", timedelta(minutes=2))
            with patch.object(keys, "HERMES_AUTH", auth), \
                    patch.object(keys, "HERMES_PYTHON", Path(directory) / "none"):
                self.assertEqual(keys.resolve("hermes:nous"), "old")


if __name__ == "__main__":
    unittest.main()
