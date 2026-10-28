"""Testes offline do preflight paginado ate o executor."""

import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from jiraia.attempt_ledger import reserve_attempt
from jiraia.execution_guard import execution_phrase
from jiraia.executor import prepare_execution
from test_executor import FakeJira, create_fixture


class PagedJira(FakeJira):
    def __init__(self, pages):
        super().__init__()
        self.pages = pages
        self.read_calls = []
        self.post_calls = 0

    def get(self, endpoint):
        self.read_calls.append(endpoint)

        if endpoint.startswith(
            "/rest/agile/1.0/board/1/sprint?"
        ):
            query = parse_qs(
                urlsplit(endpoint).query
            )

            assert query["state"] == [
                "active,future,closed"
            ]
            assert query["maxResults"] == ["50"]

            start = int(query["startAt"][0])
            return self.pages[start]

        return super().get(endpoint)

    def post(self, *args, **kwargs):
        self.post_calls += 1
        raise AssertionError(
            "POST proibido neste teste"
        )


def pages_ok():
    return {
        0: {
            "startAt": 0,
            "isLast": False,
            "values": [
                {"name": "SCRUM Sprint 0"}
            ],
        },
        1: {
            "startAt": 1,
            "isLast": True,
            "total": 2,
            "values": [
                {"name": "SCRUM Sprint 1"}
            ],
        },
    }


def confirmation(path):
    return execution_phrase(
        path.stem, "SCRUM Sprint 2"
    )


class WriteGuardIntegrationTests(unittest.TestCase):

    def test_paginated_preflight_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            jira = PagedJira(pages_ok())

            result = prepare_execution(
                path, jira, store=tmp
            )

            self.assertTrue(
                result["board_revalidated"]
            )

            offsets = [
                parse_qs(
                    urlsplit(url).query
                )["startAt"][0]
                for url in jira.read_calls
                if "/sprint?" in url
            ]

            self.assertEqual(
                offsets, ["0", "1"]
            )
            self.assertEqual(jira.post_calls, 0)

    def test_reservation_is_local_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            jira = PagedJira(pages_ok())

            result = reserve_attempt(
                path,
                jira,
                confirmation(path),
                store=tmp,
            )

            self.assertEqual(
                result["status"], "RESERVED"
            )
            self.assertEqual(jira.post_calls, 0)

            self.assertTrue(
                (
                    Path(tmp) / "attempts" /
                    f"{path.stem}.json"
                ).is_file()
            )

            self.assertFalse(
                (Path(tmp) / "real_dispatch").exists()
            )

    def test_duplicate_second_page_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            pages = pages_ok()

            pages[1]["values"] = [
                {"name": " SCRUM Sprint 2 "}
            ]

            jira = PagedJira(pages)

            with self.assertRaisesRegex(
                ValueError, "Ja existe"
            ):
                reserve_attempt(
                    path,
                    jira,
                    confirmation(path),
                    store=tmp,
                )

            self.assertFalse(
                (Path(tmp) / "attempts").exists()
            )
            self.assertEqual(jira.post_calls, 0)

    def test_closed_duplicate_blocks_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            jira = PagedJira({
                0: {
                    "isLast": True,
                    "values": [{
                        "name": "SCRUM Sprint 2",
                        "state": "closed",
                    }],
                }
            })

            with self.assertRaisesRegex(
                ValueError, "Ja existe"
            ):
                reserve_attempt(
                    path,
                    jira,
                    confirmation(path),
                    store=tmp,
                )

            self.assertEqual(jira.post_calls, 0)

            self.assertFalse(
                (Path(tmp) / "attempts").exists()
            )

            self.assertFalse(
                (Path(tmp) / "real_dispatch").exists()
            )

    def test_incomplete_page_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            jira = PagedJira({
                0: {"values": []}
            })

            with self.assertRaisesRegex(
                RuntimeError, "incompleta"
            ):
                reserve_attempt(
                    path,
                    jira,
                    confirmation(path),
                    store=tmp,
                )

            self.assertFalse(
                (Path(tmp) / "attempts").exists()
            )

    def test_inconsistent_total_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            jira = PagedJira({
                0: {
                    "isLast": True,
                    "total": 7,
                    "values": [
                        {"name": "SCRUM Sprint 0"}
                    ],
                }
            })

            with self.assertRaisesRegex(
                RuntimeError, "inconsistente"
            ):
                reserve_attempt(
                    path,
                    jira,
                    confirmation(path),
                    store=tmp,
                )

            self.assertFalse(
                (Path(tmp) / "attempts").exists()
            )

    def test_empty_intermediate_page_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            jira = PagedJira({
                0: {
                    "isLast": False,
                    "values": [],
                }
            })

            with self.assertRaisesRegex(
                RuntimeError, "vazia"
            ):
                reserve_attempt(
                    path,
                    jira,
                    confirmation(path),
                    store=tmp,
                )

            self.assertFalse(
                (Path(tmp) / "attempts").exists()
            )

    def test_repeat_reservation_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            jira = PagedJira(pages_ok())

            reserve_attempt(
                path,
                jira,
                confirmation(path),
                store=tmp,
            )

            with self.assertRaisesRegex(
                ValueError, "Repeticao bloqueada"
            ):
                reserve_attempt(
                    path,
                    jira,
                    confirmation(path),
                    store=tmp,
                )

            self.assertEqual(jira.post_calls, 0)

            self.assertEqual(
                len(list(
                    (Path(tmp) / "attempts").glob(
                        "*.json"
                    )
                )),
                1,
            )


if __name__ == "__main__":
    unittest.main()
