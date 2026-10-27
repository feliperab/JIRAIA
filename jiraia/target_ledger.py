"""Reserva local e exclusiva por destino da escrita. Nunca faz HTTP."""

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


_ID = re.compile(r"[0-9a-f]{16}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def claim_target(store, proposal_id, proposal_sha256, request):
    """Bloqueia concorrencia entre propostas distintas para o mesmo alvo.

    Retem a reserva inclusive em falhas posteriores. Nao concede
    autorizacao para escrita, nem libera reexecucao ou retry.
    """
    if (
        type(proposal_id) is not str
        or not _ID.fullmatch(proposal_id)
        or type(proposal_sha256) is not str
        or not _SHA.fullmatch(proposal_sha256)
    ):
        raise ValueError("Identificacao ou hash de proposta invalido")

    if not isinstance(request, dict) or (
        request.get("method") != "POST"
        or request.get("endpoint") != "/rest/agile/1.0/sprint"
    ):
        raise ValueError("Operacao fora da lista permitida")

    payload = request.get("payload")
    if not isinstance(payload, dict) or set(payload) != {
        "name", "originBoardId"
    }:
        raise ValueError("Payload de sprint invalido")

    name = payload["name"]
    board_id = payload["originBoardId"]
    if (
        type(name) is not str
        or not 1 <= len(name) <= 80
        or name != name.strip()
        or type(board_id) is not int
        or board_id <= 0
    ):
        raise ValueError("Parametros de sprint invalidos")

    identity = {
        "operation": "create_sprint",
        "board_id": board_id,
        "normalized_name": name.strip().casefold(),
    }
    key = hashlib.sha256(
        json.dumps(
            identity, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    folder = Path(store).resolve() / "target_claims"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (key + ".json")
    record = {
        "status": "TARGET_RESERVED",
        "operation": "create_sprint",
        "proposal_id": proposal_id,
        "proposal_sha256": proposal_sha256,
        "target": identity,
        "reserved_at": datetime.now(timezone.utc).isoformat(),
        "retry_allowed": False,
    }
    try:
        with path.open("x", encoding="utf-8") as file:
            json.dump(record, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
    except FileExistsError:
        raise ValueError(
            "Alvo de sprint ja reservado. Repeticao bloqueada. "
            "Revisao humana necessaria; nao remover o marcador automaticamente."
        ) from None
    return record
