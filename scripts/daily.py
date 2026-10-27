from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlencode

from jiraia.client import JiraClient

BOARD_ID = 1
PROJECT = "SCRUM"
STALE_DAYS = 2


def active_sprint(jira):
    query = urlencode({"state": "active", "maxResults": 50})
    data = jira.get(
        f"/rest/agile/1.0/board/{BOARD_ID}/sprint?{query}"
    )
    if data.get("isLast") is False:
        raise RuntimeError("Lista de sprints incompleta")

    sprints = [
        s for s in data.get("values", [])
        if s.get("state") == "active"
    ]
    if len(sprints) != 1:
        raise RuntimeError(
            f"Esperada 1 sprint ativa; encontradas {len(sprints)}"
        )
    return sprints[0]


def sprint_issues(jira, sprint_id):
    issues = []
    token = None
    seen_tokens = set()

    for _ in range(100):
        params = {
            "maxResults": 50,
            "fields": "summary,status,assignee,updated,labels"
        }
        if token:
            params["nextPageToken"] = token

        query = urlencode(params)
        data = jira.get(
            f"/rest/software/1.0/sprint/{sprint_id}/issue?{query}"
        )
        issues.extend(data.get("issues", []))

        token = data.get("nextPageToken")
        if not token:
            if data.get("isLast") is False:
                raise RuntimeError("Paginacao incompleta")
            break

        if token in seen_tokens:
            raise RuntimeError("Token de paginacao repetido")
        seen_tokens.add(token)
    else:
        raise RuntimeError("Limite de paginas excedido")

    return [
        issue for issue in issues
        if issue.get("key", "").startswith(PROJECT + "-")
    ]


def analyze(issue):
    fields = issue.get("fields") or {}
    status = fields.get("status") or {}
    category = (status.get("statusCategory") or {}).get("key", "")
    status_name = status.get("name", "Desconhecido")
    assignee = fields.get("assignee")

    owner = (
        assignee.get("displayName", "Nao atribuido")
        if assignee else "Nao atribuido"
    )

    labels = [
        str(x).casefold() for x in (fields.get("labels") or [])
    ]

    blocked = (
        any(term in status_name.casefold()
            for term in ("bloque", "imped", "blocked"))
        or any(label in (
            "blocked", "bloqueado", "impedido", "impedimento"
        ) for label in labels)
    )

    updated = fields.get("updated")
    days_since_update = None

    if updated:
        dt = datetime.fromisoformat(
            updated.replace("Z", "+00:00")
        )
        days_since_update = max(
            0, (datetime.now(timezone.utc) - dt).total_seconds()
            / 86400
        )

    in_progress = category == "indeterminate"
    stale = (
        in_progress
        and days_since_update is not None
        and days_since_update >= STALE_DAYS
    )

    return {
        "key": issue["key"],
        "summary": fields.get("summary", ""),
        "status": status_name,
        "owner": owner,
        "done": category == "done",
        "blocked": blocked,
        "stale": stale,
        "days_since_update": days_since_update
    }


def main():
    jira = JiraClient.from_env()
    sprint = active_sprint(jira)
    issues = sprint_issues(jira, sprint["id"])
    tasks = [analyze(issue) for issue in issues]

    print("\n========== JIRAIA DAILY COPILOT ==========")
    print("Projeto:", PROJECT)
    print("Sprint:", sprint["name"])
    print("Sprint ID:", sprint["id"])
    print("Objetivo:", sprint.get("goal") or "Nao definido")
    print("Total de tarefas:", len(tasks))

    print("\n--- STATUS ---")
    for status, count in sorted(
        Counter(t["status"] for t in tasks).items()
    ):
        print(f"{status}: {count}")

    print("\n--- RESPONSAVEIS ---")
    for owner, count in sorted(
        Counter(t["owner"] for t in tasks).items()
    ):
        print(f"{owner}: {count}")

    print("\n--- SINAIS PARA A DAILY ---")
    signals = []

    for task in tasks:
        flags = []
        if task["blocked"]:
            flags.append("Possivel bloqueio")
        if task["stale"]:
            flags.append(
                f"Sem atualizacao >= {STALE_DAYS} dias"
            )
        if not task["done"] and task["owner"] == "Nao atribuido":
            flags.append("Sem responsavel")

        if flags:
            signals.append((task, flags))

    if not signals:
        print("Nenhum sinal identificado pelas regras atuais.")
    else:
        for task, flags in signals[:30]:
            print(
                f"{task['key']} | {task['status']} | "
                f"{task['summary']}"
            )
            print("  Alertas:", ", ".join(flags))
        if len(signals) > 30:
            print(f"... e mais {len(signals) - 30} tarefas.")

    print("\n[OK] Relatorio concluido - somente leitura")
    print(
        "Nota: sinais sao heuristicas, nao confirmacoes "
        "de impedimentos ou ausencia de trabalho."
    )


if __name__ == "__main__":
    main()