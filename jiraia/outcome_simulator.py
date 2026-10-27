import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


def record_simulated_outcome(
    store,
    proposal_id,
    scenario,
    fake_response=None,
):
    """
    Registra um resultado ficticio para uma tentativa reservada.

    Nao utiliza rede, nao acessa credenciais e nao chama JiraClient.post.
    Nunca transforma uma simulacao em execucao real.
    """
    store = Path(store).resolve()

    if (
        not isinstance(proposal_id, str)
        or re.fullmatch(r"[0-9a-f]{16}", proposal_id) is None
    ):
        raise ValueError("ID de proposta invalido")

    if scenario not in ("success", "unknown"):
        raise ValueError("Cenario nao permitido")

    attempt_path = (
        store / "attempts" / f"{proposal_id}.json"
    )

    if not attempt_path.is_file():
        raise ValueError("Tentativa reservada nao encontrada")

    attempt = json.loads(
        attempt_path.read_text(encoding="utf-8")
    )

    if (
        attempt.get("proposal_id") != proposal_id
        or attempt.get("status") != "RESERVED"
        or attempt.get("outcome")
            != "NOT_EXECUTED_BY_THIS_VERSION"
    ):
        raise ValueError("Registro de tentativa invalido")

    request = attempt.get("request")

    if not isinstance(request, dict):
        raise ValueError("Requisicao reservada invalida")

    payload = request.get("payload")

    if (
        request.get("method") != "POST"
        or request.get("endpoint") != "/rest/agile/1.0/sprint"
        or not isinstance(payload, dict)
        or set(payload) != {"name", "originBoardId"}
    ):
        raise ValueError("Operacao reservada nao permitida")

    if scenario == "success":
        if (
            not isinstance(fake_response, dict)
            or type(fake_response.get("id")) is not int
            or fake_response["id"] <= 0
            or fake_response.get("name") != payload["name"]
            or fake_response.get("originBoardId")
                != payload["originBoardId"]
            or fake_response.get("state") != "future"
        ):
            raise ValueError(
                "Resposta ficticia de sucesso invalida"
            )

        status = "SIMULATED_SUCCESS"
        next_action = "SIMULATION_ONLY"

    else:
        if fake_response is not None:
            raise ValueError(
                "Resultado desconhecido nao aceita resposta"
            )

        status = "SIMULATED_UNKNOWN"
        next_action = "VERIFY_JIRA_MANUALLY_NO_AUTO_RETRY"

    record = {
        "proposal_id": proposal_id,
        "scenario": scenario,
        "status": status,
        "recorded_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "fake_response": fake_response,
        "simulated": True,
        "executed": False,
        "http_sent": False,
        "next_action": next_action,
    }

    folder = store / "simulated_outcomes"
    folder.mkdir(parents=True, exist_ok=True)

    path = folder / f"{proposal_id}.json"

    try:
        with path.open("x", encoding="utf-8") as file:
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
            "Resultado ja registrado. Repeticao bloqueada."
        ) from None

    return record