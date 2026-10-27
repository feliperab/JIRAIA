import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jiraia.action_engine import STORE, read_proposal
from jiraia.executor import prepare_execution


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


def local_preview(filename=None, store=None):
    store = Path(store) if store is not None else STORE
    store = store.resolve()

    path = select_proposal(filename, store)
    proposal, _ = read_proposal(path)

    if (
        proposal.get("schema_version") != 1
        or proposal.get("operation") != "create_sprint"
        or proposal.get("state") != "PENDING_APPROVAL"
        or proposal.get("id") != path.stem
    ):
        raise ValueError("Proposta com estrutura nao permitida")

    target = proposal["target"]
    parameters = proposal["parameters"]

    board_id = target["board_id"]
    name = parameters["name"]

    if (
        type(board_id) is not int
        or board_id <= 0
        or not isinstance(name, str)
        or not 1 <= len(name.strip()) <= 80
        or name != name.strip()
    ):
        raise ValueError("Dados da proposta invalidos")

    created = datetime.fromisoformat(proposal["created_at"])

    if created.tzinfo is None:
        raise ValueError("Data da proposta sem fuso horario")

    age = datetime.now(timezone.utc) - created

    if age < timedelta(0):
        validity = "DATA_INCONSISTENTE"
    elif age > timedelta(minutes=30):
        validity = "EXPIRADA"
    else:
        validity = "DENTRO_DO_PRAZO"

    proposal_id = proposal["id"]

    return path, {
        "proposal_id": proposal_id,
        "operation": "create_sprint",
        "board_id": board_id,
        "board_name": target.get("board_name"),
        "sprint_name": name,
        "validade_temporal": validity,
        "recibo_local_presente": path.with_suffix(
            ".approval.json"
        ).is_file(),
        "recibo_validado": False,
        "tentativa_reservada": (
            store / "attempts" / f"{proposal_id}.json"
        ).exists(),
        "despacho_registrado": (
            store / "real_dispatch" / f"{proposal_id}.json"
        ).exists(),
        "mode": "PREVIEW_ONLY",
        "network_access": False,
        "ready_to_execute": False,
        "executed": False,
    }


def main(argv=None, *, store=None, jira_factory=None):
    parser = argparse.ArgumentParser(
        description="JIRAIA Action Engine - interface protegida"
    )

    parser.add_argument(
        "proposal_file",
        nargs="?",
        help="Arquivo da proposta (padrao: mais recente)",
    )

    parser.add_argument(
        "--check-jira",
        action="store_true",
        help="Revalidar por GET, sem executar escrita",
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help="Reservado; escrita bloqueada nesta versao",
    )

    args = parser.parse_args(argv)

    # Bloquear antes de carregar arquivos, credenciais ou Jira.
    if args.execute:
        print(
            "[BLOQUEADO] Execucao real nao habilitada "
            "nesta interface."
        )
        print("[INFO] Nenhum POST foi enviado.")
        return 2

    try:
        path, preview = local_preview(
            args.proposal_file,
            store=store,
        )

        print("\n===== JIRAIA ACTION PREVIEW =====")
        print(json.dumps(
            preview,
            indent=2,
            ensure_ascii=False,
        ))

        if not args.check_jira:
            print("\n[OK] Preview local concluido")
            print("[INFO] Nenhum acesso a rede")
            return 0

        if (
            preview["tentativa_reservada"]
            or preview["despacho_registrado"]
        ):
            raise ValueError(
                "Tentativa ou despacho anterior registrado. "
                "Nao reutilizar a proposta."
            )

        if jira_factory is None:
            from jiraia.client import JiraClient
            jira = JiraClient.from_env()
        else:
            jira = jira_factory()

        result = prepare_execution(
            path,
            jira,
            store=store,
        )

        print("\n===== PREFLIGHT SOMENTE LEITURA =====")
        print(json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ))

        print("\n[OK] Preflight GET concluido")
        print("[INFO] Execucao real continua bloqueada")
        return 0

    except (
        ValueError,
        RuntimeError,
        KeyError,
        TypeError,
        FileNotFoundError,
    ) as exc:
        print(f"\n[BLOQUEADO] {exc}")
        print("[INFO] Nenhuma escrita realizada por esta interface")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())