import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from jiraia.sprint_reconciliation import reconcile


class FakeJira:
    url = "https://jiraia.atlassian.net"

    def __init__(
        self,
        sprints=None,
        *,
        complete=True,
        details=None,
    ):
        self.sprints = (
            [
                {"id": 2, "name": "SCRUM Sprint 0"},
                {"id": 1, "name": "SCRUM Sprint 1"},
                {"id": 3, "name": "SCRUM Sprint 2"},
            ]
            if sprints is None
            else sprints
        )

        self.complete = complete

        self.details = details or {
            "id": 3,
            "name": "SCRUM Sprint 2",
            "state": "future",
            "originBoardId": 1,
        }

        self.calls = []

    def get(self, endpoint):
        self.calls.append(endpoint)

        if endpoint == "/rest/agile/1.0/board/1":
            return {
                "id": 1,
                "name": "SCRUM board",
                "location": {"projectKey": "SCRUM"},
            }

        if endpoint.startswith(
            "/rest/agile/1.0/board/1/sprint?"
        ):
            params = parse_qs(
                urlsplit(endpoint).query
            )

            start = int(params["startAt"][0])

            if self.complete:
                return {
                    "isLast": True,
                    "startAt": start,
                    "values": self.sprints,
                }

            return {
                "isLast": False,
                "startAt": start,
                "values": [],
            }

        if endpoint == "/rest/agile/1.0/sprint/3":
            return self.details

        raise AssertionError("GET inesperado")

    def post(self, *args, **kwargs):
        raise AssertionError("POST proibido")


class ReconciliationTests(unittest.TestCase):

    def test_get_only_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "proposals"
            fake = FakeJira()

            result = reconcile(
                fake,
                store=store,
            )

            self.assertEqual(result["sprint_id"], 3)
            self.assertFalse(
                result["executed_by_jiraia"]
            )
            self.assertFalse(
                (Path(tmp) / "reconciliations").exists()
            )
            self.assertEqual(len(fake.calls), 3)

    def test_local_record_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "proposals"

            first = reconcile(
                FakeJira(),
                store=store,
                record=True,
            )

            second = reconcile(
                FakeJira(),
                store=store,
                record=True,
            )

            self.assertEqual(
                first["local_record"],
                "CREATED",
            )
            self.assertEqual(
                second["local_record"],
                "ALREADY_EXISTS",
            )

            evidence = json.loads(
                Path(first["record_path"]).read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(
                evidence["status"],
                "EXTERNAL_SPRINT_OBSERVED",
            )

    def test_missing_sprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                ValueError,
                "ausente",
            ):
                reconcile(
                    FakeJira(sprints=[]),
                    store=Path(tmp) / "proposals",
                    record=True,
                )

            self.assertFalse(
                (Path(tmp) / "reconciliations").exists()
            )

    def test_wrong_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                ValueError,
                "ID",
            ):
                reconcile(
                    FakeJira(sprints=[
                        {
                            "id": 5,
                            "name": "SCRUM Sprint 2",
                        }
                    ]),
                    store=Path(tmp) / "proposals",
                )

    def test_duplicate_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeJira(sprints=[
                {"id": 3, "name": "SCRUM Sprint 2"},
                {"id": 4, "name": " scrum sprint 2 "},
            ])

            with self.assertRaisesRegex(
                ValueError,
                "duplicado",
            ):
                reconcile(
                    fake,
                    store=Path(tmp) / "proposals",
                )

    def test_incomplete_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                ValueError,
                "Paginacao",
            ):
                reconcile(
                    FakeJira(complete=False),
                    store=Path(tmp) / "proposals",
                )

    def test_changed_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeJira(details={
                "id": 3,
                "name": "SCRUM Sprint 2",
                "state": "future",
                "originBoardId": 9,
            })

            with self.assertRaisesRegex(
                ValueError,
                "Detalhes",
            ):
                reconcile(
                    fake,
                    store=Path(tmp) / "proposals",
                )

    def test_wrong_site(self):
        fake = FakeJira()
        fake.url = "https://other.example.com"

        with self.assertRaisesRegex(
            ValueError,
            "Instancia",
        ):
            reconcile(fake)

        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
