"""Reconciliacao de sprint existente. Somente GET no Jira."""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from jiraia.action_engine import STORE, read_proposal
from jiraia.client import JiraClient


def reconcile(jira, *, store=STORE, record=False):
    site = urlsplit(jira.url)

    if (
        site.scheme != "https"
        or site.hostname != "jiraia.atlassian.net"
        or site.username
        or site.password
        or site.port not in (None, 443)
        or site.path not in ("", "/")
        or site.query
        or site.fragment
    ):
        raise ValueError(
            "Instancia Jira inesperada. Nada sera registrado."
        )

    # Confirmar board por GET.
    board = jira.get("/rest/agile/1.0/board/1")

    if (
        not isinstance(board, dict)
        or board.get("id") != 1
    ):
        raise ValueError("Board 1 nao confirmado")

    location = board.get("location") or {}

    if (
        isinstance(location, dict)
        and location.get("projectKey") not in (None, "SCRUM")
    ):
        raise ValueError(
            "Board nao corresponde ao projeto SCRUM"
        )

    # Consultar todas as paginas e estados das sprints.
    sprints = []
    start = 0

    for _ in range(40):
        query = urlencode({
            "state": "active,future,closed",
            "startAt": start,
            "maxResults": 50,
        })

        endpoint = (
            "/rest/agile/1.0/board/1/sprint?"
            + query
        )

        page = jira.get(endpoint)

        if (
            not isinstance(page, dict)
            or type(page.get("isLast")) is not bool
        ):
            raise ValueError(
                "Paginacao de sprints nao confirmada"
            )

        batch = page.get("values")

        if (
            not isinstance(batch, list)
            or not all(isinstance(x, dict) for x in batch)
        ):
            raise ValueError("Resposta de sprints invalida")

        if page.get("startAt", start) != start:
            raise ValueError(
                "Paginacao de sprints inconsistente"
            )

        sprints.extend(batch)

        if page["isLast"]:
            break

        if not batch:
            raise ValueError(
                "Paginacao interrompida sem resultado final"
            )

        start += len(batch)
    else:
        raise ValueError("Limite de paginacao atingido")

    matches = [
        item
        for item in sprints
        if (
            isinstance(item.get("name"), str)
            and item["name"].strip().casefold()
            == "scrum sprint 2"
        )
    ]

    if len(matches) != 1:
        raise ValueError(
            "Sprint 2 ausente ou nome duplicado; "
            "nao reconciliar"
        )

    if (
        type(matches[0].get("id")) is not int
        or matches[0]["id"] != 3
    ):
        raise ValueError(
            "ID da sprint nao corresponde ao esperado (3)"
        )

    # Confirmar tambem pela API de detalhes da sprint.
    details = jira.get("/rest/agile/1.0/sprint/3")

    if (
        not isinstance(details, dict)
        or type(details.get("id")) is not int
        or details["id"] != 3
        or details.get("name") != "SCRUM Sprint 2"
        or details.get("state") != "future"
        or details.get("originBoardId") != 1
    ):
        raise ValueError(
            "Detalhes da sprint nao confirmados: "
            "nome, estado ou board"
        )

    # Identificar propostas locais antigas sem modifica-las.
    store = Path(store).resolve()
    proposal_ids = []

    if store.is_dir():
        for path in sorted(store.glob("*.json")):
            if not re.fullmatch(
                r"[0-9a-f]{16}\.json",
                path.name,
            ):
                continue

            proposal, _ = read_proposal(path)

            if (
                proposal.get("operation") == "create_sprint"
                and proposal.get("target", {}).get(
                    "board_id"
                ) == 1
                and str(
                    proposal.get("parameters", {}).get(
                        "name", ""
                    )
                ).strip().casefold() == "scrum sprint 2"
            ):
                proposal_ids.append(path.stem)

    result = {
        "status": "EXTERNAL_SPRINT_OBSERVED",
        "jira_site": "https://jiraia.atlassian.net",
        "board_id": 1,
        "sprint_id": 3,
        "sprint_name": "SCRUM Sprint 2",
        "sprint_state": "future",
        "related_proposal_ids": proposal_ids,
        "jira_requests": "GET_ONLY",
        "executed_by_jiraia": False,
    }

    if record:
        folder = store.parent / "reconciliations"
        folder.mkdir(parents=True, exist_ok=True)

        path = folder / (
            "create_sprint-board_1-sprint_3.json"
        )

        evidence = dict(
            result,
            observed_at=datetime.now(
                timezone.utc
            ).isoformat(),
        )

        # Registro exclusivo: nunca sobrescrever evidencia.
        try:
            with path.open("x", encoding="utf-8") as output:
                json.dump(
                    evidence,
                    output,
                    ensure_ascii=False,
                    indent=2,
                )
                output.flush()
                os.fsync(output.fileno())

            result["local_record"] = "CREATED"

        except FileExistsError:
            old = json.loads(
                path.read_text(encoding="utf-8")
            )

            for key, value in result.items():
                if key == "related_proposal_ids":
                    continue

                if old.get(key) != value:
                    raise ValueError(
                        "Registro existente inconsistente; "
                        "arquivo preservado"
                    )

            result["local_record"] = "ALREADY_EXISTS"

        result["record_path"] = str(path)

    return result


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Reconciliar a sprint 3 sem escrita no Jira"
        )
    )

    parser.add_argument(
        "--record",
        action="store_true",
        help="Gravar evidencia local apos confirmar via GET",
    )

    args = parser.parse_args()

    jira = JiraClient.from_env()

    result = reconcile(
        jira,
        record=args.record,
    )

    print(json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
    ))

    print("[OK] Nenhum POST enviado pelo reconciliador")


if __name__ == "__main__":
    try:
        main()
    except (
        ValueError,
        RuntimeError,
        OSError,
        KeyError,
        TypeError,
    ) as exc:
        raise SystemExit(f"[BLOQUEADO] {exc}")
