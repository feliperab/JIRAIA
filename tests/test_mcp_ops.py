"""Offline fail-closed regression tests. Never contact Jira."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from scripts import mcp_jiraia_ops as ops


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_sim_and_ok_authorize(self):
        for word in ("sim", "OK", " Sim "):
            ctx = SimpleNamespace(elicit=AsyncMock(return_value=AcceptedElicitation(
                data=ops.Decision(resposta=word))))
            self.assertTrue(await ops._confirm(ctx, "preview"))
            ctx.elicit.assert_awaited_once()

    async def test_no_decline_and_unavailable_block(self):
        for response in (AcceptedElicitation(data=ops.Decision(resposta="não")), DeclinedElicitation()):
            self.assertFalse(await ops._confirm(SimpleNamespace(elicit=AsyncMock(return_value=response)), "preview"))
        self.assertFalse(await ops._confirm(SimpleNamespace(elicit=AsyncMock(side_effect=RuntimeError())), "preview"))

    async def test_refusal_does_not_call_dispatch(self):
        with patch.object(ops, "_dispatch", new_callable=AsyncMock) as dispatch:
            result = await ops._write(SimpleNamespace(elicit=AsyncMock(return_value=DeclinedElicitation())),
                object(), kind="test", label="test", method="PUT", endpoint="/rest/api/3/issue/SCRUM-1",
                payload={"fields":{"summary":"x"}}, snapshot=1, fresh=lambda: 1, verify=lambda _: True)
            self.assertEqual(result["status"], "CANCELADO_SEM_POST")
            dispatch.assert_not_awaited()

    async def test_stale_data_blocks_before_dispatch(self):
        with tempfile.TemporaryDirectory() as td, patch.object(ops, "AUDIT", Path(td)), patch.object(ops, "_send") as sender:
            result = await ops._dispatch(object(), kind="edit", method="PUT", endpoint="/rest/api/3/issue/SCRUM-1",
                payload={"fields":{"summary":"x"}}, snapshot=1, fresh=lambda: 2, verify=lambda _: True)
            self.assertEqual(result["status"], "DADOS_ALTERADOS_SEM_POST")
            sender.assert_not_called()

    async def test_one_dispatch_and_repetition_blocked(self):
        with tempfile.TemporaryDirectory() as td, patch.object(ops, "AUDIT", Path(td)), patch.object(ops, "_send", return_value={}) as sender:
            kwargs = dict(kind="edit", method="PUT", endpoint="/rest/api/3/issue/SCRUM-1",
                payload={"fields":{"summary":"x"}}, snapshot=1, fresh=lambda: 1, verify=lambda _: True)
            first = await ops._dispatch(object(), **kwargs)
            second = await ops._dispatch(object(), **kwargs)
            self.assertEqual(first["status"], "SUCCESS_VERIFIED")
            self.assertEqual(second["status"], "OPERACAO_JA_RESERVADA")
            sender.assert_called_once()

    async def test_unknown_outcome_never_retries(self):
        with tempfile.TemporaryDirectory() as td, patch.object(ops, "AUDIT", Path(td)), patch.object(ops, "_send", side_effect=RuntimeError()) as sender:
            kwargs = dict(kind="edit", method="PUT", endpoint="/rest/api/3/issue/SCRUM-1",
                payload={"fields":{"summary":"x"}}, snapshot=1, fresh=lambda: 1, verify=lambda _: True)
            first = await ops._dispatch(object(), **kwargs)
            second = await ops._dispatch(object(), **kwargs)
            self.assertEqual(first["status"], "UNKNOWN_NEEDS_RECONCILIATION")
            self.assertEqual(second["status"], "OPERACAO_JA_RESERVADA")
            sender.assert_called_once()


class ContractTests(unittest.TestCase):
    def test_only_scrum_issue_keys(self):
        self.assertEqual(ops._issue_key("scrum-123"), "SCRUM-123")
        for key in ("ABC-123", "SCRUM-0", "SCRUM-2/../../etc", "SCRUM-1?foo"):
            with self.assertRaises(ValueError): ops._issue_key(key)

    def test_unauthorized_endpoint_no_http(self):
        with patch.object(ops, "_require_site"):
            with self.assertRaises(PermissionError):
                ops._send(SimpleNamespace(auth="fake"), "DELETE", "/rest/api/3/issue/SCRUM-1", {})
