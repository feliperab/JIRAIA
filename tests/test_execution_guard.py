import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jiraia.execution_guard import (
    execution_phrase,
    simulate_once,
)
from test_executor import FakeJira, create_fixture


class ExecutionGuardTests(unittest.TestCase):

    def test_requires_final_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            with self.assertRaises(PermissionError):
                simulate_once(
                    path,
                    FakeJira(),
                    "APROVAR",
                    store=tmp,
                )

            self.assertFalse(
                (Path(tmp) / "simulations").exists()
            )

    @patch("urllib.request.urlopen")
    def test_simulation_without_network(self, urlopen):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            proposal_id = path.stem

            phrase = execution_phrase(
                proposal_id, "SCRUM Sprint 2"
            )

            result = simulate_once(
                path, FakeJira(), phrase, store=tmp
            )

            self.assertEqual(
                result["status"], "SIMULATED_ONLY"
            )
            self.assertFalse(result["executed"])
            self.assertFalse(result["http_sent"])
            self.assertTrue(
                (Path(tmp) / "simulations" /
                 f"{proposal_id}.json").is_file()
            )

            urlopen.assert_not_called()

    def test_duplicate_execution_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            phrase = execution_phrase(
                path.stem, "SCRUM Sprint 2"
            )

            simulate_once(
                path, FakeJira(), phrase, store=tmp
            )

            with self.assertRaisesRegex(
                ValueError, "Repeticao bloqueada"
            ):
                simulate_once(
                    path, FakeJira(), phrase, store=tmp
                )

    def test_expired_approval_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp, expired=True)
            phrase = execution_phrase(
                path.stem, "SCRUM Sprint 2"
            )

            with self.assertRaisesRegex(
                ValueError, "expirada"
            ):
                simulate_once(
                    path, FakeJira(), phrase, store=tmp
                )


if __name__ == "__main__":
    unittest.main()