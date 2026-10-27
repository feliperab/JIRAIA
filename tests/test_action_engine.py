import json
import tempfile
import unittest
from pathlib import Path

from jiraia.action_engine import (
    build_create_sprint,
    save_proposal,
    read_proposal,
)


class FakeJira:
    def get(self, endpoint):
        if endpoint == "/rest/agile/1.0/board/1":
            return {"id": 1, "name": "SCRUM board"}

        if "/sprint?" in endpoint:
            return {
                "isLast": True,
                "values": [
                    {"name": "SCRUM Sprint 0"},
                    {"name": "SCRUM Sprint 1"},
                ],
            }

        raise AssertionError("Endpoint inesperado")


class ActionEngineTests(unittest.TestCase):
    def test_create_proposal(self):
        proposal = build_create_sprint(
            FakeJira(), 1, "SCRUM Sprint 2"
        )
        self.assertEqual(proposal["operation"], "create_sprint")
        self.assertEqual(proposal["state"], "PENDING_APPROVAL")

    def test_duplicate_name(self):
        with self.assertRaises(ValueError):
            build_create_sprint(
                FakeJira(), 1, "SCRUM Sprint 1"
            )

    def test_integrity(self):
        proposal = build_create_sprint(
            FakeJira(), 1, "SCRUM Sprint 2"
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = save_proposal(proposal, tmp)
            loaded, _ = read_proposal(path)
            self.assertEqual(loaded, proposal)

            envelope = json.loads(
                Path(path).read_text(encoding="utf-8")
            )
            envelope["proposal"]["parameters"]["name"] = "Alterada"

            Path(path).write_text(
                json.dumps(envelope), encoding="utf-8"
            )

            with self.assertRaises(ValueError):
                read_proposal(path)


if __name__ == "__main__":
    unittest.main()