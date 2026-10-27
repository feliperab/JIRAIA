import unittest
from urllib.parse import parse_qs, urlsplit

from jiraia.action_engine import build_create_sprint
from jiraia.sprint_inventory import list_sprint_names


class FakeJira:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, endpoint):
        self.calls.append(endpoint)

        if endpoint == "/rest/agile/1.0/board/1":
            return {"id": 1, "name": "SCRUM board"}

        if "/board/1/sprint?" not in endpoint:
            raise AssertionError("Endpoint inesperado")

        params = parse_qs(urlsplit(endpoint).query)

        assert params["state"] == ["active,future,closed"]
        assert params["maxResults"] == ["50"]

        return self.pages[int(params["startAt"][0])]


class InventoryTests(unittest.TestCase):
    def test_one_page(self):
        jira = FakeJira({0: {
            "isLast": True, "startAt": 0, "total": 1,
            "values": [{"name": "Sprint 0"}],
        }})
        self.assertEqual(list_sprint_names(jira, 1), ["Sprint 0"])

    def test_two_pages(self):
        jira = FakeJira({
            0: {
                "isLast": False,
                "values": [{"name": "Sprint 0"}],
            },
            1: {
                "isLast": True,
                "total": 2,
                "values": [{"name": "Sprint 1"}],
            },
        })
        self.assertEqual(
            list_sprint_names(jira, 1),
            ["Sprint 0", "Sprint 1"],
        )
        self.assertEqual(len(jira.calls), 2)

    def test_closed_duplicate_blocks_proposal(self):
        jira = FakeJira({0: {
            "isLast": True,
            "values": [{"name": "SCRUM Sprint 2"}],
        }})
        with self.assertRaisesRegex(ValueError, "Ja existe"):
            build_create_sprint(jira, 1, "SCRUM Sprint 2")

    def test_duplicate_second_page_blocks_proposal(self):
        jira = FakeJira({
            0: {
                "isLast": False,
                "values": [{"name": "Sprint 0"}],
            },
            1: {
                "isLast": True,
                "values": [{"name": " scrum sprint 2 "}],
            },
        })
        with self.assertRaisesRegex(ValueError, "Ja existe"):
            build_create_sprint(jira, 1, "SCRUM Sprint 2")

    def test_missing_is_last_blocks(self):
        jira = FakeJira({0: {"values": []}})
        with self.assertRaisesRegex(RuntimeError, "incompleta"):
            list_sprint_names(jira, 1)

    def test_empty_intermediate_page_blocks(self):
        jira = FakeJira({0: {
            "isLast": False, "values": [],
        }})
        with self.assertRaisesRegex(RuntimeError, "vazia"):
            list_sprint_names(jira, 1)

    def test_inconsistent_offset_blocks(self):
        jira = FakeJira({0: {
            "isLast": True, "startAt": 99, "values": [],
        }})
        with self.assertRaisesRegex(RuntimeError, "inconsistente"):
            list_sprint_names(jira, 1)

    def test_inconsistent_total_blocks(self):
        jira = FakeJira({0: {
            "isLast": True, "total": 5, "values": [],
        }})
        with self.assertRaisesRegex(RuntimeError, "inconsistente"):
            list_sprint_names(jira, 1)


if __name__ == "__main__":
    unittest.main()
