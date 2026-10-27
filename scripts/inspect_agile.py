from urllib.parse import urlencode
from jiraia.client import JiraClient


def main():
    jira = JiraClient.from_env()

    print("\n===== JIRAIA - AGILE DISCOVERY =====")

    params = urlencode({
        "projectKeyOrId": "SCRUM",
        "maxResults": 50
    })

    data = jira.get(f"/rest/agile/1.0/board?{params}")
    boards = data.get("values", [])

    print(f"\nBoards encontrados: {len(boards)}")

    if not data.get("isLast", True):
        print("[AVISO] Existem mais boards para consultar.")

    if not boards:
        print("[AVISO] Nenhum board encontrado para SCRUM.")
        return

    for board in boards:
        board_id = board["id"]
        board_type = board.get("type", "desconhecido")

        print(f"\n===== BOARD {board_id} =====")
        print(f"Nome: {board.get('name')}")
        print(f"Tipo: {board_type}")

        if board_type != "scrum":
            print("Board sem sprints Scrum.")
            continue

        try:
            sprints = jira.get(
                f"/rest/agile/1.0/board/{board_id}/sprint"
                "?state=active&maxResults=50"
            )
        except RuntimeError as error:
            print(f"[AVISO] Nao foi possivel consultar sprints: {error}")
            continue

        active = sprints.get("values", [])

        if not active:
            print("Nenhuma sprint ativa.")
            continue

        if not sprints.get("isLast", True):
            print("[AVISO] Existem mais sprints para consultar.")

        for sprint in active:
            print(f"\nSprint ID: {sprint['id']}")
            print(f"Nome: {sprint.get('name')}")
            print(f"Estado: {sprint.get('state')}")
            print(f"Inicio: {sprint.get('startDate', 'Nao definido')}")
            print(f"Fim: {sprint.get('endDate', 'Nao definido')}")
            print(f"Objetivo: {sprint.get('goal') or 'Nao definido'}")

    print("\n[OK] Diagnostico Agile concluido.")


if __name__ == "__main__":
    main()