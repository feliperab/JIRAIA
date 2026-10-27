import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from jiraia.action_engine import STORE, read_proposal
from jiraia.execution_guard import execution_phrase
from jiraia.executor import prepare_execution
from jiraia.target_ledger import claim_target


def reserve_attempt(proposal_file, jira, confirmation, store=None):
    """
    Revalida e reserva uma tentativa de escrita.

    IMPORTANTE:
    Este metodo NAO envia POST e NAO modifica o Jira.
    Um registro existente bloqueia novas reservas.
    """
    store = Path(store) if store is not None else STORE
    store = store.resolve()
    path = Path(proposal_file).resolve()

    # Revalidar proposta, recibo, prazo e estado do board
    preview = prepare_execution(path, jira, store=store)

    if (
        preview.get("approval_validated") is not True
        or preview.get("board_revalidated") is not True
        or preview.get("ready_to_execute") is not False
        or preview.get("executed") is not False
    ):
        raise ValueError("Preflight em estado inesperado")

    request = preview["request_preview"]
    payload = request["payload"]

    if (
        request.get("method") != "POST"
        or request.get("endpoint") != "/rest/agile/1.0/sprint"
        or set(payload) != {"name", "originBoardId"}
    ):
        raise ValueError("Operacao fora da lista permitida")

    proposal_id = preview["proposal_id"]

    expected = execution_phrase(
        proposal_id, payload["name"]
    )

    if (
        type(confirmation) is not str
        or not hmac.compare_digest(confirmation, expected)
    ):
        raise PermissionError(
            "Confirmacao final de execucao incorreta"
        )

    proposal, digest = read_proposal(path)

    if proposal["id"] != proposal_id:
        raise ValueError("Identificacao de proposta inconsistente")

    # Reserva exclusiva por board + nome antes da reserva por proposta.
    # Caso um processo falhe depois daqui, a reserva permanece: fail-closed.
    claim_target(store, proposal_id, digest, request)

    ledger = store / "attempts"
    ledger.mkdir(parents=True, exist_ok=True)

    record_path = ledger / f"{proposal_id}.json"

    record = {
        "proposal_id": proposal_id,
        "proposal_sha256": digest,
        "operation": "create_sprint",
        "request": request,
        "reserved_at": datetime.now(timezone.utc).isoformat(),
        "status": "RESERVED",
        "outcome": "NOT_EXECUTED_BY_THIS_VERSION",
    }

    # Criacao exclusiva: a mesma proposta so pode obter
    # uma reserva neste diretorio.
    try:
        with record_path.open("x", encoding="utf-8") as file:
            json.dump(
                record,
                file,
                indent=2,
                ensure_ascii=False,
            )
            file.flush()
            os.fsync(file.fileno())
    except FileExistsError:
        raise ValueError(
            "Tentativa ja reservada para esta proposta. "
            "Repeticao bloqueada."
        ) from None

    # Nenhuma chamada de escrita e feita depois da reserva.
    return record