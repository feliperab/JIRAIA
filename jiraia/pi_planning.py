from urllib.parse import urlencode

from jiraia.client import JiraClient
from jiraia.planning import (
    BOARD_ID, PROJECT,
    collect_planning_snapshot,
    normalize_issue,
)
from scripts.inspect_planning import get_all_issues


def list_sprints(jira):
    results = []
    start = 0
    page_size = 50

    for _ in range(40):
        params = urlencode({
            "state": "active,future",
            "startAt": start,
            "maxResults": page_size,
        })
        data = jira.get(
            f"/rest/agile/1.0/board/{BOARD_ID}/sprint?{params}"
        )
        batch = data.get("values", [])
        results.extend(batch)
        start += len(batch)

        if data.get("isLast") is True:
            break
        if not batch:
            if data.get("isLast") is False:
                raise RuntimeError("Paginacao incompleta")
            break
        if data.get("total") is not None:
            if start >= data["total"]:
                break
        if len(batch) < page_size and data.get("isLast") is not False:
            break
    else:
        raise RuntimeError("Limite de paginas de sprints excedido")

    return results


def sprint_info(sprint):
    return {
        "id": sprint["id"],
        "name": sprint.get("name"),
        "state": sprint.get("state"),
        "start_date": sprint.get("startDate"),
        "end_date": sprint.get("endDate"),
        "goal": sprint.get("goal"),
    }


def collect_pi_snapshot(desired_sprints=5):
    if type(desired_sprints) is not int or not 1 <= desired_sprints <= 10:
        raise ValueError("desired_sprints deve ser de 1 a 10")

    jira = JiraClient.from_env()
    base = collect_planning_snapshot()
    all_sprints = list_sprints(jira)

    active = [
        s for s in all_sprints
        if s.get("state") == "active"
    ]
    future = [
        s for s in all_sprints
        if s.get("state") == "future"
    ]

    warnings = list(base["warnings"])

    if future and all(s.get("startDate") for s in future):
        future.sort(key=lambda s: s["startDate"])
    elif len(future) > 1:
        warnings.append(
            "Ordem cronologica das sprints futuras nao confirmada. "
            "Datas de inicio ausentes."
        )

    selected = future[:desired_sprints]
    points_field = base["story_points_field"]

    fields = [
        "summary", "status", "issuetype",
        "assignee", "priority", "parent"
    ]
    if points_field:
        fields.append(points_field)

    pi_sprints = []

    for sprint in selected:
        same_as_base = (
            base["future_sprint"] is not None
            and sprint["id"] == base["future_sprint"]["id"]
        )

        if same_as_base:
            issues = base["planned_issues"]
        else:
            raw = get_all_issues(
                jira,
                f"/rest/software/1.0/sprint/{sprint['id']}/issue",
                fields,
            )
            issues = [
                normalize_issue(item, points_field)
                for item in raw
                if item.get("key", "").startswith(PROJECT + "-")
            ]

        pi_sprints.append({
            **sprint_info(sprint),
            "issues": issues,
            "issue_count": len(issues),
        })

    missing = max(0, desired_sprints - len(selected))

    if missing:
        warnings.append(
            f"PI solicitado com {desired_sprints} sprints futuras, "
            f"mas somente {len(selected)} existem no board. "
            f"Faltam {missing} sprints para o horizonte solicitado."
        )

    if selected and any(
        not s.get("startDate") or not s.get("endDate")
        for s in selected
    ):
        warnings.append(
            "Datas de algumas sprints nao definidas. "
            "Calendario do PI ainda incompleto."
        )

    warnings.append(
        "Dependencias entre tarefas nao foram verificadas "
        "neste diagnostico. Nao inferir bloqueios ou precedencias."
    )

    return {
        "project": PROJECT,
        "board_id": BOARD_ID,
        "desired_sprints": desired_sprints,
        "future_sprints_available": len(future),
        "missing_sprint_slots": missing,
        "active_sprints": [sprint_info(s) for s in active],
        "pi_sprints": pi_sprints,
        "backlog": base["backlog"],
        "independent_candidates": base["independent_candidates"],
        "story_points_field": points_field,
        "warnings": list(dict.fromkeys(warnings)),
        "capacity_confirmed": False,
        "read_only": True,
        "instructions": (
            "Criar somente proposta preliminar. "
            "Nao inventar sprints, datas, estimativas, "
            "velocidade, capacidade ou dependencias. "
            "Distinguir fatos de sugestoes da IA. "
            "Nao modificar o Jira."
        ),
    }