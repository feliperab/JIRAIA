import hmac
import json
from datetime import datetime, timezone
from pathlib import Path

from jiraia.action_engine import STORE, read_proposal
from jiraia.executor import prepare_execution


def execution_phrase(proposal_id, sprint_name):
    return f"EXECUTAR {proposal_id} {sprint_name}"


def simulate_once(proposal_file, jira, confirmation, store=None):
    """
    Simula a autorizacao final e registra uso unico.
    NUNCA chama JiraClient.post ou qualquer metodo de escrita.
    """
    store = Path(store) if store is not None else STORE
    store = store.resolve()
    path = Path(proposal_file).resolve()

    # Reutilizar todas as validacoes do executor v0.2
    preview = prepare_execution(path, jira, store=store)

    if (
        preview.get("executed") is not False
        or preview.get("requires_new_execution_confirmation") is not True
    ):
        raise ValueError("Estado de preflight invalido")

    request = preview["request_preview"]

    if (
        request["method"] != "POST"
        or request["endpoint"] != "/rest/agile/1.0/sprint"
    ):
        raise ValueError("Operacao nao permitida")

    proposal_id = preview["proposal_id"]
    sprint_name = request["payload"]["name"]

    expected = execution_phrase(proposal_id, sprint_name)

    if (
        type(confirmation) is not str
        or not hmac.compare_digest(confirmation, expected)
    ):
        raise PermissionError(
            "Confirmacao final ausente ou incorreta"
        )

    _, digest = read_proposal(path)

    # Registros somente de simulacao.
    # Nao consomem aprovacoes para uma futura execucao real.
    ledger = store / "simulations"
    ledger.mkdir(parents=True, exist_ok=True)

    record_path = ledger / f"{proposal_id}.json"

    record = {
        "proposal_id": proposal_id,
        "proposal_sha256": digest,
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "operation": "create_sprint",
        "request_preview": request,
        "status": "SIMULATED_ONLY",
        "simulated": True,
        "executed": False,
        "http_sent": False,
    }

    # A criacao exclusiva impede reutilizacao local do mesmo ID.
    try:
        with record_path.open("x", encoding="utf-8") as file:
            json.dump(
                record,
                file,
                indent=2,
                ensure_ascii=False,
            )
    except FileExistsError:
        raise ValueError(
            "Simulacao ja registrada para esta proposta. "
            "Repeticao bloqueada."
        ) from None

    return record