import base64
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"

def load_env():
    config = {}

    for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        config[key.strip()] = value.strip().strip('"').strip("'")

    required = ["JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"]
    missing = [key for key in required if not config.get(key)]

    if missing:
        raise ValueError(f"Variaveis ausentes no .env: {missing}")

    return config

def main():
    config = load_env()

    base_url = config["JIRA_URL"].rstrip("/")
    credentials = f'{config["JIRA_EMAIL"]}:{config["JIRA_API_TOKEN"]}'

    encoded = base64.b64encode(
        credentials.encode("utf-8")
    ).decode("ascii")

    headers = {
        "Authorization": f"Basic {encoded}",
        "Accept": "application/json"
    }

    def jira_get(endpoint):
        request = Request(
            f"{base_url}{endpoint}",
            headers=headers,
            method="GET"
        )

        with urlopen(request, timeout=30) as response:
            return json.load(response)

    print("\n===== JIRAIA - TESTE DE CONEXAO =====")

    user = jira_get("/rest/api/3/myself")

    print(f"[OK] Autenticado: {user['displayName']}")
    print(f"[OK] Instancia: {base_url}")

    issue = jira_get(
        "/rest/api/3/issue/SCRUM-1"
        "?fields=summary,status,assignee,updated"
    )

    fields = issue["fields"]

    print("\n===== PRIMEIRA TAREFA =====")
    print(f"Chave: {issue['key']}")
    print(f"Titulo: {fields['summary']}")
    print(f"Status: {fields['status']['name']}")

    assignee = fields.get("assignee")
    print(
        "Responsavel:",
        assignee["displayName"] if assignee else "Nao atribuido"
    )

    print("\n[OK] Integracao REST API funcionando!")

if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        print(f"[ERRO] Jira retornou HTTP {error.code}")
        sys.exit(1)
    except URLError as error:
        print(f"[ERRO] Falha de conexao: {error.reason}")
        sys.exit(1)
    except Exception as error:
        print(f"[ERRO] {error}")
        sys.exit(1)