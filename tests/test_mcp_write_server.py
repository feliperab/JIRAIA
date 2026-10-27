"""Offline tests for the jiraia_write MCP server logic.

All tests target _process_sprint_creation() directly, injecting:
  - A FakeJira client (no real HTTP).
  - An async elicit_fn that returns predetermined results.
  - A synchronous send= callable to avoid _require_site checks.

No real Jira POST is ever sent.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from mcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)
from pydantic import BaseModel

from jiraia.action_engine import checksum, save_proposal
from jiraia.audit_status import inspect_local
from jiraia.execution_guard import execution_phrase
from scripts.mcp_jiraia_write import (
    _ApprovalSchema,
    _ExecutionSchema,
    _process_sprint_creation,
    _require_write_site,
)
from test_executor import FakeJira


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeReadJira(FakeJira):
    """FakeJira that also handles the post-create GET for sprint/{id}."""

    def get(self, endpoint):
        if endpoint == "/rest/agile/1.0/sprint/321":
            return {
                "id": 321,
                "name": "SCRUM Sprint 2",
                "originBoardId": 1,
                "state": "future",
            }
        return super().get(endpoint)


def _accepted(schema_cls: type, **kwargs) -> AcceptedElicitation:
    return AcceptedElicitation(data=schema_cls(**kwargs))


def _declined() -> DeclinedElicitation:
    return DeclinedElicitation()


def _cancelled() -> CancelledElicitation:
    return CancelledElicitation()


def _elicit_sequence(*responses):
    """Returns an async elicit_fn that yields responses in order."""
    queue = list(responses)

    async def _fn(message, schema):
        if not queue:
            raise AssertionError("elicit called more times than expected")
        return queue.pop(0)

    return _fn


def _success_sender():
    """Fake POST transport that returns a valid sprint response."""
    def _send(jira, payload):
        return {
            "id": 321,
            "name": payload["name"],
            "originBoardId": payload["originBoardId"],
            "state": "future",
        }
    return _send


def _approval_response(proposal_id: str) -> AcceptedElicitation:
    return _accepted(_ApprovalSchema, challenge_response=f"APROVAR {proposal_id}")


def _execution_response(proposal_id: str, name: str) -> AcceptedElicitation:
    return _accepted(_ExecutionSchema, phrase=execution_phrase(proposal_id, name))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class MpcWriteServerTests(unittest.IsolatedAsyncioTestCase):

    # ------------------------------------------------------------------
    # Happy path: full success → inspect_local shows SUCCESS
    # ------------------------------------------------------------------

    async def test_full_success_creates_audit_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            jira = FakeReadJira()
            calls = []

            def counting_sender(j, payload):
                calls.append(payload.copy())
                return {"id": 321, "name": payload["name"],
                        "originBoardId": 1, "state": "future"}

            # We don't know proposal_id until after build_create_sprint;
            # use a deferred elicit_fn that captures the proposal from the file system.
            proposal_id_holder = {}
            call_index = [0]

            async def deferred_elicit(message, schema):
                call_index[0] += 1
                if call_index[0] == 1:
                    # Extract proposal_id from the message (it follows "ID       : ")
                    for line in message.split("\n"):
                        if line.startswith("ID       :"):
                            pid = line.split(":", 1)[1].strip()
                            proposal_id_holder["id"] = pid
                    return _accepted(_ApprovalSchema,
                                     challenge_response=f"APROVAR {proposal_id_holder['id']}")
                else:
                    pid = proposal_id_holder["id"]
                    return _accepted(_ExecutionSchema,
                                     phrase=execution_phrase(pid, "SCRUM Sprint 2"))

            result = await _process_sprint_creation(
                "SCRUM Sprint 2",
                jira,
                deferred_elicit,
                store=tmp,
                send=counting_sender,
            )

            self.assertEqual(result["status"], "SUCCESS_VERIFIED")
            self.assertEqual(result["sprint_id"], 321)
            self.assertIs(result["retry_allowed"], False)
            self.assertEqual(len(calls), 1)

            summary = inspect_local(tmp)
            self.assertEqual(summary["attempts"][0]["status"], "SUCCESS_RECORDED_LOCALLY")
            self.assertEqual(len(summary["target_claims"]), 1)

    # ------------------------------------------------------------------
    # Approval declined
    # ------------------------------------------------------------------

    async def test_approval_declined_creates_no_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = await _process_sprint_creation(
                "SCRUM Sprint 2",
                FakeJira(),
                _elicit_sequence(_declined()),
                store=tmp,
                send=lambda *_: self.fail("POST not expected"),
            )
            self.assertEqual(result["status"], "APPROVAL_DECLINED")
            self.assertFalse((Path(tmp) / "attempts").exists())
            self.assertFalse((Path(tmp) / "real_dispatch").exists())

    # ------------------------------------------------------------------
    # Approval cancelled
    # ------------------------------------------------------------------

    async def test_approval_cancelled_creates_no_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = await _process_sprint_creation(
                "SCRUM Sprint 2",
                FakeJira(),
                _elicit_sequence(_cancelled()),
                store=tmp,
                send=lambda *_: self.fail("POST not expected"),
            )
            self.assertEqual(result["status"], "APPROVAL_CANCELLED")
            self.assertFalse((Path(tmp) / "real_dispatch").exists())

    # ------------------------------------------------------------------
    # Wrong approval phrase
    # ------------------------------------------------------------------

    async def test_wrong_approval_phrase_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = await _process_sprint_creation(
                "SCRUM Sprint 2",
                FakeJira(),
                _elicit_sequence(
                    _accepted(_ApprovalSchema, challenge_response="WRONG")
                ),
                store=tmp,
                send=lambda *_: self.fail("POST not expected"),
            )
            self.assertEqual(result["status"], "APPROVAL_PHRASE_MISMATCH")
            self.assertFalse((Path(tmp) / "attempts").exists())

    # ------------------------------------------------------------------
    # Execution declined after approval
    # ------------------------------------------------------------------

    async def test_execution_declined_no_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            call_index = [0]
            proposal_id_holder = {}

            async def elicit_fn(message, schema):
                call_index[0] += 1
                if call_index[0] == 1:
                    for line in message.split("\n"):
                        if line.startswith("ID       :"):
                            proposal_id_holder["id"] = line.split(":", 1)[1].strip()
                    pid = proposal_id_holder["id"]
                    return _accepted(_ApprovalSchema,
                                     challenge_response=f"APROVAR {pid}")
                return _declined()

            result = await _process_sprint_creation(
                "SCRUM Sprint 2", FakeJira(), elicit_fn,
                store=tmp,
                send=lambda *_: self.fail("POST not expected"),
            )
            self.assertEqual(result["status"], "EXECUTION_DECLINED")
            self.assertFalse((Path(tmp) / "real_dispatch").exists())
            # Approval receipt was saved
            proposals = list((Path(tmp)).glob("*.approval.json"))
            self.assertEqual(len(proposals), 1)

    # ------------------------------------------------------------------
    # Execution cancelled after approval
    # ------------------------------------------------------------------

    async def test_execution_cancelled_no_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            call_index = [0]
            proposal_id_holder = {}

            async def elicit_fn(message, schema):
                call_index[0] += 1
                if call_index[0] == 1:
                    for line in message.split("\n"):
                        if line.startswith("ID       :"):
                            proposal_id_holder["id"] = line.split(":", 1)[1].strip()
                    pid = proposal_id_holder["id"]
                    return _accepted(_ApprovalSchema,
                                     challenge_response=f"APROVAR {pid}")
                return _cancelled()

            result = await _process_sprint_creation(
                "SCRUM Sprint 2", FakeJira(), elicit_fn,
                store=tmp,
                send=lambda *_: self.fail("POST not expected"),
            )
            self.assertEqual(result["status"], "EXECUTION_CANCELLED")
            self.assertFalse((Path(tmp) / "real_dispatch").exists())

    # ------------------------------------------------------------------
    # Wrong execution phrase
    # ------------------------------------------------------------------

    async def test_wrong_execution_phrase_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            call_index = [0]
            proposal_id_holder = {}

            async def elicit_fn(message, schema):
                call_index[0] += 1
                if call_index[0] == 1:
                    for line in message.split("\n"):
                        if line.startswith("ID       :"):
                            proposal_id_holder["id"] = line.split(":", 1)[1].strip()
                    pid = proposal_id_holder["id"]
                    return _accepted(_ApprovalSchema,
                                     challenge_response=f"APROVAR {pid}")
                return _accepted(_ExecutionSchema, phrase="WRONG PHRASE")

            result = await _process_sprint_creation(
                "SCRUM Sprint 2", FakeJira(), elicit_fn,
                store=tmp,
                send=lambda *_: self.fail("POST not expected"),
            )
            self.assertEqual(result["status"], "EXECUTION_PHRASE_MISMATCH")
            self.assertFalse((Path(tmp) / "real_dispatch").exists())

    # ------------------------------------------------------------------
    # Elicitation unavailable (client does not support it)
    # ------------------------------------------------------------------

    async def test_elicitation_unavailable_blocks_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            async def failing_elicit(message, schema):
                raise RuntimeError("Client does not support elicitation")

            result = await _process_sprint_creation(
                "SCRUM Sprint 2",
                FakeJira(),
                failing_elicit,
                store=tmp,
                send=lambda *_: self.fail("POST not expected"),
            )
            self.assertEqual(result["status"], "ELICITATION_UNAVAILABLE")
            self.assertFalse((Path(tmp) / "real_dispatch").exists())
            self.assertFalse((Path(tmp) / "attempts").exists())

    # ------------------------------------------------------------------
    # Proposal expired between approval and execution elicitation
    # ------------------------------------------------------------------

    async def test_expired_proposal_blocked_at_revalidation(self):
        """If proposal expires between first and second elicitation, revalidation fails."""
        from datetime import datetime, timedelta, timezone
        from jiraia.action_engine import build_create_sprint, checksum, save_proposal
        import json

        with tempfile.TemporaryDirectory() as tmp:
            # Create a proposal manually with an old timestamp
            jira = FakeJira()
            proposal = build_create_sprint(jira, 1, "SCRUM Sprint 2")
            proposal["created_at"] = (
                datetime.now(timezone.utc) - timedelta(minutes=31)
            ).isoformat()
            path = save_proposal(proposal, folder=tmp)

            # Record approval (also with old timestamp-ish)
            from jiraia.action_engine import record_approval
            record_approval(path, proposal, checksum(proposal))

            # Directly call execute_approved_once-adjacent logic by
            # testing that prepare_execution fails for the expired proposal
            from jiraia.executor import prepare_execution
            with self.assertRaisesRegex(ValueError, "expirada"):
                prepare_execution(path, jira, store=tmp)

    # ------------------------------------------------------------------
    # Duplicate sprint name blocked at preflight
    # ------------------------------------------------------------------

    async def test_duplicate_name_blocked_before_elicitation(self):
        with tempfile.TemporaryDirectory() as tmp:
            duplicate_jira = FakeJira(names=[
                "SCRUM Sprint 0", "SCRUM Sprint 1", "SCRUM Sprint 2"
            ])
            result = await _process_sprint_creation(
                "SCRUM Sprint 2",
                duplicate_jira,
                _elicit_sequence(),  # no elicitation calls expected
                store=tmp,
                send=lambda *_: self.fail("POST not expected"),
            )
            self.assertEqual(result["status"], "PREFLIGHT_FAILED")
            self.assertIn("Ja existe", result["message"])

    # ------------------------------------------------------------------
    # Paginated duplicate — sprint on page 2
    # ------------------------------------------------------------------

    async def test_paginated_duplicate_blocked_before_elicitation(self):
        from urllib.parse import parse_qs, urlsplit

        class PagedJira(FakeJira):
            def get(self, endpoint):
                if endpoint == "/rest/agile/1.0/board/1":
                    return {"id": 1, "name": "SCRUM board"}
                if endpoint.startswith("/rest/agile/1.0/board/1/sprint?"):
                    query = parse_qs(urlsplit(endpoint).query)
                    start = int(query["startAt"][0])
                    pages = {
                        0: {
                            "isLast": False,
                            "startAt": 0,
                            "values": [{"name": "SCRUM Sprint 0"}],
                        },
                        1: {
                            "isLast": True,
                            "startAt": 1,
                            "total": 2,
                            "values": [{"name": "SCRUM Sprint 2"}],
                        },
                    }
                    return pages[start]
                raise AssertionError(f"Endpoint inesperado: {endpoint}")

        with tempfile.TemporaryDirectory() as tmp:
            result = await _process_sprint_creation(
                "SCRUM Sprint 2",
                PagedJira(),
                _elicit_sequence(),  # no elicitation expected
                store=tmp,
                send=lambda *_: self.fail("POST not expected"),
            )
            self.assertEqual(result["status"], "PREFLIGHT_FAILED")

    # ------------------------------------------------------------------
    # Second execution attempt is blocked (target already reserved)
    # ------------------------------------------------------------------

    async def test_second_execution_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            jira = FakeReadJira()
            call_index_a = [0]
            proposal_id_a = {}

            async def elicit_a(message, schema):
                call_index_a[0] += 1
                if call_index_a[0] == 1:
                    for line in message.split("\n"):
                        if line.startswith("ID       :"):
                            proposal_id_a["id"] = line.split(":", 1)[1].strip()
                    pid = proposal_id_a["id"]
                    return _accepted(_ApprovalSchema,
                                     challenge_response=f"APROVAR {pid}")
                pid = proposal_id_a["id"]
                return _accepted(_ExecutionSchema,
                                 phrase=execution_phrase(pid, "SCRUM Sprint 2"))

            result1 = await _process_sprint_creation(
                "SCRUM Sprint 2", jira, elicit_a,
                store=tmp, send=_success_sender(),
            )
            self.assertEqual(result1["status"], "SUCCESS_VERIFIED")

            # Second attempt for same target → blocked
            call_index_b = [0]
            proposal_id_b = {}

            async def elicit_b(message, schema):
                call_index_b[0] += 1
                if call_index_b[0] == 1:
                    for line in message.split("\n"):
                        if line.startswith("ID       :"):
                            proposal_id_b["id"] = line.split(":", 1)[1].strip()
                    pid = proposal_id_b["id"]
                    return _accepted(_ApprovalSchema,
                                     challenge_response=f"APROVAR {pid}")
                pid = proposal_id_b["id"]
                return _accepted(_ExecutionSchema,
                                 phrase=execution_phrase(pid, "SCRUM Sprint 2"))

            result2 = await _process_sprint_creation(
                "SCRUM Sprint 2", jira, elicit_b,
                store=tmp, send=_success_sender(),
            )
            # blocked at revalidation (sprint now exists) or at target reservation
            self.assertIn(
                result2["status"],
                {"PREFLIGHT_FAILED", "REVALIDATION_FAILED",
                 "EXECUTION_ERROR", "EXECUTION_BLOCKED"},
            )

    # ------------------------------------------------------------------
    # Network failure → UNKNOWN, no retry
    # ------------------------------------------------------------------

    async def test_network_failure_results_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            call_index = [0]
            proposal_id_holder = {}

            async def elicit_fn(message, schema):
                call_index[0] += 1
                if call_index[0] == 1:
                    for line in message.split("\n"):
                        if line.startswith("ID       :"):
                            proposal_id_holder["id"] = line.split(":", 1)[1].strip()
                    pid = proposal_id_holder["id"]
                    return _accepted(_ApprovalSchema,
                                     challenge_response=f"APROVAR {pid}")
                pid = proposal_id_holder["id"]
                return _accepted(_ExecutionSchema,
                                 phrase=execution_phrase(pid, "SCRUM Sprint 2"))

            def failing_sender(jira, payload):
                raise ConnectionError("simulated network failure")

            result = await _process_sprint_creation(
                "SCRUM Sprint 2",
                FakeReadJira(),
                elicit_fn,
                store=tmp,
                send=failing_sender,
            )
            self.assertEqual(result["status"], "UNKNOWN_NEEDS_RECONCILIATION")
            self.assertIs(result["retry_allowed"], False)
            self.assertTrue((Path(tmp) / "real_dispatch").exists())

    # ------------------------------------------------------------------
    # Single dispatch — exactly one POST transport call
    # ------------------------------------------------------------------

    async def test_single_dispatch_exactly_one_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            jira = FakeReadJira()
            post_calls = []
            call_index = [0]
            proposal_id_holder = {}

            async def elicit_fn(message, schema):
                call_index[0] += 1
                if call_index[0] == 1:
                    for line in message.split("\n"):
                        if line.startswith("ID       :"):
                            proposal_id_holder["id"] = line.split(":", 1)[1].strip()
                    pid = proposal_id_holder["id"]
                    return _accepted(_ApprovalSchema,
                                     challenge_response=f"APROVAR {pid}")
                pid = proposal_id_holder["id"]
                return _accepted(_ExecutionSchema,
                                 phrase=execution_phrase(pid, "SCRUM Sprint 2"))

            def counting_sender(j, payload):
                post_calls.append(payload.copy())
                return {"id": 321, "name": payload["name"],
                        "originBoardId": 1, "state": "future"}

            result = await _process_sprint_creation(
                "SCRUM Sprint 2", jira, elicit_fn,
                store=tmp, send=counting_sender,
            )
            self.assertEqual(result["status"], "SUCCESS_VERIFIED")
            self.assertEqual(len(post_calls), 1)
            dispatches = list((Path(tmp) / "real_dispatch").glob("*.json"))
            self.assertEqual(len(dispatches), 1)

    # ------------------------------------------------------------------
    # Audit: SUCCESS_RECORDED_LOCALLY appears in inspect_local
    # ------------------------------------------------------------------

    async def test_audit_shows_success_after_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            call_index = [0]
            proposal_id_holder = {}

            async def elicit_fn(message, schema):
                call_index[0] += 1
                if call_index[0] == 1:
                    for line in message.split("\n"):
                        if line.startswith("ID       :"):
                            proposal_id_holder["id"] = line.split(":", 1)[1].strip()
                    pid = proposal_id_holder["id"]
                    return _accepted(_ApprovalSchema,
                                     challenge_response=f"APROVAR {pid}")
                pid = proposal_id_holder["id"]
                return _accepted(_ExecutionSchema,
                                 phrase=execution_phrase(pid, "SCRUM Sprint 2"))

            await _process_sprint_creation(
                "SCRUM Sprint 2",
                FakeReadJira(),
                elicit_fn,
                store=tmp,
                send=_success_sender(),
            )
            summary = inspect_local(tmp)
            self.assertEqual(
                summary["attempts"][0]["status"],
                "SUCCESS_RECORDED_LOCALLY",
            )
            self.assertEqual(
                summary["target_claims"][0]["status"],
                "TARGET_RESERVED_WITH_ATTEMPT",
            )

    # ------------------------------------------------------------------
    # _require_write_site: wrong site and HTTP blocked
    # ------------------------------------------------------------------

    def test_require_write_site_wrong_host(self):
        from jiraia.client import JiraClient
        with self.assertRaises(PermissionError):
            _require_write_site(
                JiraClient("https://other.atlassian.net", "u", "t")
            )

    def test_require_write_site_http_blocked(self):
        from jiraia.client import JiraClient
        with self.assertRaises(PermissionError):
            _require_write_site(
                JiraClient("http://jiraia.atlassian.net", "u", "t")
            )

    def test_require_write_site_valid(self):
        from jiraia.client import JiraClient
        # Should not raise
        _require_write_site(
            JiraClient("https://jiraia.atlassian.net", "u", "t")
        )

    # ------------------------------------------------------------------
    # jiraia-readonly agent contract still has no write tools
    # ------------------------------------------------------------------

    def test_readonly_agent_has_no_write_tools(self):
        import json
        from pathlib import Path
        agent_path = (
            Path(__file__).resolve().parents[1]
            / ".kiro" / "agents" / "jiraia-readonly.json"
        )
        config = json.loads(agent_path.read_text(encoding="utf-8-sig"))
        write_tools = [
            t for t in config["tools"]
            if "write" in t.lower()
        ]
        self.assertEqual(write_tools, [])

    # ------------------------------------------------------------------
    # jiraia-writer agent has only the one write tool
    # ------------------------------------------------------------------

    def test_writer_agent_has_exactly_one_tool(self):
        import json
        from pathlib import Path
        agent_path = (
            Path(__file__).resolve().parents[1]
            / ".kiro" / "agents" / "jiraia-writer.json"
        )
        config = json.loads(agent_path.read_text(encoding="utf-8-sig"))
        self.assertEqual(len(config["tools"]), 1)
        self.assertIn("jiraia_write_create_sprint", config["tools"][0])

    def test_writer_agent_denies_shell_and_atlassian(self):
        import json
        from pathlib import Path
        agent_path = (
            Path(__file__).resolve().parents[1]
            / ".kiro" / "agents" / "jiraia-writer.json"
        )
        config = json.loads(agent_path.read_text(encoding="utf-8-sig"))
        rules = config["permissions"]["rules"]
        denied_caps = {r["capability"] for r in rules if r.get("effect") == "deny"}
        self.assertIn("shell", denied_caps)
        self.assertIn("fs_write", denied_caps)
        self.assertTrue(
            any(
                r.get("capability") == "mcp"
                and r.get("effect") == "deny"
                and "atlassian/*" in r.get("match", [])
                for r in rules
            )
        )

    # ------------------------------------------------------------------
    # record_approval in action_engine is usable without input()
    # ------------------------------------------------------------------

    def test_record_approval_saves_receipt_without_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            from jiraia.action_engine import (
                build_create_sprint, checksum, save_proposal, record_approval
            )
            proposal = build_create_sprint(FakeJira(), 1, "SCRUM Sprint 99")
            path = save_proposal(proposal, folder=tmp)
            digest = checksum(proposal)
            receipt_path = record_approval(path, proposal, digest)
            self.assertTrue(receipt_path.is_file())
            import json
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["proposal_id"], proposal["id"])
            self.assertEqual(receipt["status"], "APPROVED_FOR_FUTURE_REVALIDATION")
            self.assertFalse(receipt["executed"])

    def test_record_approval_blocks_second_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            from jiraia.action_engine import (
                build_create_sprint, checksum, save_proposal, record_approval
            )
            proposal = build_create_sprint(FakeJira(), 1, "SCRUM Sprint 99")
            path = save_proposal(proposal, folder=tmp)
            digest = checksum(proposal)
            record_approval(path, proposal, digest)
            with self.assertRaises(FileExistsError):
                record_approval(path, proposal, digest)


if __name__ == "__main__":
    unittest.main()
