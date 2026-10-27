import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jiraia.action_engine import (
    build_create_sprint,
    checksum,
    save_proposal,
)
from jiraia.executor import prepare_execution


class FakeJira:
    def __init__(self, names=None):
        self.names = names or [
            "SCRUM Sprint 0",
            "SCRUM Sprint 1",
        ]

    def get(self, endpoint):
        if endpoint == "/rest/agile/1.0/board/1":
            return {"id": 1, "name": "SCRUM board"}

        if endpoint.startswith(
            "/rest/agile/1.0/board/1/sprint?"
        ):
            return {
                "isLast": True,
                "values": [
                    {"name": name} for name in self.names
                ],
            }

        raise AssertionError("Endpoint inesperado")


def create_fixture(folder, expired=False):
    proposal = build_create_sprint(
        FakeJira(), 1, "SCRUM Sprint 2"
    )

    if expired:
        proposal["created_at"] = (
            datetime.now(timezone.utc)
            - timedelta(minutes=31)
        ).isoformat()

    path = save_proposal(proposal, folder)

    receipt = {
        "proposal_id": proposal["id"],
        "proposal_sha256": checksum(proposal),
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "status": "APPROVED_FOR_FUTURE_REVALIDATION",
        "executed": False,
    }

    path.with_suffix(".approval.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )

    return path


class ExecutorTests(unittest.TestCase):
    def test_valid_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            result = prepare_execution(
                path, FakeJira(), store=tmp
            )
            self.assertTrue(result["approval_validated"])
            self.assertFalse(result["executed"])
            self.assertFalse(result["ready_to_execute"])

    def test_expired_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp, expired=True)

            with self.assertRaisesRegex(ValueError, "expirada"):
                prepare_execution(
                    path, FakeJira(), store=tmp
                )

    def test_board_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            modified = FakeJira([
                "SCRUM Sprint 0",
                "SCRUM Sprint 1",
                "SCRUM Sprint 3",
            ])

            with self.assertRaisesRegex(ValueError, "mudou"):
                prepare_execution(
                    path, modified, store=tmp
                )

    def test_modified_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            receipt_path = path.with_suffix(
                ".approval.json"
            )
            receipt = json.loads(
                receipt_path.read_text(encoding="utf-8")
            )
            receipt["proposal_sha256"] = "0" * 64
            receipt_path.write_text(
                json.dumps(receipt), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "Hash"):
                prepare_execution(
                    path, FakeJira(), store=tmp
                )


if __name__ == "__main__":
    unittest.main()