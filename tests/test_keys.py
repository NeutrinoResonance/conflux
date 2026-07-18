from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm_super import keys


class TryRefreshTests(unittest.TestCase):
    def test_non_hermes_source_is_not_refreshed(self) -> None:
        with patch("subprocess.run") as run:
            self.assertFalse(keys.try_refresh("opencode:opencode-go"))
        run.assert_not_called()

    def test_nous_requires_shared_oauth_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            with patch.object(keys, "HERMES_SHARED_NOUS_AUTH", missing), \
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
                    patch("subprocess.run", return_value=completed) as run:
                self.assertTrue(keys.try_refresh("hermes:nous", timeout=30))

        command = run.call_args.args[0]
        self.assertEqual(command[:5],
                         ["hermes", "auth", "add", "nous", "--type"])
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
                    patch("subprocess.run", return_value=completed):
                self.assertFalse(keys.try_refresh("hermes:nous"))


if __name__ == "__main__":
    unittest.main()
