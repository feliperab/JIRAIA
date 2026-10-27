"""Integration tests: full approve → execute → audit lifecycle.

Complements test_native_write.py (unit tests per path) and test_audit_status.py
(unit tests for audit markers) by validating the end-to-end pipeline:

  proposal fixture  →  execute_approved_once  →  inspect_local

No real HTTP is ever issued: all POST calls go through the `send` injection and
all GET calls are served by FakeReadJira (which extends FakeJira from
test_executor.py, already used across the suite).

Scenarios covered
-----------------
* Full success → inspect_local reports SUCCESS_RECORDED_LOCALLY
* Network failure → UNKNOWN, retry_allowed=False, audit matches
* Missing approval file → blocked before any marker is created
* Expired proposal → blocked before any marker is created
* Cross-proposal target reservation → second proposal blocked at claim_target
* Sprint duplicate on page 2 → blocked before any marker (paginated GET)
* Second execution after success → blocked, audit unchanged
* Fresh store → no side-effects
"""

import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from jiraia.audit_status import inspect_local
from jiraia.execution_guard import execution_phrase
from jiraia.native_write import execute_approved_once
from jiraia.target_ledger import claim_target
from test_executor import FakeJira, create_fixture


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class FakeReadJira(FakeJira):
    """Extends FakeJira with GET support for the post-create sprint verification."""

    def get(self, endpoint):
        if endpoint == "/rest/agile/1.0/sprint/321":
            return {
                "id": 321,
                "name": "SCRUM Sprint 2",
                "originBoardId": 1,
                "state": "future",
            }
        return super().get(endpoint)


class PagedFakeJira(FakeJira):
    """FakeJira whose sprint list spans two pages."""

    def __init__(self, page0_names, page1_names):
        # super().__init__ sets self.names but is overridden below
        super().__init__(names=[])
        self._page0 = page0_names
        self._page1 = page1_names

    def get(self, endpoint):
        if endpoint == "/rest/agile/1.0/board/1":
            return {"id": 1, "name": "SCRUM board"}
        if endpoint.startswith("/rest/agile/1.0/board/1/sprint?"):
            query = parse_qs(urlsplit(endpoint).query)
            start = int(query["startAt"][0])
            if start == 0:
                return {
                    "isLast": False,
                    "startAt": 0,
                    "values": [{"name": n} for n in self._page0],
                }
            n0, n1 = len(self._page0), len(self._page1)
            return {
                "isLast": True,
                "startAt": start,
                "total": n0 + n1,
                "values": [{"name": n} for n in self._page1],
            }
        raise AssertionError(f"Endpoint inesperado: {endpoint}")


class PagedFakeReadJira(PagedFakeJira):
    """PagedFakeJira that also handles the post-create sprint GET."""

    def get(self, endpoint):
        if endpoint == "/rest/agile/1.0/sprint/321":
            return {
                "id": 321,
                "name": "SCRUM Sprint 2",
                "originBoardId": 1,
                "state": "future",
            }
        return super().get(endpoint)


def phrase_for(path, name="SCRUM Sprint 2"):
    return execution_phrase(path.stem, name)


def success_sender():
    """Returns a sender that simulates a successful POST response."""
    def _send(jira, payload):
        return {
            "id": 321,
            "name": payload["name"],
            "originBoardId": payload["originBoardId"],
            "state": "future",
        }
    return _send


def failing_sender():
    """Returns a sender that always raises a network error."""
    def _send(jira, payload):
        raise ConnectionError("simulated network failure")
    return _send


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class FullLifecycleTests(unittest.TestCase):

    # ------------------------------------------------------------------
    # Audit output after success
    # ------------------------------------------------------------------

    def test_success_audit_shows_success(self):
        """Successful execution → inspect_local returns SUCCESS_RECORDED_LOCALLY."""
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            result = execute_approved_once(
                path, FakeReadJira(), phrase_for(path),
                store=tmp, send=success_sender(),
            )
            self.assertEqual(result["status"], "SUCCESS_VERIFIED")
            self.assertEqual(result["sprint_id"], 321)
            self.assertIs(result["retry_allowed"], False)

            summary = inspect_local(tmp)
            self.assertEqual(len(summary["attempts"]), 1)
            self.assertEqual(
                summary["attempts"][0]["status"],
                "SUCCESS_RECORDED_LOCALLY",
            )
            self.assertEqual(
                summary["counts"].get("SUCCESS_RECORDED_LOCALLY"), 1,
            )
            # Target claim linked to the attempt
            self.assertEqual(len(summary["target_claims"]), 1)
            self.assertEqual(
                summary["target_claims"][0]["status"],
                "TARGET_RESERVED_WITH_ATTEMPT",
            )
            self.assertEqual(
                summary["target_claim_counts"].get("TARGET_RESERVED_WITH_ATTEMPT"), 1,
            )

    # ------------------------------------------------------------------
    # Audit output after UNKNOWN outcome
    # ------------------------------------------------------------------

    def test_unknown_outcome_audit_shows_unknown(self):
        """Network failure → UNKNOWN outcome → inspect_local matches."""
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            result = execute_approved_once(
                path, FakeReadJira(), phrase_for(path),
                store=tmp, send=failing_sender(),
            )
            self.assertEqual(result["status"], "UNKNOWN_NEEDS_RECONCILIATION")
            self.assertIs(result["retry_allowed"], False)
            # dispatch marker is present (POST may have been sent)
            self.assertTrue(
                (Path(tmp) / "real_dispatch" / f"{path.stem}.json").exists()
            )

            summary = inspect_local(tmp)
            self.assertEqual(len(summary["attempts"]), 1)
            self.assertEqual(
                summary["attempts"][0]["status"],
                "UNKNOWN_NEEDS_RECONCILIATION",
            )
            self.assertEqual(
                summary["counts"].get("UNKNOWN_NEEDS_RECONCILIATION"), 1,
            )

    # ------------------------------------------------------------------
    # Approval gate
    # ------------------------------------------------------------------

    def test_missing_approval_blocks_before_any_marker(self):
        """No approval file → execution fails before any marker is created."""
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            path.with_suffix(".approval.json").unlink()
            with self.assertRaises(ValueError):
                execute_approved_once(
                    path, FakeReadJira(), phrase_for(path),
                    store=tmp,
                    send=lambda *_: self.fail("POST should not be called"),
                )
            self.assertFalse((Path(tmp) / "attempts").exists())
            self.assertFalse((Path(tmp) / "target_claims").exists())
            self.assertFalse((Path(tmp) / "real_dispatch").exists())

    def test_expired_proposal_blocks_before_any_marker(self):
        """Expired proposal → execution fails before any marker is created."""
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp, expired=True)
            with self.assertRaisesRegex(ValueError, "expirada"):
                execute_approved_once(
                    path, FakeReadJira(), phrase_for(path),
                    store=tmp,
                    send=lambda *_: self.fail("POST should not be called"),
                )
            self.assertFalse((Path(tmp) / "target_claims").exists())
            self.assertFalse((Path(tmp) / "real_dispatch").exists())

    # ------------------------------------------------------------------
    # Cross-proposal target reservation
    # ------------------------------------------------------------------

    def test_cross_proposal_target_reservation_blocks(self):
        """A pre-existing target claim from a different proposal blocks execution."""
        with tempfile.TemporaryDirectory() as tmp:
            # Another proposal (different ID) already reserved the same target.
            other_request = {
                "method": "POST",
                "endpoint": "/rest/agile/1.0/sprint",
                "payload": {"name": "SCRUM Sprint 2", "originBoardId": 1},
            }
            claim_target(tmp, "f" * 16, "b" * 64, other_request)

            path = create_fixture(tmp)
            with self.assertRaisesRegex(ValueError, "Alvo de sprint ja reservado"):
                execute_approved_once(
                    path, FakeReadJira(), phrase_for(path),
                    store=tmp,
                    send=lambda *_: self.fail("POST should not be called"),
                )
            # No attempt file was created for this proposal
            self.assertFalse(
                (Path(tmp) / "attempts" / f"{path.stem}.json").exists()
            )
            self.assertFalse((Path(tmp) / "real_dispatch").exists())

    # ------------------------------------------------------------------
    # Repetition blocking
    # ------------------------------------------------------------------

    def test_second_execution_blocked_audit_unchanged(self):
        """After success, a second execution attempt is rejected; audit stays stable."""
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            execute_approved_once(
                path, FakeReadJira(), phrase_for(path),
                store=tmp, send=success_sender(),
            )
            with self.assertRaisesRegex(ValueError, "Repeticao bloqueada"):
                execute_approved_once(
                    path, FakeReadJira(), phrase_for(path),
                    store=tmp,
                    send=lambda *_: self.fail("second POST should not be called"),
                )
            summary = inspect_local(tmp)
            self.assertEqual(len(summary["attempts"]), 1)
            self.assertEqual(
                summary["attempts"][0]["status"],
                "SUCCESS_RECORDED_LOCALLY",
            )
            # Target claim count did not grow
            self.assertEqual(len(summary["target_claims"]), 1)

    # ------------------------------------------------------------------
    # Paginated sprint list — duplicate on page 2
    # ------------------------------------------------------------------

    def test_duplicate_on_page_two_blocks_before_any_marker(self):
        """Sprint already exists on page 2 at execution time → blocked at preflight."""
        with tempfile.TemporaryDirectory() as tmp:
            # Proposal was created when board had only ["SCRUM Sprint 0", "SCRUM Sprint 1"].
            path = create_fixture(tmp)
            # At execution time, page 2 now contains the duplicate.
            jira = PagedFakeJira(
                page0_names=["SCRUM Sprint 0"],
                page1_names=["SCRUM Sprint 1", "SCRUM Sprint 2"],
            )
            with self.assertRaisesRegex(ValueError, "Ja existe"):
                execute_approved_once(
                    path, jira, phrase_for(path),
                    store=tmp,
                    send=lambda *_: self.fail("POST should not be called"),
                )
            self.assertFalse((Path(tmp) / "target_claims").exists())
            self.assertFalse((Path(tmp) / "real_dispatch").exists())

    def test_paginated_board_changed_blocks_before_any_marker(self):
        """Sprint list change between proposal and execution blocks at snapshot mismatch."""
        with tempfile.TemporaryDirectory() as tmp:
            # Proposal was created with ["SCRUM Sprint 0", "SCRUM Sprint 1"].
            path = create_fixture(tmp)
            # At execution time, page 2 has a different name (not a duplicate).
            jira = PagedFakeJira(
                page0_names=["SCRUM Sprint 0"],
                page1_names=["SCRUM Sprint 99"],  # list changed
            )
            with self.assertRaisesRegex(ValueError, "mudou"):
                execute_approved_once(
                    path, jira, phrase_for(path),
                    store=tmp,
                    send=lambda *_: self.fail("POST should not be called"),
                )
            self.assertFalse((Path(tmp) / "target_claims").exists())
            self.assertFalse((Path(tmp) / "real_dispatch").exists())

    # ------------------------------------------------------------------
    # Dispatch count — one POST, one target claim, one outcome
    # ------------------------------------------------------------------

    def test_single_dispatch_marker_one_post_one_target(self):
        """Exactly one dispatch marker, one POST call, one target claim after success."""
        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)
            post_calls = []
            def counting_sender(jira, payload):
                post_calls.append(payload.copy())
                return {"id": 321, "name": payload["name"],
                        "originBoardId": 1, "state": "future"}
            execute_approved_once(
                path, FakeReadJira(), phrase_for(path),
                store=tmp, send=counting_sender,
            )
            self.assertEqual(len(post_calls), 1)
            dispatches = list((Path(tmp) / "real_dispatch").glob("*.json"))
            self.assertEqual(len(dispatches), 1)
            outcomes = list((Path(tmp) / "real_outcomes").glob("*.json"))
            self.assertEqual(len(outcomes), 1)
            claims = list((Path(tmp) / "target_claims").glob("*.json"))
            self.assertEqual(len(claims), 1)

    # ------------------------------------------------------------------
    # Fresh store — no side-effects
    # ------------------------------------------------------------------

    def test_audit_shows_empty_on_fresh_store(self):
        """inspect_local on a store that never had any activity is safe and empty."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "proposals"
            summary = inspect_local(store)
            self.assertEqual(summary["attempts"], [])
            self.assertEqual(summary["target_claims"], [])
            self.assertEqual(summary["reconciliations"], [])
            self.assertFalse(store.exists())

    # ------------------------------------------------------------------
    # Production gate: native_write also rejects wrong site
    # ------------------------------------------------------------------

    def test_native_write_rejects_wrong_jira_site(self):
        """execute_approved_once with wrong site raises PermissionError before any marker."""
        from jiraia.client import JiraClient

        with tempfile.TemporaryDirectory() as tmp:
            path = create_fixture(tmp)

            wrong_site = object.__new__(JiraClient)
            wrong_site.url = "https://other.atlassian.net"
            wrong_site.auth = "FAKE"

            with self.assertRaises(PermissionError):
                # send=None → triggers _require_site check
                execute_approved_once(
                    path, wrong_site, phrase_for(path),
                    store=tmp,
                    # We pass send=None to trigger the production path (_require_site).
                    # No network call will be made because _require_site raises first.
                )
            self.assertFalse((Path(tmp) / "target_claims").exists())
            self.assertFalse((Path(tmp) / "real_dispatch").exists())


if __name__ == "__main__":
    unittest.main()
