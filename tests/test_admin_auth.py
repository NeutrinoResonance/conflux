"""Control-plane authentication: disabled by default, one setting to enable.

When enabled, every /admin/* route — including the action-decision
endpoints — requires the operator token; the OpenAI-compatible /v1 ingress
and the dashboard HTML shells stay reachable so a tokened visit can set the
browser cookie.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from conflux import config as config_mod
from conflux import proxy
from conflux.config import AdminAuth


class _FakeAdmin:
    def __init__(self, token):
        self.token = token
        self.enabled = bool(token)


class _FakeCfg:
    def __init__(self, token):
        self.admin = _FakeAdmin(token)


class AdminAuthMiddlewareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_state = dict(proxy.state)
        proxy.state.clear()
        self.client = TestClient(proxy.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        proxy.state.clear()
        proxy.state.update(self.old_state)

    def test_disabled_by_default_admin_routes_do_not_require_token(self) -> None:
        proxy.state["cfg"] = _FakeCfg(None)
        response = self.client.get("/admin/status")
        # Reaches the handler (which may 500 without full state) — never 401.
        self.assertNotEqual(response.status_code, 401)

    def test_enabled_blocks_admin_routes_without_token(self) -> None:
        proxy.state["cfg"] = _FakeCfg("sekrit")
        for path in ("/admin/status", "/admin/events", "/admin/jobs",
                     "/admin/actions/abc/decision"):
            response = (self.client.post(path, json={"decision": "approve"})
                        if path.endswith("/decision")
                        else self.client.get(path))
            self.assertEqual(response.status_code, 401, path)

    def test_enabled_accepts_bearer_and_custom_header(self) -> None:
        proxy.state["cfg"] = _FakeCfg("sekrit")
        for headers in ({"Authorization": "Bearer sekrit"},
                        {"X-Conflux-Token": "sekrit"}):
            response = self.client.get("/admin/status", headers=headers)
            self.assertNotEqual(response.status_code, 401, headers)

    def test_wrong_token_is_rejected(self) -> None:
        proxy.state["cfg"] = _FakeCfg("sekrit")
        response = self.client.get(
            "/admin/status", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(response.status_code, 401)

    def test_query_token_sets_dashboard_cookie(self) -> None:
        proxy.state["cfg"] = _FakeCfg("sekrit")
        response = self.client.get("/", params={"token": "sekrit"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.cookies.get("conflux_admin"), "sekrit")
        follow_up = self.client.get("/admin/status")
        self.assertNotEqual(follow_up.status_code, 401)

    def test_v1_ingress_and_dashboard_shells_stay_reachable(self) -> None:
        proxy.state["cfg"] = _FakeCfg("sekrit")
        self.assertNotEqual(self.client.get("/v1/models").status_code, 401)
        for page in ("/", "/history", "/graphs", "/workspace"):
            self.assertNotEqual(self.client.get(page).status_code, 401, page)


class AdminAuthConfigTests(unittest.TestCase):
    def _write_minimal_config(self, tmp: str, admin_block: str = "") -> Path:
        path = Path(tmp) / "models.yaml"
        path.write_text(
            "providers:\n"
            "  p:\n"
            "    base_url: http://localhost\n"
            "    key_source: none\n"
            "models:\n"
            "  m:\n"
            "    provider: p\n"
            "    id: m\n"
            "    family: f\n"
            + admin_block
        )
        return path

    def test_default_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("CONFLUX_ADMIN_TOKEN", None)
                cfg = config_mod.load(self._write_minimal_config(tmp))
        self.assertFalse(cfg.admin.enabled)
        self.assertIsNone(cfg.admin.token)

    def test_yaml_token_enables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("CONFLUX_ADMIN_TOKEN", None)
                cfg = config_mod.load(self._write_minimal_config(
                    tmp, "admin:\n  token: hunter2\n"))
        self.assertTrue(cfg.admin.enabled)
        self.assertEqual(cfg.admin.token, "hunter2")

    def test_env_token_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ, {"CONFLUX_ADMIN_TOKEN": "env-token"}
            ):
                cfg = config_mod.load(self._write_minimal_config(
                    tmp, "admin:\n  token: hunter2\n"))
        self.assertEqual(cfg.admin.token, "env-token")

    def test_dataclass_default(self) -> None:
        self.assertFalse(AdminAuth().enabled)


if __name__ == "__main__":
    unittest.main()
