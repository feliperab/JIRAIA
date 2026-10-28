import os
import tempfile
import unittest
from pathlib import Path

from jiraia.native_write import select_proposal


class NativeProposalSelectionTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.store = self.base / "propostas"
        self.store.mkdir()

    def create(self, name):
        path = self.store / name
        path.write_text("{}", encoding="utf-8")
        return path

    def test_explicit_valid_proposal(self):
        path = self.create("a" * 16 + ".json")
        self.assertEqual(
            select_proposal(path, store=self.store),
            path.resolve(),
        )

    def test_selects_latest_proposal(self):
        first = self.create("a" * 16 + ".json")
        second = self.create("b" * 16 + ".json")
        os.utime(first, ns=(1600000000000000000,) * 2)
        os.utime(second, ns=(1700000000000000000,) * 2)
        self.assertEqual(
            select_proposal(store=self.store),
            second.resolve(),
        )

    def test_empty_store_blocked(self):
        with self.assertRaises(ValueError):
            select_proposal(store=self.store)

    def test_invalid_filename_blocked(self):
        path = self.create("arquivo.json")
        with self.assertRaises(ValueError):
            select_proposal(path, store=self.store)

    def test_outside_store_blocked(self):
        path = self.base / ("a" * 16 + ".json")
        path.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            select_proposal(path, store=self.store)

    def test_missing_proposal_blocked(self):
        path = self.store / ("a" * 16 + ".json")
        with self.assertRaises(ValueError):
            select_proposal(path, store=self.store)

    def test_directory_is_not_proposal(self):
        path = self.store / ("a" * 16 + ".json")
        path.mkdir()
        with self.assertRaises(ValueError):
            select_proposal(path, store=self.store)

    def test_traversal_blocked(self):
        outside = self.base / ("c" * 16 + ".json")
        outside.write_text("{}", encoding="utf-8")
        path = self.store / ".." / outside.name
        with self.assertRaises(ValueError):
            select_proposal(path, store=self.store)

    def test_ignores_invalid_newer_file(self):
        valid = self.create("a" * 16 + ".json")
        invalid = self.create("nao_validado.json")
        os.utime(valid, ns=(1600000000000000000,) * 2)
        os.utime(invalid, ns=(1700000000000000000,) * 2)
        self.assertEqual(
            select_proposal(store=self.store),
            valid.resolve(),
        )
