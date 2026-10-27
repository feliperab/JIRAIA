import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jiraia.client import JiraClient
from jiraia.execution_guard import execution_phrase
from jiraia.execution_pipeline import run_offline_once
from test_executor import FakeJira, create_fixture


def phrase_for(path):
    return execution_phrase(
        path.stem,
        "SCRUM Sprint 2",
    )


class ExecutionPipelineTests(unittest.TestCase):

    @patch("urllib.request.urlopen")
    @patch.object(JiraClient, "post")
    def test_success_without_network(self, post, urlopen):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            result = run_offline_once(
                path,
                FakeJira(),
                phrase_for(path),
                "success",
                store=tmp,
            )

            self.assertEqual(
                result["status"],
                "SIMULATED_SUCCESS",
            )
            self.assertFalse(result["http_sent"])
            self.assertFalse(result["executed"])
            self.assertEqual(
                result["fake_response"]["id"],
                999001,
            )

            attempt = Path(tmp) / "attempts" / (
                path.stem + ".json"
            )
            marker = Path(tmp) / "dispatch_previews" / (
                path.stem + ".json"
            )
            outcome = Path(tmp) / "simulated_outcomes" / (
                path.stem + ".json"
            )

            self.assertTrue(attempt.is_file())
            self.assertTrue(marker.is_file())
            self.assertTrue(outcome.is_file())

            marker_data = json.loads(
                marker.read_text(encoding="utf-8")
            )
            self.assertFalse(marker_data["network_allowed"])

            post.assert_not_called()
            urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    @patch.object(JiraClient, "post")
    def test_unknown_no_retry(self, post, urlopen):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            result = run_offline_once(
                path,
                FakeJira(),
                phrase_for(path),
                "unknown",
                store=tmp,
            )

            self.assertEqual(
                result["status"],
                "SIMULATED_UNKNOWN",
            )
            self.assertEqual(
                result["next_action"],
                "VERIFY_JIRA_MANUALLY_NO_AUTO_RETRY",
            )

            post.assert_not_called()
            urlopen.assert_not_called()

    def test_duplicate_attempt_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            phrase = phrase_for(path)

            run_offline_once(
                path, FakeJira(), phrase,
                "success", store=tmp,
            )

            with self.assertRaisesRegex(
                ValueError, "Repeticao bloqueada"
            ):
                run_offline_once(
                    path, FakeJira(), phrase,
                    "success", store=tmp,
                )

    def test_wrong_confirmation_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            with self.assertRaises(PermissionError):
                run_offline_once(
                    path,
                    FakeJira(),
                    "CONFIRMACAO_ERRADA",
                    "success",
                    store=tmp,
                )

            self.assertFalse(
                (Path(tmp) / "attempts").exists()
            )

    def test_interruption_stays_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            phrase = phrase_for(path)

            with self.assertRaisesRegex(
                RuntimeError, "Interrupcao simulada"
            ):
                run_offline_once(
                    path, FakeJira(), phrase,
                    "interrupt", store=tmp,
                )

            self.assertTrue(
                (
                    Path(tmp) / "attempts" /
                    f"{path.stem}.json"
                ).is_file()
            )

            self.assertFalse(
                (
                    Path(tmp) / "simulated_outcomes" /
                    f"{path.stem}.json"
                ).exists()
            )

            with self.assertRaisesRegex(
                ValueError, "Repeticao bloqueada"
            ):
                run_offline_once(
                    path, FakeJira(), phrase,
                    "success", store=tmp,
                )

    def test_invalid_scenario_no_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            with self.assertRaisesRegex(
                ValueError, "Cenario"
            ):
                run_offline_once(
                    path,
                    FakeJira(),
                    phrase_for(path),
                    "real",
                    store=tmp,
                )

            self.assertFalse(
                (Path(tmp) / "attempts").exists()
            )


if __name__ == "__main__":
    unittest.main()