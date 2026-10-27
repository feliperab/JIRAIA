"""JIRAIA Write MCP Server — controlled sprint creation with double elicitation.

Single authorized tool: jiraia_write_create_sprint
  - Restricted to creating FUTURE sprints on board 1 (SCRUM project).
  - Two sequential human confirmations via Kiro elicitation forms before any POST.
  - JiraClient.post() is NOT enabled; the existing native executor is invoked.
  - No retry on failure or uncertain outcome.
  - No other write operations are available on this server.
  - elicitation_fn is injected so the core logic can be tested offline.

Security invariants maintained:
  - _require_write_site() enforces the exact Jira instance.
  - Both elicitation responses are validated server-side with hmac.compare_digest.
  - A declined, cancelled, or incorrectly answered elicitation immediately blocks execution.
  - If the client does not support elicitation, the operation is blocked (no bypass).
  - execute_approved_once() runs full preflight + reservation + single POST + audit.
"""

import hmac
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP, Context
from mcp.server.elicitation import (
    AcceptedElicitation,
    DeclinedElicitation,
    CancelledElicitation,
)
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jiraia.action_engine import (
    STORE,
    build_create_sprint,
    checksum,
    record_approval,
    save_proposal,
)
from jiraia.client import JiraClient
from jiraia.execution_guard import execution_phrase
from jiraia.executor import prepare_execution
from jiraia.native_write import execute_approved_once


AUTHORIZED_SITE = "https://jiraia.atlassian.net"
AUTHORIZED_BOARD = 1


# ---------------------------------------------------------------------------
# Site guard
# ---------------------------------------------------------------------------

def _require_write_site(jira):
    """Fail fast if this is not the authorised Jira instance.

    Intentionally stricter than checking URL only: type equality (not isinstance)
    prevents subclass substitution.
    """
    if type(jira) is not JiraClient:
        raise PermissionError("Executor requer JiraClient original")
    u = urlsplit(jira.url)
    if (
        u.scheme != "https"
        or u.hostname != "jiraia.atlassian.net"
        or u.port not in (None, 443)
        or u.username or u.password
        or u.path not in ("", "/")
        or u.query or u.fragment
    ):
        raise PermissionError("Instancia de escrita nao autorizada")


# ---------------------------------------------------------------------------
# Elicitation schemas — only primitive fields allowed by the MCP spec
# ---------------------------------------------------------------------------

class _ApprovalSchema(BaseModel):
    challenge_response: str = Field(
        description="Copie exatamente o desafio de aprovacao apresentado"
    )


class _ExecutionSchema(BaseModel):
    phrase: str = Field(
        description="Copie exatamente a frase de execucao apresentada"
    )


# ---------------------------------------------------------------------------
# Core logic — injectable elicit_fn enables offline testing
# ---------------------------------------------------------------------------

async def _process_sprint_creation(
    sprint_name: str,
    jira,
    elicit_fn,
    *,
    store=None,
    send=None,
) -> dict:
    """Full proposal → double-elicitation → execution pipeline.

    Parameters
    ----------
    sprint_name : str
        Name of the sprint to create (stripped, 1-80 chars).
    jira :
        JiraClient instance (or FakeJira in tests).
    elicit_fn :
        Async callable (message, schema) -> ElicitationResult. In production
        this is ctx.elicit; in tests it is a controlled fake.
    store : optional
        Overrides the default proposal store. Production always uses STORE.
    send : optional
        Injected POST transport for offline tests. Production uses None
        (which activates the native transport with site/store checks).
    """
    store_path = Path(store) if store is not None else STORE

    # --- Input validation ---
    if not isinstance(sprint_name, str) or not 1 <= len(sprint_name.strip()) <= 80:
        return {
            "status": "INVALID_INPUT",
            "message": "Nome de sprint invalido (1-80 caracteres).",
        }
    sprint_name = sprint_name.strip()

    # --- GET preflight: verify board and detect duplicate names ---
    try:
        proposal = build_create_sprint(jira, AUTHORIZED_BOARD, sprint_name)
    except ValueError as exc:
        return {"status": "PREFLIGHT_FAILED", "message": str(exc)}
    except RuntimeError as exc:
        return {"status": "JIRA_ERROR", "message": str(exc)}

    path = save_proposal(proposal, folder=store_path)
    proposal_id = proposal["id"]
    digest = checksum(proposal)
    sprint_display = proposal["parameters"]["name"]
    board_name = proposal["target"].get("board_name") or "SCRUM"

    # --- ELICITATION 1: Approval ---
    approval_challenge = f"APROVAR {proposal_id}"

    try:
        approval_result = await elicit_fn(
            message=(
                f"JIRAIA — Proposta de criacao de sprint (revisao obrigatoria)\n\n"
                f"Operacao : criar sprint FUTURA (sem iniciar)\n"
                f"Instancia: {AUTHORIZED_SITE}\n"
                f"Board    : {AUTHORIZED_BOARD} — {board_name}\n"
                f"Nome     : {sprint_display}\n"
                f"ID       : {proposal_id}\n"
                f"SHA-256  : {digest[:24]}...\n\n"
                f"Para aprovar, copie EXATAMENTE:\n"
                f"  {approval_challenge}"
            ),
            schema=_ApprovalSchema,
        )
    except Exception as exc:
        return {
            "status": "ELICITATION_UNAVAILABLE",
            "message": (
                "O cliente nao suporta elicitacao. "
                "A operacao foi bloqueada sem criar marcadores. "
                f"Detalhe: {type(exc).__name__}"
            ),
        }

    if isinstance(approval_result, DeclinedElicitation):
        return {
            "status": "APPROVAL_DECLINED",
            "proposal_id": proposal_id,
            "message": "Aprovacao recusada. Nenhum marcador criado.",
        }
    if isinstance(approval_result, CancelledElicitation):
        return {
            "status": "APPROVAL_CANCELLED",
            "proposal_id": proposal_id,
            "message": "Aprovacao cancelada. Nenhum marcador criado.",
        }

    # Validate the typed challenge — server-side, not trust the model
    if not hmac.compare_digest(
        approval_result.data.challenge_response, approval_challenge
    ):
        return {
            "status": "APPROVAL_PHRASE_MISMATCH",
            "proposal_id": proposal_id,
            "message": "Frase de aprovacao incorreta. Operacao bloqueada.",
        }

    # Persist approval receipt (open("x") + fsync — one-time write)
    record_approval(path, proposal, digest)

    # --- Revalidation GET (board + sprint list snapshot comparison) ---
    try:
        prepare_execution(path, jira, store=store_path)
    except ValueError as exc:
        return {
            "status": "REVALIDATION_FAILED",
            "proposal_id": proposal_id,
            "message": str(exc),
        }
    except RuntimeError as exc:
        return {
            "status": "JIRA_ERROR",
            "proposal_id": proposal_id,
            "message": str(exc),
        }

    # --- ELICITATION 2: Final execution phrase ---
    exec_phrase = execution_phrase(proposal_id, sprint_display)

    try:
        execution_result = await elicit_fn(
            message=(
                f"JIRAIA — CONFIRMACAO FINAL ANTES DO POST\n\n"
                f"ATENCAO: A proxima acao criara uma sprint REAL no Jira Cloud.\n"
                f"Sem desfazer automatico. Sem retry apos resultado incerto.\n\n"
                f"Instancia: {AUTHORIZED_SITE}\n"
                f"Endpoint : POST /rest/agile/1.0/sprint\n"
                f"Payload  : "
                f'{{\"name\": \"{sprint_display}\", '
                f'\"originBoardId\": {AUTHORIZED_BOARD}}}\n\n'
                f"Para autorizar UMA UNICA escrita, copie EXATAMENTE:\n"
                f"  {exec_phrase}"
            ),
            schema=_ExecutionSchema,
        )
    except Exception as exc:
        return {
            "status": "ELICITATION_UNAVAILABLE",
            "proposal_id": proposal_id,
            "message": (
                "Elicitacao de execucao indisponivel. "
                "Aprovacao salva, mas POST nao enviado. "
                f"Detalhe: {type(exc).__name__}"
            ),
        }

    if isinstance(execution_result, DeclinedElicitation):
        return {
            "status": "EXECUTION_DECLINED",
            "proposal_id": proposal_id,
            "message": "Execucao recusada pelo usuario. Aprovacao registrada, POST nao enviado.",
        }
    if isinstance(execution_result, CancelledElicitation):
        return {
            "status": "EXECUTION_CANCELLED",
            "proposal_id": proposal_id,
            "message": "Execucao cancelada. Aprovacao registrada, POST nao enviado.",
        }

    if not hmac.compare_digest(execution_result.data.phrase, exec_phrase):
        return {
            "status": "EXECUTION_PHRASE_MISMATCH",
            "proposal_id": proposal_id,
            "message": "Frase de execucao incorreta. POST bloqueado.",
        }

    # --- Execute: at most one POST, via native executor ---
    try:
        outcome = execute_approved_once(
            path, jira, exec_phrase,
            store=store_path, send=send,
        )
    except PermissionError as exc:
        return {
            "status": "EXECUTION_BLOCKED",
            "proposal_id": proposal_id,
            "message": str(exc),
        }
    except (ValueError, RuntimeError, OSError) as exc:
        return {
            "status": "EXECUTION_ERROR",
            "proposal_id": proposal_id,
            "message": str(exc),
        }

    return outcome


# ---------------------------------------------------------------------------
# MCP tool — production entry point
# ---------------------------------------------------------------------------

mcp = FastMCP("JIRAIA-WRITE")


@mcp.tool()
async def jiraia_write_create_sprint(sprint_name: str, ctx: Context) -> dict:
    """Create a new FUTURE sprint on SCRUM board 1.

    Requires TWO sequential human confirmations via Kiro elicitation forms:
      1. Review the proposal and type the approval challenge.
      2. Read the final warning and type the execution phrase.

    JiraClient.post() is NOT enabled. The native write executor handles
    the POST after all confirmations pass. No retry on failure.
    """
    try:
        jira = JiraClient.from_env()
        _require_write_site(jira)
    except (ValueError, PermissionError) as exc:
        return {"status": "SITE_ERROR", "message": str(exc)}

    return await _process_sprint_creation(
        sprint_name,
        jira,
        ctx.elicit,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
