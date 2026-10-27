"""Testes locais de diagnostico de reservas por destino."""

import json
import tempfile
import unittest
from pathlib import Path

from jiraia.target_ledger import claim_target
from jiraia.target_audit import inspect_target_claims
from jiraia.audit_status import inspect_local

PID = "1234567890abcdef"
SHA = "a" * 64
REQUEST = {
    "method": "POST",
    "endpoint": "/rest/agile/1.0/sprint",
    "payload": {"name": "SCRUM Sprint 4", "originBoardId": 1},
}


def attempt(request=None, digest=SHA):
    return {
        "proposal_id": PID,
        "proposal_sha256": digest,
        "operation": "create_sprint",
        "status": "RESERVED",
        "request": REQUEST if request is None else request,
    }


class TargetAuditTests(unittest.TestCase):
    def test_absent_folder_is_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "proposals"
            self.assertEqual(inspect_target_claims(store, {}), [])
            self.assertFalse(store.exists())

    def test_reservation_without_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "proposals"
            claim_target(store, PID, SHA, REQUEST)
            records = inspect_target_claims(store, {})
            self.assertEqual(records[0]["status"], "TARGET_RESERVED_NO_ATTEMPT")
            self.assertIs(records[0]["retry_allowed"], False)

    def test_reservation_matches_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "proposals"
            claim_target(store, PID, SHA, REQUEST)
            records = inspect_target_claims(store, {PID: attempt()})
            self.assertEqual(records[0]["status"], "TARGET_RESERVED_WITH_ATTEMPT")

    def test_request_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "proposals"
            claim_target(store, PID, SHA, REQUEST)
            wrong = dict(REQUEST)
            wrong["payload"] = {"name": "Other", "originBoardId": 1}
            self.assertEqual(
                inspect_target_claims(store, {PID: attempt(wrong)})[0]["status"],
                "TARGET_CLAIM_ATTEMPT_MISMATCH",
            )

    def test_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "proposals"
            claim_target(store, PID, SHA, REQUEST)
            self.assertEqual(
                inspect_target_claims(store, {PID: attempt(digest="b" * 64)})[0]["status"],
                "TARGET_CLAIM_ATTEMPT_MISMATCH",
            )

    def test_filename_key_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "proposals"
            claim_target(store, PID, SHA, REQUEST)
            path = next((store / "target_claims").glob("*.json"))
            path.rename(path.with_name("0" * 64 + ".json"))
            self.assertEqual(
                inspect_target_claims(store, {})[0]["status"],
                "INVALID_TARGET_CLAIM",
            )

    def test_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "proposals" / "target_claims"
            store.mkdir(parents=True)
            (store / ("1" * 64 + ".json")).write_text("{no", encoding="utf-8")
            self.assertEqual(
                inspect_target_claims(store.parent, {})[0]["status"],
                "INVALID_TARGET_CLAIM",
            )

    def test_audit_summary_includes_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "proposals"
            claim_target(store, PID, SHA, REQUEST)
            summary = inspect_local(store)
            self.assertEqual(
                summary["target_claims"][0]["status"],
                "TARGET_RESERVED_NO_ATTEMPT",
            )

    def test_invalid_retry_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "proposals"
            claim_target(store, PID, SHA, REQUEST)
            path = next((store / "target_claims").glob("*.json"))
            content = json.loads(path.read_text(encoding="utf-8"))
            content["retry_allowed"] = True
            path.write_text(json.dumps(content), encoding="utf-8")
            self.assertEqual(
                inspect_target_claims(store, {})[0]["status"],
                "INVALID_TARGET_CLAIM",
            )


if __name__ == "__main__":
    unittest.main()
