"""Offline tests for the separate, explicitly authorized native writer."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jiraia.client import JiraClient
from jiraia.execution_guard import execution_phrase
from jiraia.native_write import (
    _post_one_future_sprint,
    _require_site,
    _validate_payload,
    execute_approved_once,
    main,
)
from test_executor import FakeJira, create_fixture


class FakeReadJira(FakeJira):
    def __init__(self, mode="success", names=None):
        super().__init__(names=names)
        self.mode = mode
        self.verifications = 0

    def get(self, endpoint):
        if endpoint == "/rest/agile/1.0/sprint/321":
            self.verifications += 1
            if self.mode == "verification_error":
                raise RuntimeError("Fictitious verification failure")
            return {
                "id": 321, "name": "SCRUM Sprint 2",
                "originBoardId": 1, "state": "future",
            }
        return super().get(endpoint)


def phrase(path):
    return execution_phrase(path.stem, "SCRUM Sprint 2")


def success_sender(calls, store):
    def send(jira, payload):
        calls.append(payload.copy())
        markers = list((Path(store) / "real_dispatch").glob("*.json"))
        assert len(markers) == 1, "POST before dispatch marker"
        assert payload == {"name": "SCRUM Sprint 2", "originBoardId": 1}
        return {
            "id": 321, "name": "SCRUM Sprint 2",
            "originBoardId": 1, "state": "future",
        }
    return send


class NativeWriteTests(unittest.TestCase):
    def test_success_one_dispatch_and_read_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            calls = []
            jira = FakeReadJira()
            with patch("jiraia.native_write.urlopen") as network:
                result = execute_approved_once(
                    path, jira, phrase(path), store=tmp,
                    send=success_sender(calls, tmp),
                )
                network.assert_not_called()
            self.assertEqual(result["status"], "SUCCESS_VERIFIED")
            self.assertEqual(result["sprint_id"], 321)
            self.assertEqual(len(calls), 1)
            self.assertEqual(jira.verifications, 1)
            self.assertTrue((Path(tmp) / "real_dispatch" / (path.stem + ".json")).exists())
            self.assertTrue((Path(tmp) / "real_outcomes" / (path.stem + ".json")).exists())
            self.assertEqual(len(list((Path(tmp) / "target_claims").glob("*.json"))), 1)

    def test_second_execution_never_sends(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            calls = []
            writer = success_sender(calls, tmp)
            execute_approved_once(path, FakeReadJira(), phrase(path), store=tmp, send=writer)
            with self.assertRaisesRegex(ValueError, "Repeticao bloqueada"):
                execute_approved_once(path, FakeReadJira(), phrase(path), store=tmp, send=writer)
            self.assertEqual(len(calls), 1)

    def test_wrong_final_phrase_creates_no_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            with self.assertRaises(PermissionError):
                execute_approved_once(path, FakeReadJira(), "ERRADO", store=tmp,
                                      send=lambda *_: self.fail("POST called"))
            self.assertFalse((Path(tmp) / "target_claims").exists())

    def test_duplicate_at_preflight_creates_no_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            duplicate = FakeReadJira(names=["SCRUM Sprint 0", "SCRUM Sprint 1", "SCRUM Sprint 2"])
            with self.assertRaisesRegex(ValueError, "Ja existe"):
                execute_approved_once(path, duplicate, phrase(path), store=tmp,
                                      send=lambda *_: self.fail("POST called"))
            self.assertFalse((Path(tmp) / "target_claims").exists())

    def test_sender_network_error_results_unknown_not_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            count = []
            def fail(*_):
                count.append(1)
                raise ConnectionError("simulated")
            result = execute_approved_once(path, FakeReadJira(), phrase(path), store=tmp, send=fail)
            self.assertEqual(result["status"], "UNKNOWN_NEEDS_RECONCILIATION")
            self.assertEqual(count, [1])
            self.assertIs(result["retry_allowed"], False)

    def test_mismatch_post_result_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            result = execute_approved_once(
                path, FakeReadJira(), phrase(path), store=tmp,
                send=lambda *_: {"id": 321, "name": "OTHER", "originBoardId": 1, "state": "future"},
            )
            self.assertEqual(result["status"], "UNKNOWN_NEEDS_RECONCILIATION")

    def test_failed_get_verification_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            result = execute_approved_once(path, FakeReadJira(mode="verification_error"),
                                           phrase(path), store=tmp,
                                           send=success_sender([], tmp))
            self.assertEqual(result["status"], "UNKNOWN_NEEDS_RECONCILIATION")
            self.assertEqual(result["sprint_id_candidate"], 321)

    def test_site_must_match(self):
        with self.assertRaises(PermissionError):
            _require_site(JiraClient("https://another.atlassian.net", "user", "fake"))
        with self.assertRaises(PermissionError):
            _require_site(JiraClient("http://jiraia.atlassian.net", "user", "fake"))
        _require_site(JiraClient("https://jiraia.atlassian.net", "user", "fake"))

    def test_payload_must_be_future_sprint_on_board_one(self):
        with self.assertRaises(PermissionError):
            _validate_payload({"name": "Sprint", "originBoardId": 2})
        with self.assertRaises(PermissionError):
            _validate_payload({"name": "Sprint", "originBoardId": 1, "goal": "extra"})

    def test_authorized_transport_issues_exactly_one_post(self):
        jira = JiraClient("https://jiraia.atlassian.net", "nobody@example.com", "FAKE")
        class Response:
            status = 201
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self, *_):
                return json.dumps({"id": 321}).encode()
        with patch("jiraia.native_write.urlopen", return_value=Response()) as http:
            result = _post_one_future_sprint(jira, {"name": "SCRUM Sprint 3", "originBoardId": 1})
        self.assertEqual(result["id"], 321)
        self.assertEqual(http.call_count, 1)
        request = http.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "https://jiraia.atlassian.net/rest/agile/1.0/sprint")
        self.assertEqual(json.loads(request.data), {"name": "SCRUM Sprint 3", "originBoardId": 1})

    def test_execute_requires_terminal_before_any_request(self):
        with patch("jiraia.native_write.sys.stdin") as stdin, \
             patch("jiraia.native_write.JiraClient.from_env") as client:
            stdin.isatty.return_value = False
            with self.assertRaises(PermissionError):
                main(["nonexistent.json", "--execute"])
            client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
