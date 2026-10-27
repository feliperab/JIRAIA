from jiraia.client import JiraClient

def main():
    jira = JiraClient.from_env()
    board_id = 1

    print("\n===== JIRAIA - BOARD FEATURES =====")

    features = jira.get(
        f"/rest/agile/1.0/board/{board_id}/features"
    )

    for feature in features.get("features", []):
        name = feature.get("boardFeature", "UNKNOWN")
        state = feature.get("state", "UNKNOWN")
        print(f"{name}: {state}")

    print("\n===== SPRINTS =====")

    try:
        data = jira.get(
            f"/rest/agile/1.0/board/{board_id}/sprint"
            "?state=active,future&maxResults=50"
        )

        sprints = data.get("values", [])

        print(f"Sprints encontradas: {len(sprints)}")

        for sprint in sprints:
            print(f"\nID: {sprint['id']}")
            print(f"Nome: {sprint.get('name')}")
            print(f"Estado: {sprint.get('state')}")
            print(f"Objetivo: {sprint.get('goal') or 'Nao definido'}")

        if data.get("isLast") is False:
            print("[AVISO] Existem mais paginas de sprints.")

    except RuntimeError as error:
        print(f"[AVISO] Consulta de sprints: {error}")

    print("\n[OK] Diagnostico finalizado.")

if __name__ == "__main__":
    main()