"""Offline tests for local-only attempt marker diagnostics."""
import json
import tempfile
import unittest
from pathlib import Path
from jiraia.audit_status import inspect_local

PID = "1234567890abcdef"
HASH = "a" * 64
REQUEST = {"method": "POST", "endpoint": "/rest/agile/1.0/sprint", "payload": {"name": "Example Sprint", "originBoardId": 1}}


def write(store, folder, record):
    path = Path(store) / folder / (PID + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def attempt():
    return {"proposal_id": PID, "proposal_sha256": HASH, "operation": "create_sprint", "request": REQUEST, "status": "RESERVED"}


def dispatch():
    return {"proposal_id": PID, "proposal_sha256": HASH, "operation": "create_sprint", "request": REQUEST, "status": "POST_MAY_HAVE_BEEN_SENT", "retry_allowed": False}


def success():
    return {"proposal_id": PID, "status": "SUCCESS_VERIFIED", "sprint_id": 9, "sprint_name": "Example Sprint", "origin_board_id": 1, "retry_allowed": False}


class AuditTests(unittest.TestCase):
    def test_empty_no_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "proposals"
            self.assertEqual(inspect_local(store)["attempts"], [])
            self.assertFalse(store.exists())

    def test_reserved_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "attempts", attempt())
            self.assertEqual(inspect_local(tmp)["attempts"][0]["status"], "RESERVED_NO_DISPATCH_MARKER")

    def test_dispatch_without_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "attempts", attempt())
            write(tmp, "real_dispatch", dispatch())
            self.assertEqual(inspect_local(tmp)["attempts"][0]["status"], "DISPATCH_OUTCOME_MISSING")

    def test_unknown_after_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "attempts", attempt())
            write(tmp, "real_dispatch", dispatch())
            write(tmp, "real_outcomes", {"proposal_id": PID, "status": "UNKNOWN_NEEDS_RECONCILIATION", "sprint_id_candidate": None, "retry_allowed": False, "next_action": "VERIFY_JIRA_BEFORE_NEW_PROPOSAL"})
            self.assertEqual(inspect_local(tmp)["attempts"][0]["status"], "UNKNOWN_NEEDS_RECONCILIATION")

    def test_success_after_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "attempts", attempt())
            write(tmp, "real_dispatch", dispatch())
            write(tmp, "real_outcomes", success())
            self.assertEqual(inspect_local(tmp)["attempts"][0]["status"], "SUCCESS_RECORDED_LOCALLY")

    def test_orphan_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "real_outcomes", success())
            self.assertEqual(inspect_local(tmp)["attempts"][0]["status"], "INCONSISTENT_LOCAL_RECORDS")

    def test_mismatched_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "attempts", attempt())
            record = dispatch()
            record["proposal_sha256"] = "b" * 64
            write(tmp, "real_dispatch", record)
            self.assertEqual(inspect_local(tmp)["attempts"][0]["status"], "INCONSISTENT_LOCAL_RECORDS")

    def test_malformed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "attempts" / (PID + ".json")
            path.parent.mkdir()
            path.write_text("{invalid", encoding="utf-8")
            self.assertEqual(inspect_local(tmp)["attempts"][0]["status"], "INCONSISTENT_LOCAL_RECORDS")

    def test_external_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "proposals"
            path = Path(tmp) / "reconciliations" / "create_sprint-board_1-sprint_3.json"
            path.parent.mkdir()
            path.write_text(json.dumps({"status": "EXTERNAL_SPRINT_OBSERVED", "board_id": 1, "sprint_id": 3, "jira_requests": "GET_ONLY", "executed_by_jiraia": False}), encoding="utf-8")
            data = inspect_local(store)
            self.assertEqual(data["reconciliations"][0]["status"], "EXTERNAL_OBSERVATION_RECORDED")


if __name__ == "__main__":
    unittest.main()
