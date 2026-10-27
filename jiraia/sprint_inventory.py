"""Inventario completo de sprints. Somente GET."""

from urllib.parse import urlencode


def list_sprint_names(jira, board_id):
    if type(board_id) is not int or board_id <= 0:
        raise ValueError("Board ID invalido")

    names = []
    start = 0

    for _ in range(40):
        query = urlencode({
            "state": "active,future,closed",
            "startAt": start,
            "maxResults": 50,
        })

        page = jira.get(
            f"/rest/agile/1.0/board/{board_id}/sprint?{query}"
        )

        if (
            not isinstance(page, dict)
            or type(page.get("isLast")) is not bool
        ):
            raise RuntimeError(
                "Lista de sprints incompleta ou invalida"
            )

        items = page.get("values")

        if (
            not isinstance(items, list)
            or any(
                not isinstance(item, dict)
                or not isinstance(item.get("name"), str)
                or not item["name"].strip()
                for item in items
            )
        ):
            raise RuntimeError("Pagina de sprints invalida")

        if "startAt" in page and (
            type(page["startAt"]) is not int
            or page["startAt"] != start
        ):
            raise RuntimeError(
                "Paginacao de sprints inconsistente"
            )

        if "total" in page and (
            type(page["total"]) is not int
            or page["total"] < start + len(items)
            or (
                page["isLast"]
                and page["total"] != start + len(items)
            )
        ):
            raise RuntimeError(
                "Contagem de sprints inconsistente"
            )

        names.extend(item["name"] for item in items)

        if page["isLast"]:
            return names

        if not items:
            raise RuntimeError(
                "Pagina intermediaria vazia"
            )

        start += len(items)

    raise RuntimeError("Limite de paginacao atingido")
