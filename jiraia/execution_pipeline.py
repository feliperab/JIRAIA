import json
import os
from datetime import datetime, timezone
from pathlib import Path

from jiraia.action_engine import STORE
from jiraia.attempt_ledger import reserve_attempt
from jiraia.outcome_simulator import record_simulated_outcome


def run_offline_once(
    proposal_file,
    jira_reader,
    confirmation,
    scenario,
    store=None,
):
    """
    Coordena uma tentativa inteiramente simulada.

    Ordem:
      1. Validar autorizacao e estado do board
      2. Reservar tentativa persistente
      3. Registrar marcador antes do resultado
      4. Simular sucesso, incerteza ou interrupcao

    Nenhum POST e realizado.
    """
    if scenario not in ("success", "unknown", "interrupt"):
        raise ValueError("Cenario de simulacao invalido")

    store = Path(store) if store is not None else STORE
    store = store.resolve()

    # O registro exclusivo e criado antes do resultado.
    attempt = reserve_attempt(
        proposal_file,
        jira_reader,
        confirmation,
        store=store,
    )

    proposal_id = attempt["proposal_id"]
    request = attempt["request"]

    # Marcador persistente anterior a qualquer resultado.
    marker_folder = store / "dispatch_previews"
    marker_folder.mkdir(parents=True, exist_ok=True)

    marker_path = marker_folder / f"{proposal_id}.json"

    marker = {
        "proposal_id": proposal_id,
        "operation": "create_sprint",
        "reserved_at": attempt["reserved_at"],
        "marked_at": datetime.now(timezone.utc).isoformat(),
        "status": "OFFLINE_DISPATCH_MARKED",
        "network_allowed": False,
        "http_sent": False,
        "executed": False,
    }

    try:
        with marker_path.open("x", encoding="utf-8") as file:
            json.dump(
                marker,
                file,
                indent=2,
                ensure_ascii=False,
            )
            file.flush()
            os.fsync(file.fileno())
    except FileExistsError:
        raise ValueError(
            "Marcador de despacho ja existe. "
            "Repeticao bloqueada."
        ) from None

    # Simular interrupcao depois da reserva.
    # A reserva permanece e impede uma nova tentativa.
    if scenario == "interrupt":
        raise RuntimeError(
            "Interrupcao simulada apos a reserva. "
            "Tentativa permanece bloqueada."
        )

    if scenario == "unknown":
        return record_simulated_outcome(
            store,
            proposal_id,
            "unknown",
        )

    # Resposta ficticia. ID nunca obtido do Jira.
    payload = request["payload"]

    fake_response = {
        "id": 999001,
        "name": payload["name"],
        "state": "future",
        "originBoardId": payload["originBoardId"],
    }

    return record_simulated_outcome(
        store,
        proposal_id,
        "success",
        fake_response=fake_response,
    )