"""Explicit, single-operation Jira Cloud writer; legacy write paths stay blocked.

Only supports a FUTURE sprint on board 1 of jiraia.atlassian.net. The CLI
requires a fresh, locally approved proposal AND a separate terminal phrase.
No retries, including on ambiguous POST outcomes.
"""

import argparse
import hmac
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from jiraia.action_engine import STORE, read_proposal
from jiraia.attempt_ledger import reserve_attempt
from jiraia.client import JiraClient
from jiraia.execution_guard import execution_phrase
from jiraia.executor import prepare_execution


ENDPOINT = "/rest/agile/1.0/sprint"
SITE = "https://jiraia.atlassian.net"


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


def select_proposal(filename=None, store=None):
    store = Path(store) if store is not None else STORE
    store = store.resolve()

    if filename is None:
        candidates = [
            p for p in store.glob("*.json")
            if re.fullmatch(r"[0-9a-f]{16}\.json", p.name)
            and p.is_file()
        ]

        if not candidates:
            raise ValueError("Nenhuma proposta local encontrada")

        path = max(
            candidates,
            key=lambda p: (p.stat().st_mtime_ns, p.name),
        ).resolve()
    else:
        path = Path(filename).resolve()

    if path.parent != store:
        raise ValueError("Proposta fora do diretorio autorizado")

    if not re.fullmatch(r"[0-9a-f]{16}\.json", path.name):
        raise ValueError("Nome de proposta invalido")

    if not path.is_file():
        raise ValueError("Arquivo de proposta nao encontrado")

    return path


def _require_site(jira):
    if type(jira) is not JiraClient:
        raise PermissionError("Executor nativo requer JiraClient original")
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


def _validate_payload(payload):
    if (
        type(payload) is not dict
        or set(payload) != {"name", "originBoardId"}
        or type(payload["originBoardId"]) is not int
        or payload["originBoardId"] != 1
        or type(payload["name"]) is not str
        or not 1 <= len(payload["name"]) <= 80
        or payload["name"] != payload["name"].strip()
    ):
        raise PermissionError("Apenas criacao de sprint futura no board 1")


def _post_one_future_sprint(jira, payload):
    """Dedicated authorized transport; JiraClient.post() stays blocked."""
    _require_site(jira)
    _validate_payload(payload)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        SITE + ENDPOINT,
        data=body,
        headers={
            "Authorization": "Basic " + jira.auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        if response.status != 201:
            raise RuntimeError("Resultado HTTP inesperado no POST")
        data = json.load(response)
    if not isinstance(data, dict):
        raise ValueError("Resposta da criacao nao e JSON objeto")
    return data


def execute_approved_once(proposal_file, jira, confirmation, *, store=None, send=None):
    """Execute max one dispatch; `send` exists only for offline tests.

    An existing target claim or dispatch marker is NEVER reset. If a POST may
    have been sent, its outcome is either verified or marked UNKNOWN.
    """
    store = Path(store) if store is not None else STORE
    store = store.resolve()
    path = Path(proposal_file).resolve()

    if send is None:
        _require_site(jira)
        if store != STORE.resolve():
            raise PermissionError("Store de producao inesperado")
    elif not callable(send):
        raise TypeError("Transporte de teste invalido")

    if path.parent != store:
        raise ValueError("Proposta fora do diretorio autorizado")
    proposal, _ = read_proposal(path)
    payload_precheck = {
        "name": proposal["parameters"]["name"],
        "originBoardId": proposal["target"]["board_id"],
    }
    _validate_payload(payload_precheck)
    expected = execution_phrase(proposal["id"], payload_precheck["name"])
    if type(confirmation) is not str or not hmac.compare_digest(confirmation, expected):
        raise PermissionError("Confirmacao final incorreta")

    # GET preflight + approval validation + target and proposal reservations.
    attempt = reserve_attempt(path, jira, confirmation, store=store)
    request = attempt["request"]
    if request.get("method") != "POST" or request.get("endpoint") != ENDPOINT:
        raise ValueError("Operacao fora da allowlist")
    payload = request["payload"]
    _validate_payload(payload)
    if payload != payload_precheck:
        raise ValueError("Payload mudou durante a reserva")

    proposal_id = attempt["proposal_id"]
    dispatch = {
        "proposal_id": proposal_id,
        "proposal_sha256": attempt["proposal_sha256"],
        "operation": "create_sprint",
        "request": request,
        "dispatch_prepared_at": datetime.now(timezone.utc).isoformat(),
        "status": "POST_MAY_HAVE_BEEN_SENT",
        "retry_allowed": False,
    }
    # Durable marker BEFORE the first and only possible POST.
    persist_once(store, "real_dispatch", proposal_id, dispatch)

    sprint_id = None
    try:
        created = (send(jira, payload) if send is not None
                   else _post_one_future_sprint(jira, payload))
        if not isinstance(created, dict):
            raise ValueError("Resposta de criacao invalida")
        sprint_id = created.get("id")
        if type(sprint_id) is not int or sprint_id <= 0:
            raise ValueError("ID retornado invalido")
        if not matches_sprint(created, sprint_id, payload):
            raise ValueError("Criacao nao corresponde a proposta")
        verified = jira.get(f"{ENDPOINT}/{sprint_id}")
        if not matches_sprint(verified, sprint_id, payload):
            raise ValueError("Verificacao posterior inconsistente")
    except Exception:
        # POST may have succeeded even if the response or verification failed.
        outcome = {
            "proposal_id": proposal_id,
            "status": "UNKNOWN_NEEDS_RECONCILIATION",
            "sprint_id_candidate": sprint_id if type(sprint_id) is int and sprint_id > 0 else None,
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

    outcome["recorded_at"] = datetime.now(timezone.utc).isoformat()
    persist_once(store, "real_outcomes", proposal_id, outcome)
    return outcome


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="JIRAIA: unica escrita real, com proposta e confirmacao humana"
    )
    parser.add_argument("proposal_file", help="Arquivo .jiraia/proposals/<id>.json")
    parser.add_argument("--execute", action="store_true", help="Habilitar pedido interativo")
    args = parser.parse_args(argv)

    # Reject non-interactive execution BEFORE any GET or reservation.
    if args.execute and not sys.stdin.isatty():
        raise PermissionError("Escrita exige terminal interativo")

    jira = JiraClient.from_env()
    _require_site(jira)
    path = select_proposal(args.proposal_file, store=STORE)
    proposal, _ = read_proposal(path)
    payload = {"name": proposal["parameters"]["name"],
               "originBoardId": proposal["target"]["board_id"]}
    _validate_payload(payload)

    preview = prepare_execution(path, jira, store=STORE)  # GET only
    if preview["request_preview"]["payload"] != payload:
        raise ValueError("Preflight diverge da proposta")
    print("\n===== JIRAIA - ESCRITA CONTROLADA =====")
    print("Instancia:", SITE)
    print("Operacao: criar sprint FUTURA")
    print("Board:", payload["originBoardId"])
    print("Nome:", payload["name"])
    print("Inicio, fim e goal: NAO DEFINIDOS")
    print("Proposta:", proposal["id"])
    print("Preflight: aprovado; somente GET ate este ponto")
    if not args.execute:
        print("[PREVIEW] Sem escrita. Use --execute somente com autorizacao especifica.")
        return 0

    phrase = execution_phrase(proposal["id"], payload["name"])
    print("\nATENCAO: a proxima etapa pode alterar o Jira real.")
    print("Digite exatamente para AUTORIZAR UMA UNICA escrita:", phrase)
    confirmation = input("Confirmacao: ")
    if not hmac.compare_digest(confirmation, phrase):
        print("[CANCELADO] Nenhuma reserva nem POST criado")
        return 2

    outcome = execute_approved_once(path, jira, confirmation)
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    return 0 if outcome["status"] == "SUCCESS_VERIFIED" else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PermissionError, ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        # No exception chaining: never print HTTP headers, credentials or authorization data.
        print("[BLOQUEADO] " + str(exc), file=sys.stderr)
        raise SystemExit(2) from None
