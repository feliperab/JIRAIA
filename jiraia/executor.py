import argparse
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jiraia.action_engine import (
    STORE,
    build_create_sprint,
    read_proposal,
)
from jiraia.client import JiraClient


def prepare_execution(proposal_file, jira, store=None):
    store = Path(store) if store is not None else STORE
    path = Path(proposal_file).resolve()

    if path.parent != store.resolve():
        raise ValueError("Proposta fora do diretorio permitido")

    proposal, digest = read_proposal(path)

    if path.name != f"{proposal['id']}.json":
        raise ValueError("ID e nome do arquivo nao correspondem")

    if proposal.get("schema_version") != 1:
        raise ValueError("Versao de proposta nao suportada")

    if proposal.get("state") != "PENDING_APPROVAL":
        raise ValueError("Estado de proposta invalido")

    receipt_path = path.with_suffix(".approval.json")

    if not receipt_path.is_file():
        raise ValueError("Recibo de aprovacao nao encontrado")

    receipt = json.loads(
        receipt_path.read_text(encoding="utf-8")
    )

    if receipt.get("proposal_id") != proposal["id"]:
        raise ValueError("ID do recibo nao corresponde")

    if not hmac.compare_digest(
        str(receipt.get("proposal_sha256", "")),
        digest
    ):
        raise ValueError("Hash do recibo nao corresponde")

    if receipt.get("status") != "APPROVED_FOR_FUTURE_REVALIDATION":
        raise ValueError("Status de aprovacao invalido")

    if receipt.get("executed") is not False:
        raise ValueError("Proposta ja executada ou estado desconhecido")

    now = datetime.now(timezone.utc)
    created = datetime.fromisoformat(proposal["created_at"])
    approved = datetime.fromisoformat(receipt["approved_at"])

    if created.tzinfo is None or approved.tzinfo is None:
        raise ValueError("Datas sem fuso horario")

    if not (created <= approved <= now):
        raise ValueError("Sequencia temporal inconsistente")

    ttl = timedelta(minutes=30)

    if now - created > ttl or now - approved > ttl:
        raise ValueError(
            "Proposta ou aprovacao expirada. "
            "Gere uma nova proposta."
        )

    board_id = proposal["target"]["board_id"]
    sprint_name = proposal["parameters"]["name"]

    # Consultas GET ao Jira; nenhuma escrita.
    current = build_create_sprint(
        jira, board_id, sprint_name
    )

    if current["target"]["board_name"] != (
        proposal["target"]["board_name"]
    ):
        raise ValueError("Nome do board foi alterado")

    before = sorted(
        name.casefold()
        for name in proposal["observed"]["existing_sprint_names"]
    )

    after = sorted(
        name.casefold()
        for name in current["observed"]["existing_sprint_names"]
    )

    if before != after:
        raise ValueError(
            "Lista de nomes de sprints mudou. "
            "Gere uma nova proposta."
        )

    return {
        "proposal_id": proposal["id"],
        "operation": "create_sprint",
        "request_preview": {
            "method": "POST",
            "endpoint": "/rest/agile/1.0/sprint",
            "payload": {
                "name": sprint_name,
                "originBoardId": board_id,
            },
        },
        "approval_validated": True,
        "board_revalidated": True,
        "ready_to_execute": False,
        "requires_new_execution_confirmation": True,
        "executed": False,
    }


def main():
    parser = argparse.ArgumentParser(
        description="JIRAIA - preflight somente leitura"
    )
    parser.add_argument("proposal_file")
    args = parser.parse_args()

    jira = JiraClient.from_env()
    result = prepare_execution(args.proposal_file, jira)

    print("\n===== JIRAIA EXECUTION PREFLIGHT =====")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("\n[OK] Pre-validacao aprovada")
    print("[INFO] Nenhum POST foi enviado ao Jira")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, KeyError, TypeError) as exc:
        raise SystemExit(f"[BLOQUEADO] {exc}")