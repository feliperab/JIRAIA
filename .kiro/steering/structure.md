---
inclusion: always
---

# JIRAIA - Arquitetura e organizacao

## Diretorios

- `jiraia/`: cliente Jira, copilotos e Action Engine.
- `scripts/`: comandos locais e servidor FastMCP.
- `tests/`: testes automatizados.
- `.kiro/steering/`: contexto persistente do Kiro.
- `.kiro/settings/mcp.json`: configuracao MCP privada, ignorada pelo Git.
- `.jiraia/`: propostas, recibos, simulacoes e registros locais, ignorados pelo Git.

## Modulos do Action Engine

- `jiraia/action_engine.py`: propostas e aprovacoes.
- `jiraia/executor.py`: revalidacao de propostas.
- `jiraia/attempt_ledger.py`: reserva persistente de tentativas.
- `jiraia/client.py`: cliente HTTP, incluindo bloqueio de POST real.

## Integracao MCP

O servidor `scripts/mcp_jiraia.py` expoe somente:

- `jiraia_daily`
- `jiraia_sprint_planning`
- `jiraia_pi_planning`

## Servidores MCP operacionais

- `scripts/mcp_jiraia.py`: consultas e planejamento, somente leitura.
- `scripts/mcp_jiraia_ops.py`: operacoes Jira e CRUD de issues.
- `scripts/mcp_jiraia_write.py`: criacao controlada de sprint.
- `jiraia/native_write.py`: caminho nativo de escrita controlada.
- `jiraia/execution_guard.py`: protecoes de execucao.
- `jiraia/attempt_ledger.py`: controle persistente de tentativas.

O servidor de leitura nao deve adquirir permissoes de escrita.

As ferramentas operacionais exigem autorizacao humana,
validacao de estado e rastreabilidade de operacoes.

As 12 ferramentas CRUD de Epicos, Stories e Subtarefas
estao disponiveis. A exclusao real ainda requer homologacao
funcional completa.

Nao introduzir caminhos de escrita que contornem
confirmacao humana, auditoria ou controle de tentativas.
