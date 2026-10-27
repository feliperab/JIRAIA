import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jiraia.client import JiraClient
from jiraia.attempt_ledger import reserve_attempt
from jiraia.execution_guard import execution_phrase
from test_executor import FakeJira, create_fixture


def confirmation_for(path):
    return execution_phrase(path.stem, "SCRUM Sprint 2")


class AttemptLedgerTests(unittest.TestCase):

    @patch("urllib.request.urlopen")
    @patch.object(JiraClient, "post")
    def test_reserves_without_http(self, post, urlopen):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            result = reserve_attempt(
                path,
                FakeJira(),
                confirmation_for(path),
                store=tmp,
            )

            self.assertEqual(result["status"], "RESERVED")
            self.assertEqual(
                result["outcome"],
                "NOT_EXECUTED_BY_THIS_VERSION",
            )
            self.assertTrue(
                (
                    Path(tmp) / "attempts" /
                    f"{path.stem}.json"
                ).is_file()
            )

            post.assert_not_called()
            urlopen.assert_not_called()

    def test_duplicate_reservation_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            phrase = confirmation_for(path)

            reserve_attempt(
                path, FakeJira(), phrase, store=tmp
            )

            with self.assertRaisesRegex(
                ValueError, "Repeticao bloqueada"
            ):
                reserve_attempt(
                    path, FakeJira(), phrase, store=tmp
                )

    def test_wrong_confirmation_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            with self.assertRaises(PermissionError):
                reserve_attempt(
                    path, FakeJira(), "EXECUTAR",
                    store=tmp,
                )

            self.assertFalse(
                (Path(tmp) / "attempts").exists()
            )

    def test_expired_proposal_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp, expired=True)

            with self.assertRaisesRegex(
                ValueError, "expirada"
            ):
                reserve_attempt(
                    path,
                    FakeJira(),
                    confirmation_for(path),
                    store=tmp,
                )

            self.assertFalse(
                (Path(tmp) / "attempts").exists()
            )

    def test_board_change_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            changed = FakeJira([
                "SCRUM Sprint 0",
                "SCRUM Sprint 1",
                "SCRUM Sprint 3",
            ])

            with self.assertRaisesRegex(
                ValueError, "mudou"
            ):
                reserve_attempt(
                    path,
                    changed,
                    confirmation_for(path),
                    store=tmp,
                )

            self.assertFalse(
                (Path(tmp) / "attempts").exists()
            )


if __name__ == "__main__":
    unittest.main()