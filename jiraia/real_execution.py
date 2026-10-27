import json
import os
from datetime import datetime, timezone
from pathlib import Path

from jiraia.action_engine import STORE
from jiraia.attempt_ledger import reserve_attempt


ENDPOINT = "/rest/agile/1.0/sprint"


def persist_once(store, folder_name, proposal_id, record):
    folder = Path(store).resolve() / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{proposal_id}.json"

    try:
        with path.open("x", encoding="utf-8") as file:
            json.dump(record, file, indent=2, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
    except FileExistsError:
        raise ValueError(
            "Registro ja existe. Repeticao bloqueada."
        ) from None

    return path


def matches_sprint(data, sprint_id, payload):
    return (
        isinstance(data, dict)
        and type(data.get("id")) is int
        and data["id"] == sprint_id
        and data.get("name") == payload["name"]
        and data.get("originBoardId") == payload["originBoardId"]
        and data.get("state") == "future"
    )


def execute_create_sprint_once(
    proposal_file,
    jira,
    confirmation,
    *,
    enable_real_write=False,
    store=None,
):
    """
    Executor de uso unico.

    Nao ha CLI de escrita nesta versao.
    Por padrao, nenhuma operacao pode ser executada.

    Requer:
    - aprovacao valida;
    - confirmacao final;
    - board sem mudancas;
    - reserva persistente;
    - habilitacao explicita.

    Qualquer incerteza apos o despacho exige
    reconciliacao. Nunca faz retry automatico.
    """
    if enable_real_write is not True:
        raise PermissionError(
            "Escrita real desabilitada por padrao"
        )

    # Bloqueio temporario de producao.
    # Clientes ficticios continuam permitidos nos testes.
    # Nunca confundir esta verificacao com uma fronteira
    # de seguranca contra codigo Python malicioso.
    from jiraia.client import JiraClient

    if isinstance(jira, JiraClient):
        raise PermissionError(
            "Cliente Jira real bloqueado nesta versao. "
            "Escrita em producao ainda nao autorizada."
        )

    store = Path(store) if store is not None else STORE
    store = store.resolve()

    # Executa o preflight e reserva antes do POST.
    attempt = reserve_attempt(
        proposal_file,
        jira,
        confirmation,
        store=store,
    )

    proposal_id = attempt["proposal_id"]
    request = attempt["request"]

    if (
        request.get("method") != "POST"
        or request.get("endpoint") != ENDPOINT
    ):
        raise ValueError("Operacao nao permitida")

    payload = request["payload"]

    # Este marcador existe ANTES da chamada POST.
    # Se o processo parar depois daqui, nao tentar
    # novamente com a mesma proposta.
    dispatch = {
        "proposal_id": proposal_id,
        "proposal_sha256": attempt["proposal_sha256"],
        "operation": "create_sprint",
        "request": request,
        "dispatch_prepared_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": "POST_MAY_HAVE_BEEN_SENT",
        "retry_allowed": False,
    }

    persist_once(
        store, "real_dispatch", proposal_id, dispatch
    )

    sprint_id = None

    try:
        # Unica chamada POST permitida nesta funcao.
        created = jira.post(
            ENDPOINT,
            payload,
            allow_write=True,
        )

        if not isinstance(created, dict):
            raise ValueError("Resposta POST inesperada")

        sprint_id = created.get("id")

        if (
            type(sprint_id) is not int
            or sprint_id <= 0
            or not matches_sprint(
                created, sprint_id, payload
            )
        ):
            raise ValueError(
                "Resposta POST nao corresponde a proposta"
            )

        # Verificar a sprint criada por ID.
        verified = jira.get(
            f"/rest/agile/1.0/sprint/{sprint_id}"
        )

        if not matches_sprint(
            verified, sprint_id, payload
        ):
            raise ValueError(
                "Verificacao posterior inconsistente"
            )

    except Exception:
        # Nao expor a excecao original:
        # mensagens HTTP podem conter dados sensiveis.
        # O POST pode ter sido processado pelo Jira.
        outcome = {
            "proposal_id": proposal_id,
            "status": "UNKNOWN_NEEDS_RECONCILIATION",
            "sprint_id_candidate": (
                sprint_id if type(sprint_id) is int
                and sprint_id > 0 else None
            ),
            "retry_allowed": False,
            "next_action": "VERIFY_JIRA_BEFORE_NEW_PROPOSAL",
        }

    else:
        outcome = {
            "proposal_id": proposal_id,
            "status": "SUCCESS_VERIFIED",
            "sprint_id": sprint_id,
            "sprint_name": payload["name"],
            "origin_board_id": payload["originBoardId"],
            "retry_allowed": False,
        }

    outcome["recorded_at"] = datetime.now(
        timezone.utc
    ).isoformat()

    # Se a gravacao falhar, a reserva e o marcador
    # anteriores continuam bloqueando repeticoes.
    persist_once(
        store, "real_outcomes", proposal_id, outcome
    )

    return outcome