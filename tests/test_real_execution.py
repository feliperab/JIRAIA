import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jiraia.real_execution import (
    execute_create_sprint_once,
)
from jiraia.execution_guard import execution_phrase
from test_executor import FakeJira, create_fixture


class FakeWriter(FakeJira):
    def __init__(self, mode="success", store=None):
        super().__init__()
        self.mode = mode
        self.store = Path(store) if store else None
        self.post_calls = 0

    def post(self, endpoint, payload, *, allow_write=False):
        self.post_calls += 1

        assert allow_write is True
        assert endpoint == "/rest/agile/1.0/sprint"

        if self.store:
            markers = list(
                (self.store / "real_dispatch").glob("*.json")
            )
            assert len(markers) == 1, (
                "POST chamado antes do marcador"
            )

        if self.mode == "network_error":
            raise RuntimeError("Conexao ficticia perdida")

        if self.mode == "invalid_response":
            return {
                "id": 321,
                "name": "Outra Sprint",
                "state": "future",
                "originBoardId": 1,
            }

        return {
            "id": 321,
            "name": payload["name"],
            "state": "future",
            "originBoardId": payload["originBoardId"],
        }

    def get(self, endpoint):
        if endpoint == "/rest/agile/1.0/sprint/321":
            if self.mode == "verification_error":
                raise RuntimeError(
                    "Falha ficticia de verificacao"
                )

            return {
                "id": 321,
                "name": "SCRUM Sprint 2",
                "state": "future",
                "originBoardId": 1,
            }

        return super().get(endpoint)


def confirmation_for(path):
    return execution_phrase(
        path.stem, "SCRUM Sprint 2"
    )


def execute_fixture(path, jira, folder, enabled=True):
    return execute_create_sprint_once(
        path,
        jira,
        confirmation_for(path),
        enable_real_write=enabled,
        store=folder,
    )


class RealExecutionTests(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_default_blocks_all_writes(self, urlopen):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            jira = FakeWriter(store=tmp)

            with self.assertRaises(PermissionError):
                execute_fixture(
                    path, jira, tmp, enabled=False
                )

            self.assertEqual(jira.post_calls, 0)
            self.assertFalse(
                (Path(tmp) / "attempts").exists()
            )
            urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_success_verified_offline(self, urlopen):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            jira = FakeWriter(store=tmp)

            result = execute_fixture(path, jira, tmp)

            self.assertEqual(
                result["status"], "SUCCESS_VERIFIED"
            )
            self.assertEqual(result["sprint_id"], 321)
            self.assertEqual(jira.post_calls, 1)
            self.assertTrue(
                (
                    Path(tmp) / "real_dispatch" /
                    f"{path.stem}.json"
                ).is_file()
            )
            self.assertTrue(
                (
                    Path(tmp) / "real_outcomes" /
                    f"{path.stem}.json"
                ).is_file()
            )
            urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_network_error_no_retry(self, urlopen):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            jira = FakeWriter(
                "network_error", store=tmp
            )

            result = execute_fixture(path, jira, tmp)

            self.assertEqual(
                result["status"],
                "UNKNOWN_NEEDS_RECONCILIATION",
            )
            self.assertFalse(result["retry_allowed"])
            self.assertEqual(jira.post_calls, 1)

            with self.assertRaises(ValueError):
                execute_fixture(path, jira, tmp)

            self.assertEqual(jira.post_calls, 1)
            urlopen.assert_not_called()

    def test_invalid_response_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            jira = FakeWriter(
                "invalid_response", store=tmp
            )

            result = execute_fixture(path, jira, tmp)

            self.assertEqual(
                result["status"],
                "UNKNOWN_NEEDS_RECONCILIATION",
            )
            self.assertEqual(jira.post_calls, 1)

    def test_verification_failure_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            jira = FakeWriter(
                "verification_error", store=tmp
            )

            result = execute_fixture(path, jira, tmp)

            self.assertEqual(
                result["status"],
                "UNKNOWN_NEEDS_RECONCILIATION",
            )
            self.assertEqual(
                result["sprint_id_candidate"], 321
            )
            self.assertEqual(jira.post_calls, 1)

    def test_wrong_confirmation_no_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            jira = FakeWriter(store=tmp)

            with self.assertRaises(PermissionError):
                execute_create_sprint_once(
                    path,
                    jira,
                    "CONFIRMACAO_ERRADA",
                    enable_real_write=True,
                    store=tmp,
                )

            self.assertEqual(jira.post_calls, 0)
            self.assertFalse(
                (Path(tmp) / "real_dispatch").exists()
            )

    def test_board_change_no_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            jira = FakeWriter(store=tmp)
            jira.names = [
                "SCRUM Sprint 0",
                "SCRUM Sprint 1",
                "SCRUM Sprint 3",
            ]

            with self.assertRaises(ValueError):
                execute_fixture(path, jira, tmp)

            self.assertEqual(jira.post_calls, 0)

    def test_duplicate_success_no_second_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            jira = FakeWriter(store=tmp)

            execute_fixture(path, jira, tmp)

            with self.assertRaises(ValueError):
                execute_fixture(path, jira, tmp)

            self.assertEqual(jira.post_calls, 1)


if __name__ == "__main__":
    unittest.main()