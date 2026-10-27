---
inclusion: always
---

# JIRAIA - Tecnologias e desenvolvimento

## Ambiente

- Windows com PowerShell 5.1.
- Python 3.13, utilizando o ambiente virtual `.venv`.
- Testes automatizados com `unittest`.
- Jira Cloud acessado por cliente HTTP Python.
- FastMCP para integrar ferramentas ao Kiro CLI V3.
- Comando de conversacao do projeto: `kiro-cli chat --v3`.

## Convencoes

- Preservar a arquitetura e os modulos existentes.
- Preferir dependencias ja instaladas e a biblioteca padrao.
- Executar `.venv\Scripts\python.exe -m unittest discover -s tests -q` antes de versionar alteracoes.
- Simular respostas HTTP nos testes de escrita.
- Nunca carregar credenciais reais em testes.
- Nunca realizar `git push` sem solicitacao explicita do usuario.

## Seguranca

- Steering orienta o agente, mas nao concede permissoes.
- O servidor MCP deve continuar somente de leitura.
- Uma alteracao no Jira exige autorizacao humana especifica e verificacoes no codigo.
