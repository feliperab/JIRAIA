import argparse
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from jiraia.client import JiraClient

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

    query = urlencode({
        "state": "active,future",
        "maxResults": 50,
    })

    existing = jira.get(
        f"/rest/agile/1.0/board/{board_id}/sprint?{query}"
    )

    if existing.get("isLast") is not True:
        raise RuntimeError(
            "Lista de sprints nao confirmada como completa"
        )

    existing_names = [
        s.get("name", "") for s in existing.get("values", [])
    ]

    if any(n.casefold() == name.casefold() for n in existing_names):
        raise ValueError(
            f"Ja existe uma sprint ativa ou futura chamada {name}"
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

    receipt = {
        "proposal_id": proposal["id"],
        "proposal_sha256": digest,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "status": "APPROVED_FOR_FUTURE_REVALIDATION",
        "executed": False,
    }

    receipt_path = path.with_suffix(".approval.json")

    with receipt_path.open("x", encoding="utf-8") as file:
        json.dump(receipt, file, indent=2)

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