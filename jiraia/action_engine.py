import argparse
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jiraia.client import JiraClient
from jiraia.sprint_inventory import list_sprint_names

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / ".jiraia" / "proposals"


def checksum(proposal):
    content = json.dumps(
        proposal,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def build_create_sprint(jira, board_id, name):
    if type(board_id) is not int or board_id <= 0:
        raise ValueError("Board ID invalido")

    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("Nome da sprint invalido")

    name = name.strip()

    board = jira.get(f"/rest/agile/1.0/board/{board_id}")

    existing_names = list_sprint_names(jira, board_id)
    if any(
        existing.strip().casefold() == name.casefold()
        for existing in existing_names
    ):
        raise ValueError(
            f"Ja existe uma sprint chamada {name}"
        )
    return {
        "schema_version": 1,
        "id": secrets.token_hex(8),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "operation": "create_sprint",
        "target": {
            "board_id": board_id,
            "board_name": board.get("name"),
        },
        "parameters": {
            "name": name,
        },
        "observed": {
            "existing_sprint_names": existing_names,
        },
        "description": (
            f"Proposta de criar a sprint '{name}' "
            f"no board {board_id}, sem iniciar a sprint."
        ),
        "state": "PENDING_APPROVAL",
    }


def save_proposal(proposal, folder=STORE):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    envelope = {
        "proposal": proposal,
        "sha256": checksum(proposal),
    }

    path = folder / f"{proposal['id']}.json"

    with path.open("x", encoding="utf-8") as file:
        json.dump(envelope, file, indent=2, ensure_ascii=False)

    return path


def read_proposal(path):
    path = Path(path)
    envelope = json.loads(path.read_text(encoding="utf-8"))

    proposal = envelope["proposal"]
    expected = checksum(proposal)
    received = envelope["sha256"]

    if not hmac.compare_digest(expected, received):
        raise ValueError("Proposta modificada desde a criacao")

    if proposal.get("operation") != "create_sprint":
        raise ValueError("Operacao nao permitida")

    return proposal, expected


def record_approval(path, proposal, digest):
    """Save an approval receipt without interactive input.

    Called by approve_proposal() after terminal confirmation, or by
    external flows (MCP elicitation, tests) that have already obtained
    explicit human authorisation by other means.

    Uses open("x") + fsync so a receipt can only be written once.
    Returns the Path of the created receipt file.
    """
    receipt = {
        "proposal_id": proposal["id"],
        "proposal_sha256": digest,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "status": "APPROVED_FOR_FUTURE_REVALIDATION",
        "executed": False,
    }
    receipt_path = Path(path).with_suffix(".approval.json")
    with receipt_path.open("x", encoding="utf-8") as file:
        json.dump(receipt, file, indent=2, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    return receipt_path


def approve_proposal(path):
    path = Path(path).resolve()

    if path.parent != STORE.resolve():
        raise ValueError("Proposta fora do diretorio autorizado")

    proposal, digest = read_proposal(path)

    if proposal.get("state") != "PENDING_APPROVAL":
        raise ValueError("Estado da proposta invalido")

    created = datetime.fromisoformat(proposal["created_at"])

    if datetime.now(timezone.utc) - created > timedelta(minutes=30):
        raise ValueError(
            "Proposta expirada. Gere uma nova para aprovacao."
        )

    print("\n===== REVISAO DA PROPOSTA =====")
    print("ID:", proposal["id"])
    print("Operacao:", proposal["operation"])
    print("Board:", proposal["target"]["board_name"])
    print("Nome:", proposal["parameters"]["name"])
    print("Descricao:", proposal["description"])
    print("Hash:", digest)
    print("\nNenhuma alteracao sera executada nesta versao.")

    challenge = f"APROVAR {proposal['id']}"
    confirmation = input(
        f"\nDigite exatamente '{challenge}' para aprovar: "
    ).strip()

    if confirmation != challenge:
        print("[CANCELADO] Aprovacao nao concedida")
        return False

    record_approval(path, proposal, digest)
    print("[OK] Aprovacao local registrada")
    print("[INFO] Nenhuma chamada de escrita foi realizada")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="JIRAIA Action Engine - dry-run"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("propose-create-sprint")
    create.add_argument("--board", type=int, default=1)
    create.add_argument("--name", required=True)

    approve = sub.add_parser("approve")
    approve.add_argument("proposal_file")

    args = parser.parse_args()

    if args.command == "propose-create-sprint":
        jira = JiraClient.from_env()
        proposal = build_create_sprint(
            jira, args.board, args.name
        )
        path = save_proposal(proposal)

        print("\n===== JIRAIA ACTION PREVIEW =====")
        print("ID:", proposal["id"])
        print("Acao:", proposal["description"])
        print("Estado:", proposal["state"])
        print("Arquivo:", path)
        print("[OK] Proposta criada. Jira nao alterado.")

    elif args.command == "approve":
        approve_proposal(args.proposal_file)


if __name__ == "__main__":
    main()