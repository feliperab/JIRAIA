# JIRAIA

**Assistente de gestao agil integrado ao Jira Cloud pelo Kiro CLI V3, utilizando Model Context Protocol (MCP).**

O JIRAIA permite consultar, planejar e executar operacoes no Jira por linguagem natural, utilizando um unico agente chamado `jiraia`.

O usuario nao precisa executar comandos Python, preparar payloads REST ou alternar entre agentes para as tarefas operacionais.

## Estado atual

O projeto possui funcionalidades de leitura e escrita reais no Jira Cloud.

As operacoes de escrita sao limitadas ao escopo autorizado e exigem confirmacao humana pela interface MCP do Kiro.

**Ambiente configurado:**

- Jira Cloud: `https://jiraia.atlassian.net`
- Projeto: `SCRUM`
- Scrum board: `1`
- Interface: Kiro CLI V3
- Linguagem: Python 3.13
- Protocolo: MCP / FastMCP

A disponibilidade efetiva de cada ferramenta depende da configuracao MCP local, das permissoes do agente e das permissoes da conta Jira.

## Funcionalidades

### Daily

A ferramenta `jiraia_daily` consulta a sprint ativa e apresenta:

- Issues em andamento e pendentes.
- Responsaveis.
- Possiveis impedimentos.
- Pontos de atencao.
- Proximas acoes recomendadas.

Somente leitura.

### Sprint Planning

A ferramenta `jiraia_sprint_planning` consulta:

- Sprint atual e sprints futuras.
- Backlog.
- Story Points.
- Candidatos ao planejamento.
- Riscos de capacidade e dependencia.

Somente leitura.

### PI Planning

A ferramenta `jiraia_pi_planning` analisa:

- Horizonte de sprints.
- Sprints existentes e ausentes.
- Backlog disponivel.
- Alocacao de trabalho.
- Riscos e lacunas de planejamento.

Somente leitura.

### Gestao de issues

O servidor `jiraia_ops` disponibiliza operacoes para:

- Buscar issues por filtros JQL.
- Consultar detalhes de uma issue.
- Consultar tipos de issues.
- Buscar usuarios atribuiveis.
- Listar transicoes de status.
- Criar issues.
- Editar resumo, descricao e Story Points.
- Definir prioridade.
- Atribuir ou remover responsaveis.
- Transicionar status.
- Comentar issues.

As escritas exigem confirmacao humana.

### Gestao de sprints

O JIRAIA permite:

- Criar sprints futuras.
- Criar sprint futura e alocar issues em uma unica solicitacao.
- Alocar issues em uma sprint futura.
- Atualizar nome, goal e datas de uma sprint futura.

As ferramentas de escrita do servidor `jiraia_ops` operam no projeto SCRUM e no board 1.

O sistema nao inicia nem exclui sprints automaticamente.

## Um unico agente no Kiro

O agente principal e:

`jiraia`

Sua funcao e receber pedidos em linguagem natural e utilizar a ferramenta MCP apropriada.

Exemplos:

> JIRAIA, faca minha Daily.

> JIRAIA, analise o backlog para a proxima sprint.

> JIRAIA, prepare o PI Planning para cinco sprints.

> JIRAIA, mostre os detalhes da SCRUM-3.

> JIRAIA, crie a Sprint 4 e coloque SCRUM-3 nela.

> JIRAIA, atualize os Story Points da SCRUM-3 para 5.

> JIRAIA, altere o status da SCRUM-3 para Concluido.

As operacoes de escrita so prosseguem mediante aprovacao humana.

A configuracao do agente fica em `.kiro/agents/jiraia.json`.

A lista de ferramentas do agente deve incluir as ferramentas dos servidores MCP utilizados. Confira a lista efetivamente carregada com `/tools`.

## Aprovacao humana

As ferramentas de escrita do servidor `jiraia_ops` utilizam MCP elicitation para apresentar um formulario de confirmacao diretamente ao usuario.

Exemplo de interacao:

```text
Usuario:
JIRAIA, crie a Sprint 4 e coloque SCRUM-3 nela.

JIRAIA:
Alteracoes propostas:

1. Criar sprint futura "Sprint 4" no board 1.
2. Alocar SCRUM-3 na nova sprint.

As operacoes sao sequenciais e nao atomicas.

Autoriza?

Usuario:
SIM

JIRAIA:
Executa as operacoes autorizadas.
Verifica os resultados.
Retorna o status e os registros de auditoria.
```

Respostas aceitas no formulario:

- `SIM`: autoriza.
- `OK`: autoriza.
- `NAO`: cancela.
- `Decline` ou cancelamento do formulario: cancela.

O servidor valida a resposta recebida por MCP. A aprovacao nao deve ser fornecida como argumento de ferramenta gerado pelo modelo.

Consultas de leitura nao precisam de aprovacao de escrita.

O servidor historico `jiraia_write` utiliza outro fluxo, com duas confirmacoes e frases especificas. Para a experiencia simplificada Sim/OK/Nao, utilize as ferramentas de `jiraia_ops`.

## Operacoes compostas

A ferramenta `jiraia_criar_sprint_com_issues` permite solicitar a criacao de uma sprint e a alocacao de ate 20 issues em uma unica interacao.

O fluxo:

1. Consulta e valida o estado atual do Jira.
2. Prepara a proposta.
3. Exibe uma confirmacao humana para o conjunto.
4. Revalida os dados.
5. Cria a sprint futura.
6. Verifica a criacao.
7. Aloca as issues.
8. Verifica a alocacao.
9. Retorna o resultado auditado.

**Importante:** o Jira nao oferece uma transacao atomica para esse conjunto. A sprint pode ser criada mesmo que a alocacao posterior falhe.

Nesses casos, o JIRAIA deve informar sucesso parcial ou estado incerto, sem repetir automaticamente a escrita.

## Resultados de execucao

Principais status retornados pelas ferramentas:

| Status | Significado |
| --- | --- |
| `SUCCESS_VERIFIED` | Resultado confirmado pela verificacao posterior |
| `CANCELADO_SEM_POST` | Usuario nao autorizou a escrita |
| `DADOS_ALTERADOS_SEM_POST` | Dados mudaram antes do envio |
| `OPERACAO_JA_RESERVADA` | Tentativa duplicada bloqueada |
| `UNKNOWN_NEEDS_RECONCILIATION` | Resultado incerto; requer verificacao |
| `PARTIAL_SUCCESS_REVIEW_REQUIRED` | Operacao composta parcialmente concluida |

Um resultado incerto nao autoriza nova tentativa automatica.

A auditoria local fica em `.jiraia/`, incluindo registros das operacoes do servidor `jiraia_ops`.

Esses arquivos nao devem ser versionados.

## Arquitetura MCP

O projeto possui tres servidores principais:

| Servidor | Arquivo | Funcao |
| --- | --- | --- |
| `jiraia_local` | `scripts/mcp_jiraia.py` | Daily, Sprint Planning, PI Planning |
| `jiraia_write` | `scripts/mcp_jiraia_write.py` | Escrita historica controlada, com dupla confirmacao |
| `jiraia_ops` | `scripts/mcp_jiraia_ops.py` | Consultas e escritas com formulario Sim/OK/Nao |

A separacao entre servidores preserva os contratos de seguranca e permite ao agente principal utilizar ferramentas especificas.

### Ferramentas do jiraia_ops

Consultas:

- `jiraia_buscar_issues`
- `jiraia_detalhar_issue`
- `jiraia_listar_transicoes`
- `jiraia_tipos_issue`
- `jiraia_buscar_usuarios`

Escritas:

- `jiraia_criar_sprint`
- `jiraia_criar_sprint_com_issues`
- `jiraia_criar_issue`
- `jiraia_editar_issue`
- `jiraia_definir_prioridade`
- `jiraia_atribuir_issue`
- `jiraia_transicionar_issue`
- `jiraia_alocar_issues`
- `jiraia_comentar_issue`
- `jiraia_atualizar_sprint`

## Instalacao

### Requisitos

- Windows com PowerShell.
- Git.
- Python 3.13.
- Kiro CLI V3.
- Conta Jira Cloud com permissoes apropriadas.

### Clonar

```powershell
git clone https://github.com/feliperab/JIRAIA.git
cd JIRAIA
```

### Preparar Python

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Configurar Jira

Crie `.env` a partir do exemplo:

```powershell
Copy-Item .env.example .env
```

Variaveis:

```text
JIRA_URL=https://jiraia.atlassian.net
JIRA_EMAIL=seu-email@exemplo.com
JIRA_API_TOKEN=seu-token
```

**Nunca versionar `.env` nem compartilhar tokens.**

### Registrar os servidores MCP

Configure os servidores no arquivo local `.kiro/settings/mcp.json`.

Exemplo de estrutura, substituindo `C:/CAMINHO/JIRAIA` pelo caminho real:

```json
{
  "mcpServers": {
    "jiraia_local": {
      "command": "C:/CAMINHO/JIRAIA/.venv/Scripts/python.exe",
      "args": ["C:/CAMINHO/JIRAIA/scripts/mcp_jiraia.py"]
    },
    "jiraia_write": {
      "command": "C:/CAMINHO/JIRAIA/.venv/Scripts/python.exe",
      "args": ["C:/CAMINHO/JIRAIA/scripts/mcp_jiraia_write.py"]
    },
    "jiraia_ops": {
      "command": "C:/CAMINHO/JIRAIA/.venv/Scripts/python.exe",
      "args": ["C:/CAMINHO/JIRAIA/scripts/mcp_jiraia_ops.py"]
    }
  }
}
```

Se o arquivo MCP ja existir, adicione apenas as entradas ausentes. Preserve as configuracoes e credenciais existentes.

O exemplo acima nao substitui automaticamente a allowlist do agente.

Para utilizar todas as funcionalidades em uma unica conversa, inclua as ferramentas de `jiraia_ops` na lista `tools` do agente `jiraia` e mantenha permissoes restritas para escrita.

A configuracao efetivamente carregada no Kiro deve ser conferida com `/tools`. Nao presuma que uma ferramenta esta disponivel apenas porque seu servidor existe no repositorio.

### Iniciar o Kiro

Na raiz do projeto:

```powershell
kiro-cli
```

Dentro do Kiro:

```text
/agent
```

Selecione `jiraia`.

Depois confira:

```text
/mcp
/tools
```

O uso operacional deve ocorrer pela conversa com o agente `jiraia`.

## Seguranca

Principais controles tecnicos:

- Instancia Jira autorizada explicitamente.
- Operacoes limitadas ao projeto SCRUM e ao board 1, conforme a ferramenta.
- Validacao de chaves, parametros e endpoints.
- Confirmacao humana via MCP antes de escritas.
- Revalidacao do estado do Jira.
- Registro persistente antes da tentativa de envio.
- Verificacao posterior das alteracoes.
- Bloqueio de repeticao automatica apos resultado incerto.
- Auditoria local.
- Bloqueio das interfaces legadas de escrita generica.

O metodo generico `JiraClient.post()` permanece bloqueado. As operacoes autorizadas utilizam transportes separados e limitados por tipo.

A CLI historica `--execute` tambem permanece bloqueada.

Os controles reduzem o risco de alteracoes acidentais, mas nao substituem seguranca do sistema operacional, gerenciamento de credenciais e revisao de permissoes.

O Steering em `.kiro/steering/` fornece orientacoes ao agente. Para determinar o comportamento efetivo de escrita, consulte os controles Python e as permissoes MCP, inclusive quando documentos historicos de Steering estiverem desatualizados.

## Testes

Execute:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

Os testes automatizados utilizam mocks para validar os fluxos sem enviar POSTs reais ao Jira.

A execucao de testes nao constitui autorizacao para alteracoes de producao.

A quantidade de testes pode mudar conforme o projeto evolui. Use o resultado da suite executada, nao numeros historicos fixos.

## Estrutura

```text
JIRAIA/
├── .kiro/
│   ├── agents/
│   │   └── jiraia.json
│   └── steering/
├── jiraia/
│   ├── client.py
│   ├── action_engine.py
│   ├── executor.py
│   ├── native_write.py
│   ├── attempt_ledger.py
│   └── execution_cli.py
├── scripts/
│   ├── mcp_jiraia.py
│   ├── mcp_jiraia_write.py
│   └── mcp_jiraia_ops.py
├── tests/
├── .env.example
├── requirements.txt
└── README.md
```

A arvore destaca os componentes principais.

## Validacao em Jira real

Em 27 de outubro de 2026, o projeto realizou e verificou operacoes reais no board 1:

- Criacao da `SCRUM Sprint 3`, ID 4.
- Criacao da `Sprint 4`, ID 5.
- Alocacao da `SCRUM-3` na sprint ID 5.
- Consulta posterior confirmando a alocacao e o status da issue.

Esses resultados pertencem ao ambiente de desenvolvimento configurado e nao implicam que outros ambientes estejam previamente preparados.

## Licenca

Consulte o arquivo `LICENSE`, caso exista. Na ausencia de licenca explicita, nao presuma direitos de redistribuicao.
