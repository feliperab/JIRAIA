from urllib.parse import urlencode

from jiraia.client import JiraClient
from scripts.inspect_planning import get_all_issues

BOARD_ID = 1
PROJECT = "SCRUM"


def normalize_issue(issue, points_field):
    fields = issue.get("fields") or {}
    issue_type = fields.get("issuetype") or {}
    status = fields.get("status") or {}
    assignee = fields.get("assignee") or {}
    priority = fields.get("priority") or {}
    parent = fields.get("parent") or {}

    type_name = issue_type.get("name", "")
    is_subtask = (
        issue_type.get("subtask", False)
        or type_name.casefold() in (
            "subtask", "sub-task", "subtarefa"
        )
    )

    points = fields.get(points_field) if points_field else None

    return {
        "key": issue["key"],
        "summary": fields.get("summary"),
        "type": type_name,
        "is_subtask": bool(is_subtask),
        "parent_key": parent.get("key"),
        "parent_resolution": (
            "resolved" if parent.get("key")
            else "not_returned" if is_subtask
            else "not_applicable"
        ),
        "status": status.get("name"),
        "status_category": (
            (status.get("statusCategory") or {}).get("key")
        ),
        "priority": priority.get("name"),
        "assignee": assignee.get("displayName"),
        "story_points": points,
    }


def collect_planning_snapshot():
    jira = JiraClient.from_env()

    catalog = jira.get("/rest/api/3/field")

    point_fields = [
        field for field in catalog
        if field.get("custom")
        and field.get("name", "").casefold() in (
            "story point estimate",
            "story points",
            "pontos de historia",
            "pontos de história",
        )
    ]

    points_field = (
        point_fields[0]["id"]
        if len(point_fields) == 1 else None
    )

    fields = [
        "summary", "status", "issuetype",
        "assignee", "priority", "parent"
    ]

    if points_field:
        fields.append(points_field)

    # Sprints futuras
    query = urlencode({
        "state": "future",
        "maxResults": 50
    })
    sprint_data = jira.get(
        f"/rest/agile/1.0/board/{BOARD_ID}/sprint?{query}"
    )

    if sprint_data.get("isLast") is False:
        raise RuntimeError("Lista de sprints incompleta")

    future = sprint_data.get("values", [])
    sprint = future[0] if future else None

    # Backlog
    backlog_raw = get_all_issues(
        jira,
        f"/rest/software/1.0/board/{BOARD_ID}/backlog",
        fields
    )

    # Proxima sprint
    planned_raw = []
    if sprint:
        planned_raw = get_all_issues(
            jira,
            f"/rest/software/1.0/sprint/{sprint['id']}/issue",
            fields
        )

    def normalize_collection(raw):
        return [
            normalize_issue(issue, points_field)
            for issue in raw
            if issue.get("key", "").startswith(PROJECT + "-")
        ]

    backlog = normalize_collection(backlog_raw)
    planned = normalize_collection(planned_raw)

    warnings = []

    if not sprint:
        warnings.append("Nenhuma sprint futura encontrada.")

    if not points_field:
        warnings.append(
            "Campo Story Points nao identificado de forma unica."
        )
    elif any(
        item["story_points"] is None
        for item in backlog + planned
    ):
        warnings.append(
            "Existem tarefas sem estimativa Story Points."
        )

    if any(item["is_subtask"] for item in backlog):
        warnings.append(
            "Subtarefas devem ser avaliadas junto de suas "
            "tarefas pai, nao como compromissos independentes."
        )

    if any(
        item["status_category"] == "indeterminate"
        for item in backlog
    ):
        warnings.append(
            "Existem itens em andamento no backlog; "
            "verificar sua situacao antes do planejamento."
        )

    unresolved = sorted({
        item["key"]
        for item in backlog + planned
        if item["is_subtask"]
        and item["parent_resolution"] != "resolved"
    })

    if unresolved:
        warnings.append(
            "Hierarquia de subtarefa nao confirmada pela API: "
            + ", ".join(unresolved)
            + ". Nao inferir tarefa pai ou dependencias."
        )

    warnings.append(
        "Capacidade nao calculada: faltam dados confiaveis "
        "sobre disponibilidade do time e velocity."
    )

    return {
        "project": PROJECT,
        "board_id": BOARD_ID,
        "future_sprint": (
            {
                "id": sprint["id"],
                "name": sprint.get("name"),
                "goal": sprint.get("goal"),
            }
            if sprint else None
        ),
        "story_points_field": points_field,
        "backlog": backlog,
        "planned_issues": planned,
        "independent_candidates": [
            item["key"]
            for item in backlog
            if not item["is_subtask"]
        ],
        "warnings": warnings,
        "read_only": True,
        "instructions": (
            "Proponha apenas um planejamento preliminar. "
            "Nao invente Story Points, capacidade, velocity "
            "ou prioridades nao sustentadas pelos dados. "
            "Nao mova tarefas no Jira."
        ),
    }