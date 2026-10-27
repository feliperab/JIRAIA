import base64
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode


class JiraClient:
    def __init__(self, url, email, token):
        self.url = url.rstrip("/")
        credentials = f"{email}:{token}"
        self.auth = base64.b64encode(
            credentials.encode("utf-8")
        ).decode("ascii")

    @classmethod
    def from_env(cls):
        env_path = Path(__file__).resolve().parents[1] / ".env"

        config = {}
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip().strip('"').strip("'")

        required = ("JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN")
        missing = [key for key in required if not config.get(key)]

        if missing:
            raise ValueError(f"Configuracao ausente: {', '.join(missing)}")

        return cls(
            config["JIRA_URL"],
            config["JIRA_EMAIL"],
            config["JIRA_API_TOKEN"]
        )

    def get(self, endpoint):
        if not endpoint.startswith("/") or endpoint.startswith("//"):
            raise ValueError("Endpoint invalido")

        request = Request(
            self.url + endpoint,
            headers={
                "Authorization": f"Basic {self.auth}",
                "Accept": "application/json"
            },
            method="GET"
        )

        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            raise RuntimeError(
                f"Jira API retornou HTTP {error.code}"
            ) from None
        except URLError:
            raise RuntimeError(
                "Nao foi possivel conectar ao Jira"
            ) from None

    def myself(self):
        return self.get("/rest/api/3/myself")

    def get_issue(self, key, fields=None):
        endpoint = "/rest/api/3/issue/" + quote(key, safe="")

        if fields:
            endpoint += "?" + urlencode({
                "fields": ",".join(fields)
            })

        return self.get(endpoint)