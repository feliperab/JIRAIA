from urllib.parse import urlencode
from jiraia.client import JiraClient

BOARD_ID = 1
PROJECT = "SCRUM"


def get_all_issues(jira, endpoint, fields):
    issues = []
    token = None
    seen = set()

    for _ in range(100):
        params = {
            "maxResults": 50,
            "fields": ",".join(fields)
        }
        if token:
            params["nextPageToken"] = token

        data = jira.get(endpoint + "?" + urlencode(params))
        issues.extend(data.get("issues", []))

        if data.get("isLast") is True:
            return issues

        token = data.get("nextPageToken")
        if not token:
            if data.get("isLast") is False:
                raise RuntimeError("Paginacao incompleta")
            return issues

        if token in seen:
            raise RuntimeError("Token de paginacao repetido")
        seen.add(token)

    raise RuntimeError("Limite de paginas excedido")


def show_issues(label, issues, estimate_fields):
    issues = [
        i for i in issues
        if i.get("key", "").startswith(PROJECT + "-")
    ]

    print(f"\n===== {label} =====")
    print(f"Total: {len(issues)}")

    for issue in issues[:30]:
        f = issue.get("fields") or {}
        status = (f.get("status") or {}).get("name", "?")
        summary = f.get("summary") or ""
        kind = (f.get("issuetype") or {}).get("name", "?")

        print(
            f"{issue['key']} | {kind} | {status} | {summary}"
        )

        for field in estimate_fields:
            value = f.get(field["id"])
            if value is not None:
                print(f"  {field['name']}: {value}")

    if len(issues) > 30:
        print(f"... mais {len(issues) - 30} tarefas")


def main():
    jira = JiraClient.from_env()

    print("\n===== JIRAIA - PLANNING DISCOVERY =====")

    # Identificar campos de estimativa existentes
    fields_catalog = jira.get("/rest/api/3/field")

    estimate_fields = [
        f for f in fields_catalog
        if f.get("custom")
        and (
            "story point" in f.get("name", "").lower()
            or "ponto" in f.get("name", "").lower()
        )
    ]

    print("\n--- CAMPOS DE ESTIMATIVA ---")
    if not estimate_fields:
        print("Nenhum campo Story Points identificado.")

    for f in estimate_fields:
        print(f"{f['id']} | {f['name']}")

    if len(estimate_fields) != 1:
        print(
            "Campo de estimativa ainda nao confirmado; "
            "nenhuma capacidade sera calculada."
        )

    requested_fields = [
        "summary", "status", "issuetype", "assignee",
        "priority"
    ]
    requested_fields.extend(f["id"] for f in estimate_fields)

    # Descobrir a proxima sprint
    params = urlencode({
        "state": "future",
        "maxResults": 50
    })
    sprints_data = jira.get(
        f"/rest/agile/1.0/board/{BOARD_ID}/sprint?{params}"
    )

    if sprints_data.get("isLast") is False:
        raise RuntimeError("Lista de sprints futuras incompleta")

    future = sprints_data.get("values", [])

    print("\n--- SPRINTS FUTURAS ---")
    for sprint in future:
        print(f"{sprint['id']} | {sprint['name']}")

    # Consultar backlog
    backlog = get_all_issues(
        jira,
        f"/rest/software/1.0/board/{BOARD_ID}/backlog",
        requested_fields
    )
    show_issues("BACKLOG", backlog, estimate_fields)

    # Consultar primeira sprint futura
    if future:
        sprint = future[0]

        issues = get_all_issues(
            jira,
            f"/rest/software/1.0/sprint/{sprint['id']}/issue",
            requested_fields
        )
        show_issues(
            f"SPRINT FUTURA: {sprint['name']}",
            issues,
            estimate_fields
        )
    else:
        print("\nNenhuma sprint futura encontrada.")

    print("\n[OK] Diagnostico concluido - somente leitura")


if __name__ == "__main__":
    main()