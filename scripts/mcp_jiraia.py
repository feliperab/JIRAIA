import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP
from jiraia.client import JiraClient
from scripts.daily import active_sprint, sprint_issues, analyze

mcp = FastMCP("JIRAIA")


@mcp.tool()
def jiraia_daily() -> dict:
    """Consulta a sprint ativa e gera um diagnostico de daily somente leitura."""
    jira = JiraClient.from_env()
    sprint = active_sprint(jira)
    issues = sprint_issues(jira, sprint["id"])
    tasks = [analyze(issue) for issue in issues]

    signals = []
    for task in tasks:
        alerts = []

        if task["blocked"]:
            alerts.append("Possivel bloqueio")
        if task["stale"]:
            alerts.append("Sem atualizacao ha pelo menos 2 dias")
        if not task["done"] and task["owner"] == "Nao atribuido":
            alerts.append("Sem responsavel")

        if alerts:
            signals.append({
                "key": task["key"],
                "alerts": alerts
            })

    return {
        "project": "SCRUM",
        "sprint": {
            "id": sprint["id"],
            "name": sprint["name"],
            "goal": sprint.get("goal"),
        },
        "total": len(tasks),
        "by_status": dict(Counter(t["status"] for t in tasks)),
        "by_owner": dict(Counter(t["owner"] for t in tasks)),
        "issues": tasks,
        "signals": signals,
        "note": "Alertas sao heuristicas. days_since_update mede tempo desde a ultima atualizacao, nao idade da tarefa. Ausencia de bloqueios sinalizados nao comprova ausencia de impedimentos."
    }



@mcp.tool()
def jiraia_sprint_planning() -> dict:
    """
    Consulta backlog e sprint futura para apoiar Sprint Planning.
    Somente leitura. Nao estima capacidade nem altera o Jira.
    """
    from jiraia.planning import collect_planning_snapshot
    return collect_planning_snapshot()


@mcp.tool()
def jiraia_pi_planning(desired_sprints: int = 5) -> dict:
    """
    Diagnostica o PI, sprints futuras e backlog.
    Somente leitura; nao altera tarefas ou sprints.
    """
    from jiraia.pi_planning import collect_pi_snapshot
    return collect_pi_snapshot(desired_sprints)

if __name__ == "__main__":
    mcp.run(transport="stdio")