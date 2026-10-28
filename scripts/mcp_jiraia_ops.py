"""JIRAIA operations: scoped Jira Cloud access with one human MCP approval per write.

All network writes are exclusively user-authorized; no model-supplied approval.
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from mcp.server.elicitation import AcceptedElicitation
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jiraia.action_engine import STORE, build_create_sprint, checksum, record_approval, save_proposal
from jiraia.client import JiraClient
from jiraia.execution_guard import execution_phrase
from jiraia.native_write import _require_site, execute_approved_once

mcp = FastMCP("JIRAIA Operations")
AUDIT = ROOT / ".jiraia" / "ops_attempts"
ISSUE = re.compile(r"SCRUM-[1-9][0-9]*\Z", re.I)

class Decision(BaseModel):
    resposta: str = Field(description="Digite SIM, NAO ou OK. A recusa tambem pode ser feita com Decline.")


def _client():
    jira = JiraClient.from_env()
    _require_site(jira)
    return jira


def _issue_key(key):
    if type(key) is not str or ISSUE.fullmatch(key) is None:
        raise ValueError("Issue deve ter formato SCRUM-123")
    return key.upper()


def _issue(jira, key):
    data = jira.get("/rest/api/3/issue/" + quote(_issue_key(key), safe=""))
    if data.get("key", "").upper() != key.upper() or data.get("fields", {}).get("project", {}).get("key") != "SCRUM":
        raise PermissionError("Issue fora do projeto SCRUM")
    return data


def _sprint(jira, sid, future=False):
    if type(sid) is not int or sid < 1:
        raise ValueError("ID da sprint invalido")
    data = jira.get(f"/rest/agile/1.0/sprint/{sid}")
    if data.get("originBoardId") != 1:
        raise PermissionError("Sprint fora do board 1")
    if future and data.get("state") != "future":
        raise PermissionError("Somente sprint futura")
    return data


def _plain(text, limit=3000):
    if type(text) is not str or not text.strip() or len(text) > limit:
        raise ValueError("Texto obrigatorio, tamanho invalido")
    return text.strip()


def _adf(text):
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def _adf_text(doc):
    def collect(node):
        if isinstance(node, dict):
            return (node.get("text", "") if node.get("type") == "text" else "") + "".join(collect(x) for x in node.get("content", []))
        return ""
    return collect(doc)


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _persist_once(folder, name, data):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name + ".json")
    with path.open("x", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    return path


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Redirect proibido em escrita Jira")


def _send(jira, method, endpoint, payload):
    _require_site(jira)
    if method not in ("POST", "PUT") or not endpoint.startswith("/rest/") or "?" in endpoint or "#" in endpoint:
        raise PermissionError("Metodo ou endpoint nao permitido")
    # Defense in depth: endpoints and methods are explicitly dispatched below.
    allowed = (
        method == "POST" and endpoint in ("/rest/api/3/issue",)
        or method == "PUT" and bool(re.fullmatch(r"/rest/api/3/issue/SCRUM-[1-9][0-9]*", endpoint))
        or method == "POST" and bool(re.fullmatch(r"/rest/api/3/issue/SCRUM-[1-9][0-9]*/transitions", endpoint))
        or method == "POST" and bool(re.fullmatch(r"/rest/api/3/issue/SCRUM-[1-9][0-9]*/comment", endpoint))
        or method == "POST" and bool(re.fullmatch(r"/rest/agile/1\.0/sprint/[1-9][0-9]*/issue", endpoint))
        or method == "POST" and bool(re.fullmatch(r"/rest/agile/1\.0/sprint/[1-9][0-9]*", endpoint))
    )
    if not allowed:
        raise PermissionError("Endpoint fora da allowlist")
    req = Request("https://jiraia.atlassian.net" + endpoint,
                  data=_canonical(payload).encode("utf-8"), method=method,
                  headers={"Authorization": "Basic " + jira.auth,
                           "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with build_opener(_NoRedirect()).open(req, timeout=20) as response:
            if response.status not in (200, 201, 204):
                raise RuntimeError("HTTP inesperado")
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        raise RuntimeError(f"Jira HTTP {e.code}; nao repetir automaticamente") from None
    except (URLError, OSError, ValueError):
        raise RuntimeError("Resultado de escrita incerto; nao repetir automaticamente") from None


async def _confirm(ctx, summary):
    # The user answers the MCP form, not a tool argument controlled by the model.
    try:
        result = await ctx.elicit(
            message="JIRAIA - AUTORIZACAO DE ESCRITA REAL\n\n" + summary +
                    "\n\nAutoriza EXATAMENTE estas alteracoes? Digite SIM, OK ou NAO.",
            schema=Decision)
    except Exception:
        return False
    if not isinstance(result, AcceptedElicitation):
        return False
    answer = getattr(getattr(result, "data", None), "resposta", None)
    return type(answer) is str and answer.strip().casefold() in ("sim", "ok")


async def _dispatch(jira, *, kind, method, endpoint, payload, snapshot, fresh, verify):
    """Preflight recheck, durable reservation, one dispatch. Only call after human approval."""
    if _canonical(fresh()) != _canonical(snapshot):
        return {"status": "DADOS_ALTERADOS_SEM_POST"}
    fingerprint = hashlib.sha256(_canonical({"kind": kind, "endpoint": endpoint,
                   "payload": payload, "before": snapshot}).encode("utf-8")).hexdigest()
    try:
        _persist_once(AUDIT, fingerprint, {"kind": kind, "method": method,
            "endpoint": endpoint, "payload": payload, "status": "DISPATCH_MAY_HAVE_OCCURRED",
            "created_at": datetime.now(timezone.utc).isoformat(), "retry_allowed": False})
    except FileExistsError:
        return {"status": "OPERACAO_JA_RESERVADA", "retry_allowed": False}
    try:
        result = _send(jira, method, endpoint, payload)
        verified = verify(result)
        if not verified:
            raise RuntimeError("Verificacao posterior inconclusiva")
        outcome = {"status": "SUCCESS_VERIFIED", "result": result, "retry_allowed": False}
    except Exception:
        outcome = {"status": "UNKNOWN_NEEDS_RECONCILIATION", "retry_allowed": False}
    _persist_once(AUDIT / "outcomes", fingerprint, outcome)
    return {**outcome, "audit_id": fingerprint[:20]}


async def _write(ctx, jira, *, kind, label, method, endpoint, payload, snapshot, fresh, verify):
    if not await _confirm(ctx, label + "\n" + _canonical(payload)):
        return {"status": "CANCELADO_SEM_POST"}
    return await _dispatch(jira, kind=kind, method=method, endpoint=endpoint, payload=payload,
                           snapshot=snapshot, fresh=fresh, verify=verify)


@mcp.tool()
def jiraia_buscar_issues(filtro: str = "ORDER BY updated DESC", limite: int = 30) -> dict:
    """Consultar issues SCRUM. Informe filtro JQL opcional; somente leitura."""
    jira = _client()
    if type(filtro) is not str or len(filtro) > 500 or ";" in filtro:
        raise ValueError("Filtro JQL invalido")
    if type(limite) is not int or not 1 <= limite <= 100:
        raise ValueError("Limite invalido")
    condition = filtro.strip()
    if condition and "ORDER BY" in condition.upper() and not condition.upper().startswith("ORDER BY"):
        raise ValueError("Separe o filtro do ORDER BY")
    jql = "project = SCRUM " + ("AND (" + condition + ")" if condition and not condition.upper().startswith("ORDER BY") else condition)
    q = urlencode({"jql": jql, "maxResults": limite,
                   "fields": "summary,status,issuetype,assignee,priority,updated,customfield_10016"})
    data = jira.get("/rest/api/3/search/jql?" + q)
    items = []
    for issue in data.get("issues", []):
        if ISSUE.fullmatch(issue.get("key", "")):
            f = issue.get("fields", {})
            items.append({"key": issue["key"], "summary": f.get("summary"),
                          "status": (f.get("status") or {}).get("name"),
                          "assignee": (f.get("assignee") or {}).get("displayName"),
                          "points": f.get("customfield_10016")})
    return {"issues": items, "next_page_token": data.get("nextPageToken"), "read_only": True}


@mcp.tool()
def jiraia_detalhar_issue(chave: str) -> dict:
    """Detalhar issue do projeto SCRUM; somente leitura."""
    return _issue(_client(), _issue_key(chave))


@mcp.tool()
def jiraia_listar_transicoes(chave: str) -> dict:
    """Listar status disponiveis para uma issue antes de transicionar."""
    jira = _client(); key = _issue_key(chave); _issue(jira, key)
    data = jira.get(f"/rest/api/3/issue/{key}/transitions")
    return {"issue": key, "transitions": [{"id": x["id"], "name": x["name"],
             "to": x.get("to", {}).get("name")} for x in data.get("transitions", [])]}


@mcp.tool()
def jiraia_tipos_issue() -> dict:
    """Listar tipos de issues permitidos no projeto SCRUM para criacao."""
    jira = _client()
    project = jira.get("/rest/api/3/project/SCRUM")
    types = project.get("issueTypes") or []
    if not types:
        other = jira.get("/rest/api/3/issuetype/project?" + urlencode({"projectId": project["id"]}))
        types = other.get("values", []) if isinstance(other, dict) else other
    return {"tipos": [{"id": x.get("id"), "name": x.get("name"),
                        "subtarefa": x.get("subtask")} for x in types]}


@mcp.tool()
def jiraia_buscar_usuarios(termo: str) -> dict:
    """Buscar responsaveis atribuiveis ao projeto SCRUM; somente leitura."""
    jira = _client()
    q = urlencode({"project": "SCRUM", "query": _plain(termo, 100), "maxResults": 30})
    users = jira.get("/rest/api/3/user/assignable/search?" + q)
    return {"usuarios": [{"account_id": u.get("accountId"),
                              "nome": u.get("displayName"), "ativo": u.get("active")} for u in users]}


@mcp.tool()
async def jiraia_criar_sprint(nome: str, ctx: Context) -> dict:
    """Criar sprint FUTURA no board 1, com um formulario SIM/NAO/OK."""
    jira = _client()
    proposta = build_create_sprint(jira, 1, _plain(nome, 80))
    path = save_proposal(proposta)
    titulo = proposta["parameters"]["name"]
    if not await _confirm(ctx, f"Criar sprint FUTURA '{titulo}' no board 1, sem iniciar.\nSite: https://jiraia.atlassian.net"):
        return {"status": "CANCELADO_SEM_POST", "proposal_id": proposta["id"]}
    # Compatibility with vetted native executor; no code phrase is shown to user.
    record_approval(path, proposta, checksum(proposta))
    return execute_approved_once(path, jira, execution_phrase(proposta["id"], titulo))


@mcp.tool()
async def jiraia_criar_sprint_com_issues(nome: str, chaves: list[str], ctx: Context) -> dict:
    """Criar sprint futura e alocar ate 20 issues, com uma unica aprovacao SIM/NAO/OK.

    Operacoes sao sequenciais, nao atomicas. Se a alocacao falhar apos
    criacao, reporta sucesso parcial e nao tenta repetir.
    """
    jira = _client()
    title = _plain(nome, 80)
    if type(chaves) is not list or not 1 <= len(chaves) <= 20:
        raise ValueError("Quantidade de issues invalida")
    keys = [_issue_key(x) for x in chaves]
    if len(keys) != len(set(keys)):
        raise ValueError("Issues duplicadas")
    proposal = build_create_sprint(jira, 1, title)
    snapshots = [_issue(jira, k)["fields"].get("updated") for k in keys]
    path = save_proposal(proposal)
    if not await _confirm(ctx, f"PACOTE DE 2 OPERACOES REAIS NO BOARD 1\n"
                          f"1. Criar sprint FUTURA: {title}\n"
                          f"2. Mover {len(keys)} issues para ela: {', '.join(keys)}\n"
                          "Nao e transacao atomica: pode haver sucesso parcial."):
        return {"status": "CANCELADO_SEM_POST", "proposal_id": proposal["id"]}
    if [_issue(jira, k)["fields"].get("updated") for k in keys] != snapshots:
        return {"status": "DADOS_ALTERADOS_SEM_POST"}
    record_approval(path, proposal, checksum(proposal))
    sprint_result = execute_approved_once(path, jira, execution_phrase(proposal["id"], title))
    if sprint_result.get("status") != "SUCCESS_VERIFIED":
        return {"status": "SPRINT_NAO_CONFIRMADA", "sprint": sprint_result, "retry_allowed": False}
    sid = sprint_result["sprint_id"]
    target = _sprint(jira, sid, future=True)
    def membership(_):
        seen = set(); start = 0
        for _page in range(50):
            page = jira.get(f"/rest/agile/1.0/sprint/{sid}/issue?startAt={start}&maxResults=100")
            issues = page.get("issues", [])
            seen.update(x.get("key") for x in issues)
            if set(keys) <= seen: return True
            if page.get("isLast") is True or len(issues) < 100: return False
            start += len(issues)
        return False
    move = await _dispatch(jira, kind="issue_move_after_sprint_create",
        method="POST", endpoint=f"/rest/agile/1.0/sprint/{sid}/issue",
        payload={"issues": keys},
        snapshot={"sprint": target["name"], "updated": snapshots},
        fresh=lambda: {"sprint": _sprint(jira, sid, True)["name"],
                       "updated": [_issue(jira, k)["fields"].get("updated") for k in keys]},
        verify=membership)
    return {"status": "SUCCESS_VERIFIED" if move["status"] == "SUCCESS_VERIFIED" else "PARTIAL_SUCCESS_REVIEW_REQUIRED",
            "sprint": sprint_result, "allocation": move, "retry_allowed": False}


@mcp.tool()
async def jiraia_criar_issue(resumo: str, tipo: str, ctx: Context, descricao: str = "") -> dict:
    """Criar issue no projeto SCRUM (tipos disponiveis: consultar projeto)."""
    jira = _client(); summary = _plain(resumo, 240); typ = _plain(tipo, 80)
    project = jira.get("/rest/api/3/project/SCRUM")
    types = project.get("issueTypes") or []
    if not types:
        other = jira.get("/rest/api/3/issuetype/project?" + urlencode({"projectId": project["id"]}))
        types = other.get("values", []) if isinstance(other, dict) else other
    matches = [x for x in types if x.get("name", "").casefold() == typ.casefold() and not x.get("subtask")]
    if len(matches) != 1:
        return {"status": "TIPO_NAO_ENCONTRADO", "tipos": [x.get("name") for x in types if not x.get("subtask")]}
    payload = {"fields": {"project": {"key": "SCRUM"}, "issuetype": {"id": matches[0]["id"]}, "summary": summary}}
    if descricao.strip(): payload["fields"]["description"] = _adf(_plain(descricao))
    def verify(data):
        key = data.get("key")
        if not isinstance(key, str) or ISSUE.fullmatch(key) is None: return False
        f = _issue(jira, key)["fields"]
        return f.get("summary") == summary and f.get("issuetype", {}).get("id") == matches[0]["id"]
    return await _write(ctx, jira, kind="issue_create", label=f"Criar {typ}: {summary}",
        method="POST", endpoint="/rest/api/3/issue", payload=payload,
        snapshot={"project_id": project["id"], "type_id": matches[0]["id"]},
        fresh=lambda: {"project_id": jira.get("/rest/api/3/project/SCRUM")["id"], "type_id": matches[0]["id"]},
        verify=verify)


@mcp.tool()
async def jiraia_editar_issue(chave: str, ctx: Context, resumo: str = "", descricao: str = "", pontos: float = -1) -> dict:
    """Editar resumo, descricao e/ou story points de issue SCRUM."""
    jira = _client(); key = _issue_key(chave); before = _issue(jira, key)
    fields = {}
    if resumo: fields["summary"] = _plain(resumo, 240)
    if descricao: fields["description"] = _adf(_plain(descricao))
    if pontos != -1:
        if type(pontos) not in (float, int) or not 0 <= pontos <= 1000: raise ValueError("Pontos invalidos")
        fields["customfield_10016"] = pontos
    if not fields: raise ValueError("Nenhuma alteracao informada")
    def verify(_):
        after = _issue(jira, key)["fields"]
        return all((_adf_text(after.get(k)) == _adf_text(v) if k == "description" else after.get(k) == v)
                   for k, v in fields.items())
    return await _write(ctx, jira, kind="issue_edit", label=f"Editar {key}",
        method="PUT", endpoint=f"/rest/api/3/issue/{key}", payload={"fields": fields},
        snapshot=before.get("fields", {}).get("updated"),
        fresh=lambda: _issue(jira, key)["fields"].get("updated"), verify=verify)


@mcp.tool()
async def jiraia_definir_prioridade(chave: str, prioridade: str, ctx: Context) -> dict:
    """Definir prioridade existente do Jira para issue SCRUM."""
    jira = _client(); key = _issue_key(chave); before = _issue(jira, key)
    name = _plain(prioridade, 80)
    priorities = jira.get("/rest/api/3/priority")
    matches = [x for x in priorities if x.get("name", "").casefold() == name.casefold()]
    if len(matches) != 1:
        return {"status": "PRIORIDADE_NAO_ENCONTRADA", "opcoes": [x.get("name") for x in priorities]}
    wanted = matches[0]["id"]
    return await _write(ctx, jira, kind="issue_priority", label=f"Prioridade de {key}: {name}",
        method="PUT", endpoint=f"/rest/api/3/issue/{key}",
        payload={"fields": {"priority": {"id": wanted}}},
        snapshot=before["fields"].get("updated"),
        fresh=lambda: _issue(jira, key)["fields"].get("updated"),
        verify=lambda _: (_issue(jira, key)["fields"].get("priority") or {}).get("id") == wanted)


@mcp.tool()
async def jiraia_atribuir_issue(chave: str, account_id: str, ctx: Context) -> dict:
    """Atribuir issue SCRUM por accountId real, ou NENHUM para desatribuir."""
    jira = _client(); key = _issue_key(chave); before = _issue(jira, key)
    if type(account_id) is not str or not 1 <= len(account_id) <= 160:
        raise ValueError("account_id invalido")
    target = None if account_id.upper() == "NENHUM" else account_id
    if target is not None:
        people = jira.get("/rest/api/3/user/assignable/search?" + urlencode({"project": "SCRUM", "query": target, "maxResults": 100}))
        if not any(u.get("accountId") == target and u.get("active") is not False for u in people):
            return {"status": "USUARIO_NAO_CONFIRMADO_COMO_ATRIBUIVEL"}
    payload = {"fields": {"assignee": {"accountId": target} if target is not None else None}}
    return await _write(ctx, jira, kind="issue_assign", label=f"Atribuir {key} para {target or 'nenhum responsavel'}",
        method="PUT", endpoint=f"/rest/api/3/issue/{key}", payload=payload,
        snapshot=before["fields"].get("updated"),
        fresh=lambda: _issue(jira, key)["fields"].get("updated"),
        verify=lambda _: (_issue(jira, key)["fields"].get("assignee") or {}).get("accountId") == target)


@mcp.tool()
async def jiraia_transicionar_issue(chave: str, destino: str, ctx: Context) -> dict:
    """Mudar status de issue SCRUM usando uma transicao permitida pelo Jira."""
    jira = _client(); key = _issue_key(chave); before = _issue(jira, key)
    name = _plain(destino, 80)
    def options(): return jira.get(f"/rest/api/3/issue/{key}/transitions").get("transitions", [])
    available = options()
    matches = [x for x in available if x.get("name", "").casefold() == name.casefold() or x.get("to", {}).get("name", "").casefold() == name.casefold()]
    if len(matches) != 1: return {"status": "TRANSICAO_INDISPONIVEL", "opcoes": [x.get("name") for x in available]}
    transition = matches[0]
    return await _write(ctx, jira, kind="issue_transition", label=f"Mover {key}: {before['fields']['status']['name']} -> {transition['to']['name']}",
        method="POST", endpoint=f"/rest/api/3/issue/{key}/transitions", payload={"transition": {"id": transition["id"]}},
        snapshot={"updated": before["fields"].get("updated"), "id": transition["id"]},
        fresh=lambda: {"updated": _issue(jira, key)["fields"].get("updated"),
                      "id": next((x["id"] for x in options() if x.get("id") == transition["id"]), None)},
        verify=lambda _: _issue(jira, key)["fields"]["status"]["id"] == transition["to"]["id"])


@mcp.tool()
async def jiraia_alocar_issues(sprint_id: int, chaves: list[str], ctx: Context) -> dict:
    """Alocar ate 20 issues SCRUM numa sprint FUTURA do board 1, com uma confirmacao."""
    jira = _client(); target = _sprint(jira, sprint_id, future=True)
    if type(chaves) is not list or not 1 <= len(chaves) <= 20: raise ValueError("Quantidade de issues invalida")
    keys = [_issue_key(x) for x in chaves]
    if len(set(keys)) != len(keys): raise ValueError("Issues duplicadas")
    snapshots = [_issue(jira, k)["fields"].get("updated") for k in keys]
    def verify(_):
        seen = set(); start = 0
        for _page in range(50):
            data = jira.get(f"/rest/agile/1.0/sprint/{sprint_id}/issue?startAt={start}&maxResults=100")
            found = data.get("issues", [])
            seen.update(x.get("key") for x in found)
            if set(keys) <= seen: return True
            if data.get("isLast") is True or len(found) < 100: return False
            start += len(found)
        return False
    return await _write(ctx, jira, kind="issue_move_sprint", label=f"Alocar {', '.join(keys)} na sprint '{target['name']}' ({sprint_id})",
        method="POST", endpoint=f"/rest/agile/1.0/sprint/{sprint_id}/issue", payload={"issues": keys},
        snapshot={"state": target["state"], "sprint": target["name"], "updated": snapshots},
        fresh=lambda: {"state": _sprint(jira, sprint_id, True)["state"], "sprint": _sprint(jira, sprint_id, True)["name"],
                       "updated": [_issue(jira, k)["fields"].get("updated") for k in keys]}, verify=verify)


@mcp.tool()
async def jiraia_comentar_issue(chave: str, texto: str, ctx: Context) -> dict:
    """Adicionar comentario a uma issue SCRUM; uma confirmacao humana."""
    jira = _client(); key = _issue_key(chave); _issue(jira, key)
    content = _plain(texto, 3000)
    payload = {"body": _adf(content)}
    return await _write(ctx, jira, kind="issue_comment", label=f"Comentar em {key}: {content}",
        method="POST", endpoint=f"/rest/api/3/issue/{key}/comment", payload=payload,
        snapshot={"key": key}, fresh=lambda: {"key": _issue(jira, key)["key"]},
        verify=lambda data: type(data.get("id")) is str and
            _adf_text(jira.get(f"/rest/api/3/issue/{key}/comment/{data['id']}").get("body")) == content)


@mcp.tool()
async def jiraia_atualizar_sprint(sprint_id: int, ctx: Context, goal: str = "", nome: str = "", inicio: str = "", fim: str = "") -> dict:
    """Atualizar goal ou nome de sprint futura SCRUM no board 1."""
    jira = _client(); before = _sprint(jira, sprint_id, future=True)
    payload = {}
    if goal: payload["goal"] = _plain(goal, 500)
    if nome: payload["name"] = _plain(nome, 80)
    if inicio or fim:
        if not inicio or not fim: raise ValueError("Informe inicio e fim juntos")
        try:
            start = datetime.fromisoformat(inicio.replace("Z", "+00:00"))
            end = datetime.fromisoformat(fim.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Datas devem estar em ISO 8601 com fuso") from None
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("Datas invalidas ou sem fuso horario")
        payload.update({"startDate": start.isoformat(), "endDate": end.isoformat()})
    if not payload: raise ValueError("Nenhuma alteracao informada")
    def verify(_):
        after = _sprint(jira, sprint_id)
        for k, v in payload.items():
            if k in ("startDate", "endDate"):
                try:
                    a = datetime.fromisoformat(after[k].replace("Z", "+00:00"))
                    b = datetime.fromisoformat(v.replace("Z", "+00:00"))
                except (ValueError, TypeError, KeyError, AttributeError):
                    return False
                if a != b: return False
            elif after.get(k) != v:
                return False
        return True
    return await _write(ctx, jira, kind="sprint_update", label=f"Atualizar sprint {before['name']} ({sprint_id})",
        method="POST", endpoint=f"/rest/agile/1.0/sprint/{sprint_id}", payload=payload,
        snapshot=before, fresh=lambda: _sprint(jira, sprint_id, future=True), verify=verify)


if __name__ == "__main__":
    mcp.run(transport="stdio")
