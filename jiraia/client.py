import urllib.parse
import urllib.request
import urllib.error
import base64
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode


def _require_write_transport_activation():
    """
    Transporte POST desabilitado nesta versao.

    Nao existe chave booleana ou variavel de ambiente
    que autorize acesso real a rede por este caminho.
    """
    raise PermissionError(
        "Transporte HTTP de escrita desabilitado. "
        "Autorizacao de producao ainda nao implementada."
    )


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

    def post(self, endpoint, payload, *, allow_write=False):
        """
        POST restrito a criacao de sprint.
        Bloqueado por padrao. O executor devera autorizar
        explicitamente cada chamada apos validacao.
        """
        if allow_write is not True:
            raise PermissionError(
                "POST bloqueado: autorizacao de escrita ausente"
            )

        if endpoint != "/rest/agile/1.0/sprint":
            raise ValueError("Endpoint de escrita nao permitido")

        if not isinstance(payload, dict):
            raise ValueError("Payload invalido")

        if set(payload) != {"name", "originBoardId"}:
            raise ValueError("Campos de payload nao permitidos")

        name = payload["name"]
        board_id = payload["originBoardId"]

        if (
            not isinstance(name, str)
            or not 1 <= len(name.strip()) <= 80
            or name != name.strip()
            or type(board_id) is not int
            or board_id <= 0
        ):
            raise ValueError("Parametros de sprint invalidos")

        parsed = urllib.parse.urlparse(self.url)

        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("URL Jira invalida para escrita")

        _require_write_transport_activation()

        body = json.dumps(
            payload,
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            self.url.rstrip("/") + endpoint,
            data=body,
            headers={
                "Authorization": f"Basic {self.auth}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request, timeout=20
            ) as response:
                status = response.status
                raw = response.read()

        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"Jira rejeitou POST: HTTP {exc.code}. "
                "Nenhum detalhe de credencial sera exibido."
            ) from None

        except urllib.error.URLError:
            raise RuntimeError(
                "Falha de comunicacao no POST. "
                "Estado da operacao desconhecido; "
                "verifique o Jira antes de repetir."
            ) from None

        if status != 201:
            raise RuntimeError(
                f"Resposta HTTP inesperada: {status}. "
                "Verifique o Jira antes de repetir."
            )

        try:
            result = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise RuntimeError(
                "Resposta invalida apos POST. "
                "Verifique o Jira antes de repetir."
            ) from None

        if not isinstance(result, dict):
            raise RuntimeError(
                "Resposta inesperada apos POST. "
                "Verifique o Jira antes de repetir."
            )

        return result
