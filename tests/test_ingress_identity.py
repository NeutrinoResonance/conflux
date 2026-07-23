"""Explicit conversation/endeavor identity at the OpenAI-compatible ingress."""

from __future__ import annotations

import unittest

from fastapi import HTTPException

from llm_super import proxy


class _Request:
    def __init__(self, headers: dict | None = None):
        self.headers = headers or {}


MESSAGES = [{"role": "user", "content": "hello"}]


class ConversationResolutionTests(unittest.TestCase):
    def test_hash_fallback_without_explicit_id(self) -> None:
        session, explicit = proxy._resolve_conversation(
            _Request(), {}, MESSAGES)
        self.assertEqual(session, proxy._session_id(MESSAGES))
        self.assertFalse(explicit)

    def test_header_wins_over_hash(self) -> None:
        session, explicit = proxy._resolve_conversation(
            _Request({"x-llm-super-conversation": "conv-42"}), {}, MESSAGES)
        self.assertEqual(session, "conv-42")
        self.assertTrue(explicit)

    def test_body_field_wins_over_hash(self) -> None:
        session, explicit = proxy._resolve_conversation(
            _Request(), {"conversation_id": "ticket.1234"}, MESSAGES)
        self.assertEqual(session, "ticket.1234")
        self.assertTrue(explicit)

    def test_header_beats_body(self) -> None:
        session, _ = proxy._resolve_conversation(
            _Request({"x-llm-super-conversation": "from-header"}),
            {"conversation_id": "from-body"}, MESSAGES)
        self.assertEqual(session, "from-header")

    def test_invalid_explicit_id_is_rejected_not_degraded(self) -> None:
        for bad in ("a b", "x" * 200, "-leading-dash", "id\n@"):
            with self.assertRaises(HTTPException, msg=repr(bad)):
                proxy._resolve_conversation(
                    _Request(), {"conversation_id": bad}, MESSAGES)

    def test_blank_explicit_id_means_absent(self) -> None:
        for blank in ("", "  "):
            session, explicit = proxy._resolve_conversation(
                _Request(), {"conversation_id": blank}, MESSAGES)
            self.assertFalse(explicit)
            self.assertEqual(session, proxy._session_id(MESSAGES))

    def test_explicit_id_is_stable_across_first_message_edits(self) -> None:
        edited = [{"role": "user", "content": "hello EDITED"}]
        a, _ = proxy._resolve_conversation(
            _Request({"x-llm-super-conversation": "conv-42"}), {}, MESSAGES)
        b, _ = proxy._resolve_conversation(
            _Request({"x-llm-super-conversation": "conv-42"}), {}, edited)
        self.assertEqual(a, b)
        # ... unlike the hash fallback, which forks:
        self.assertNotEqual(proxy._session_id(MESSAGES),
                            proxy._session_id(edited))

    def test_endeavor_id_validated_same_way(self) -> None:
        self.assertEqual(
            proxy._explicit_id(_Request({"x-llm-super-endeavor": "goal-7"}),
                               {}, "x-llm-super-endeavor", "endeavor_id"),
            "goal-7")
        self.assertIsNone(
            proxy._explicit_id(_Request(), {}, "x-llm-super-endeavor",
                               "endeavor_id"))
        with self.assertRaises(HTTPException):
            proxy._explicit_id(_Request(), {"endeavor_id": "bad id"},
                               "x-llm-super-endeavor", "endeavor_id")


if __name__ == "__main__":
    unittest.main()
