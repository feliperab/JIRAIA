import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jiraia.attempt_ledger import reserve_attempt
from jiraia.client import JiraClient
from jiraia.execution_guard import execution_phrase
from jiraia.outcome_simulator import (
    record_simulated_outcome,
)
from test_executor import FakeJira, create_fixture


FAKE_SUCCESS = {
    "id": 321,
    "name": "SCRUM Sprint 2",
    "state": "future",
    "originBoardId": 1,
}


def reserve_fixture(folder):
    path = create_fixture(folder)

    confirmation = execution_phrase(
        path.stem, "SCRUM Sprint 2"
    )

    reserve_attempt(
        path,
        FakeJira(),
        confirmation,
        store=folder,
    )

    return path.stem


class OutcomeSimulatorTests(unittest.TestCase):

    @patch("urllib.request.urlopen")
    @patch.object(JiraClient, "post")
    def test_simulated_success_without_http(
        self, post, urlopen
    ):
        with tempfile.TemporaryDirectory() as tmp:
            proposal_id = reserve_fixture(tmp)

            result = record_simulated_outcome(
                tmp,
                proposal_id,
                "success",
                fake_response=FAKE_SUCCESS,
            )

            self.assertEqual(
                result["status"], "SIMULATED_SUCCESS"
            )
            self.assertFalse(result["executed"])
            self.assertFalse(result["http_sent"])
            self.assertEqual(
                result["fake_response"]["id"], 321
            )

            post.assert_not_called()
            urlopen.assert_not_called()

    def test_unknown_result_requires_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            proposal_id = reserve_fixture(tmp)

            result = record_simulated_outcome(
                tmp, proposal_id, "unknown"
            )

            self.assertEqual(
                result["status"], "SIMULATED_UNKNOWN"
            )
            self.assertEqual(
                result["next_action"],
                "VERIFY_JIRA_MANUALLY_NO_AUTO_RETRY",
            )
            self.assertIsNone(result["fake_response"])
            self.assertFalse(result["http_sent"])

    def test_duplicate_outcome_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            proposal_id = reserve_fixture(tmp)

            record_simulated_outcome(
                tmp, proposal_id, "unknown"
            )

            with self.assertRaisesRegex(
                ValueError, "Repeticao bloqueada"
            ):
                record_simulated_outcome(
                    tmp,
                    proposal_id,
                    "success",
                    fake_response=FAKE_SUCCESS,
                )

    def test_missing_reservation_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                ValueError, "nao encontrada"
            ):
                record_simulated_outcome(
                    tmp, "0" * 16, "unknown"
                )

    def test_wrong_success_response_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            proposal_id = reserve_fixture(tmp)

            wrong_response = dict(FAKE_SUCCESS)
            wrong_response["name"] = "Outra Sprint"

            with self.assertRaisesRegex(
                ValueError, "Resposta ficticia"
            ):
                record_simulated_outcome(
                    tmp,
                    proposal_id,
                    "success",
                    fake_response=wrong_response,
                )

            self.assertFalse(
                (
                    Path(tmp) / "simulated_outcomes" /
                    f"{proposal_id}.json"
                ).exists()
            )

    def test_invalid_proposal_id_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                ValueError, "ID de proposta invalido"
            ):
                record_simulated_outcome(
                    tmp, "../outra-pasta", "unknown"
                )


if __name__ == "__main__":
    unittest.main()