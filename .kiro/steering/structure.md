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
- `jiraia/execution_pipeline.py`: simulacao offline do fluxo.
- `jiraia/outcome_simulator.py`: resultados ficticios.
- `jiraia/real_execution.py`: executor com producao bloqueada.
- `jiraia/execution_cli.py`: visualizacao e preflight de leitura.
- `jiraia/client.py`: cliente HTTP, incluindo bloqueio de POST real.

## Integracao MCP

O servidor `scripts/mcp_jiraia.py` expoe somente:

- `jiraia_daily`
- `jiraia_sprint_planning`
- `jiraia_pi_planning`

Nao adicionar ferramentas de escrita ao MCP sem revisao de seguranca e autorizacao humana especifica.
