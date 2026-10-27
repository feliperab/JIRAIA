"""Testes offline de reserva unica por board/nome."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jiraia.target_ledger import claim_target
from jiraia.attempt_ledger import reserve_attempt
from jiraia.execution_guard import execution_phrase
from test_executor import FakeJira, create_fixture

ID1 = "0123456789abcdef"
ID2 = "fedcba9876543210"
DIGEST = "a" * 64


def request(name="SCRUM Sprint 2", board=1):
    return {
        "method": "POST",
        "endpoint": "/rest/agile/1.0/sprint",
        "payload": {"name": name, "originBoardId": board},
    }


class TargetLedgerTests(unittest.TestCase):
    def test_one_reservation_creates_one_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = claim_target(tmp, ID1, DIGEST, request())
            self.assertEqual(record["status"], "TARGET_RESERVED")
            self.assertIs(record["retry_allowed"], False)
            files = list((Path(tmp) / "target_claims").glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertEqual(
                json.loads(files[0].read_text(encoding="utf-8"))["proposal_id"],
                ID1,
            )

    def test_two_proposals_same_target_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            claim_target(tmp, ID1, DIGEST, request())
            with self.assertRaisesRegex(ValueError, "Repeticao bloqueada"):
                claim_target(tmp, ID2, "b" * 64, request())
            self.assertEqual(
                len(list((Path(tmp) / "target_claims").glob("*.json"))), 1
            )

    def test_casefold_collision_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            claim_target(tmp, ID1, DIGEST, request("SCRUM Sprint 2"))
            with self.assertRaises(ValueError):
                claim_target(tmp, ID2, DIGEST, request("scrum sprint 2"))

    def test_other_board_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            claim_target(tmp, ID1, DIGEST, request(board=1))
            claim_target(tmp, ID2, DIGEST, request(board=2))
            self.assertEqual(
                len(list((Path(tmp) / "target_claims").glob("*.json"))), 2
            )

    def test_other_name_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            claim_target(tmp, ID1, DIGEST, request("Sprint A"))
            claim_target(tmp, ID2, DIGEST, request("Sprint B"))
            self.assertEqual(
                len(list((Path(tmp) / "target_claims").glob("*.json"))), 2
            )

    def test_invalid_endpoint_fails_without_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            op = request()
            op["endpoint"] = "/rest/api/3/issue"
            with self.assertRaises(ValueError):
                claim_target(tmp, ID1, DIGEST, op)
            self.assertFalse((Path(tmp) / "target_claims").exists())

    def test_invalid_payload_fails_without_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            op = request()
            op["payload"]["goal"] = "NAO PERMITIDO"
            with self.assertRaises(ValueError):
                claim_target(tmp, ID1, DIGEST, op)
            self.assertFalse((Path(tmp) / "target_claims").exists())

    def test_invalid_proposal_identifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                claim_target(tmp, "../outro", DIGEST, request())
            self.assertFalse((Path(tmp) / "target_claims").exists())

    def test_integration_two_distinct_proposals(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = create_fixture(tmp)
            second = create_fixture(tmp)
            self.assertNotEqual(first.stem, second.stem)
            jira = FakeJira()
            confirmation1 = execution_phrase(first.stem, "SCRUM Sprint 2")
            confirmation2 = execution_phrase(second.stem, "SCRUM Sprint 2")
            with patch("urllib.request.urlopen") as urlopen:
                first_result = reserve_attempt(
                    first, jira, confirmation1, store=tmp
                )
                self.assertEqual(first_result["status"], "RESERVED")
                with self.assertRaisesRegex(ValueError, "Repeticao bloqueada"):
                    reserve_attempt(second, jira, confirmation2, store=tmp)
                urlopen.assert_not_called()
            self.assertTrue(
                (Path(tmp) / "attempts" / (first.stem + ".json")).is_file()
            )
            self.assertFalse(
                (Path(tmp) / "attempts" / (second.stem + ".json")).exists()
            )
            self.assertEqual(
                len(list((Path(tmp) / "target_claims").glob("*.json"))), 1
            )
            self.assertFalse((Path(tmp) / "real_dispatch").exists())

    def test_wrong_confirmation_cannot_claim_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            with self.assertRaises(PermissionError):
                reserve_attempt(path, FakeJira(), "NAO AUTORIZADO", store=tmp)
            self.assertFalse((Path(tmp) / "target_claims").exists())


if __name__ == "__main__":
    unittest.main()
