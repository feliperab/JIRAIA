import json
import tempfile
import unittest

from jiraia.native_write import matches_sprint, persist_once


class NativeWriteRetainedGuardsTests(unittest.TestCase):

    def setUp(self):
        self.payload = {"name": "Sprint de teste", "originBoardId": 1}
        self.data = {
            "id": 42,
            "name": "Sprint de teste",
            "originBoardId": 1,
            "state": "future",
        }

    def test_persist_creates_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = persist_once(
                folder, "audit", "abc", {"status": "prepared"}
            )
            with path.open(encoding="utf-8") as file:
                self.assertEqual(
                    json.load(file), {"status": "prepared"}
                )

    def test_persist_rejects_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            persist_once(folder, "audit", "abc", {"value": 1})
            with self.assertRaises(ValueError):
                persist_once(folder, "audit", "abc", {"value": 2})

    def test_duplicate_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = persist_once(
                folder, "audit", "abc", {"value": 1}
            )
            with self.assertRaises(ValueError):
                persist_once(
                    folder, "audit", "abc", {"value": 99}
                )
            with path.open(encoding="utf-8") as file:
                self.assertEqual(json.load(file), {"value": 1})

    def test_persist_allows_distinct_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            first = persist_once(
                folder, "audit", "abc", {"value": 1}
            )
            second = persist_once(
                folder, "audit", "def", {"value": 2}
            )
            self.assertNotEqual(first, second)

    def test_matches_valid_future_sprint(self):
        self.assertTrue(
            matches_sprint(self.data, 42, self.payload)
        )

    def test_rejects_wrong_id(self):
        self.assertFalse(
            matches_sprint(self.data, 43, self.payload)
        )

    def test_rejects_wrong_name(self):
        data = {**self.data, "name": "Outra sprint"}
        self.assertFalse(
            matches_sprint(data, 42, self.payload)
        )

    def test_rejects_wrong_board(self):
        data = {**self.data, "originBoardId": 99}
        self.assertFalse(
            matches_sprint(data, 42, self.payload)
        )

    def test_rejects_non_future_state(self):
        data = {**self.data, "state": "active"}
        self.assertFalse(
            matches_sprint(data, 42, self.payload)
        )

    def test_rejects_boolean_id(self):
        data = {**self.data, "id": True}
        self.assertFalse(
            matches_sprint(data, True, self.payload)
        )


if __name__ == "__main__":
    unittest.main()
