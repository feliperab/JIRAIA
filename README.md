# JIRAIA

**Copiloto de planejamento e acompanhamento do Jira Cloud integrado ao Kiro CLI V3 por MCP.**

O JIRAIA transforma dados de sprints e backlog em diagnósticos para reuniões de **Daily**, **Sprint Planning** e **PI Planning**. O projeto também inclui um *Action Engine* experimental para gerar propostas, verificar aprovações locais e simular operações com rastreabilidade.

> [!IMPORTANT]
> **O JIRAIA não executa alterações reais no Jira nesta versão.** A interface de execução, o executor com cliente real e o transporte HTTP de escrita permanecem bloqueados. Aprovações locais e simulações não representam autorização para uma escrita de produção.

## Funcionalidades

| Recurso | Objetivo | Comportamento atual |
| --- | --- | --- |
| Daily Copilot | Diagnóstico da sprint ativa | Consulta, sem escrita |
| Sprint Planning | Análise de backlog e sprint futura | Consulta, sem escrita |
| PI Planning | Visão de planejamento entre sprints | Consulta, sem escrita |
| Action Engine | Preparação, integridade e aprovação local de propostas | Preview e simulação |
| Execution CLI | Exibição de propostas e verificações antes de executar | Execução real desabilitada |
| Kiro Steering | Contexto persistente de produto, arquitetura e segurança | Ativo no Kiro CLI V3 |

### Ferramentas MCP

O servidor local `jiraia_local` expõe três ferramentas:

- `jiraia_daily` — consulta a sprint ativa para apoiar a Daily.
- `jiraia_sprint_planning` — consulta backlog e sprint futura para apoiar o Sprint Planning.
- `jiraia_pi_planning` — consulta sprints futuras e backlog para apoiar o PI Planning.

As ferramentas do MCP foram concebidas como operações de **somente leitura**. O Kiro também pode ter ferramentas nativas, como `shell` e `write`; elas possuem permissões próprias e não são automaticamente limitadas pela política do servidor MCP.

## Tecnologias

- Python 3.13 e ambiente virtual `.venv`
- Windows e PowerShell 5.1 no ambiente de desenvolvimento
- Jira Cloud REST API
- Model Context Protocol (MCP) e FastMCP
- Kiro CLI V3 e arquivos de Steering
- `unittest` para testes automatizados

## Instalação

### 1. Pré-requisitos

Instale **Git**, **Python 3.13** e **Kiro CLI**, e tenha acesso ao seu projeto no Jira Cloud com credenciais de leitura apropriadas.

### 2. Clonar o repositório

```powershell
git clone https://github.com/feliperab/JIRAIA.git
cd JIRAIA
```

### 3. Instalar as dependências

No PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Use sempre o Python do ambiente virtual nos comandos abaixo.

### 4. Configurar credenciais do Jira

Copie o exemplo de configuração e preencha os valores **somente no arquivo local**:

```powershell
Copy-Item .env.example .env
notepad .env
```

Configure a URL do seu tenant, seu e-mail e o token de API segundo os nomes e comentários indicados em `.env.example`. **Não cole credenciais em issues, commits, logs ou mensagens.**

O arquivo `.env` e a configuração privada de MCP estão previstos no `.gitignore`. Confira as regras antes de adicionar novos arquivos ao Git.

## Integração com o Kiro CLI V3

O servidor MCP Python está em `scripts/mcp_jiraia.py` e é utilizado pelo Kiro por `stdio`. A configuração fica no arquivo MCP local do Kiro (por exemplo, `.kiro/settings/mcp.json` no projeto, conforme a instalação).

Um exemplo de entrada para **adicionar** ao objeto `mcpServers`, adaptando o caminho à sua máquina:

```json
{
  "jiraia_local": {
    "command": "C:/CAMINHO/JIRAIA/.venv/Scripts/python.exe",
    "args": ["C:/CAMINHO/JIRAIA/scripts/mcp_jiraia.py"]
  }
}
```

> Esse trecho é uma **entrada de `mcpServers`**, não o conteúdo completo do arquivo `mcp.json`. Preserve outros servidores e configurações já existentes. Não versionar arquivos MCP contendo informações privadas.

Abra uma sessão na pasta do projeto:

```powershell
kiro-cli chat --v3
```

Dentro do Kiro:

- `/mcp` — verifique se `jiraia_local` está ativo e disponibiliza as três ferramentas.
- `/tools` — confira as ferramentas e permissões disponíveis na sessão.
- `/context` — confira os arquivos Steering incluídos no contexto.

Exemplos de solicitações:

> Use `jiraia_daily` para resumir a sprint ativa, identificar bloqueios e sugerir a pauta da Daily.

> Use `jiraia_sprint_planning` para analisar o backlog e os pontos de atenção da próxima sprint.

> Use `jiraia_pi_planning` para preparar uma visão de planejamento do PI com base nos dados disponíveis.

As respostas dependem do estado real do Jira, das permissões da conta e das informações presentes no board.

## Steering do Kiro

O contexto persistente fica em `.kiro/steering/`:

| Arquivo | Propósito |
| --- | --- |
| `product.md` | Visão do produto e objetivos do JIRAIA |
| `tech.md` | Tecnologias e convenções de desenvolvimento |
| `structure.md` | Estrutura do projeto e contratos MCP |
| `jira-safety.md` | Política de leitura, escrita e aprovação humana |

O carregamento desses quatro documentos foi validado no Kiro CLI V3. **Steering orienta o agente; não substitui controles técnicos de acesso e autorização.**

## Action Engine e execução segura

Os módulos de `jiraia/` contemplam geração de propostas, verificações de integridade, recibos locais de aprovação, reserva de tentativas e simulação de resultados. Arquivos de trabalho gerados localmente permanecem em `.jiraia/`, que não deve ser enviado ao Git.

Para visualizar uma proposta local existente:

```powershell
.\.venv\Scripts\python.exe -m jiraia.execution_cli
```

Para acrescentar verificações de **leitura** no Jira:

```powershell
.\.venv\Scripts\python.exe -m jiraia.execution_cli --check-jira
```

A execução real **não** é habilitada por `--execute` ou `allow_write=True`. O aplicativo possui bloqueios adicionais no executor e no cliente HTTP para impedir envios acidentais pelo caminho implementado. Não tente contornar essas proteções.

Uma versão futura com escrita exigirá autorização humana específica para a operação, revalidação do estado do Jira, prevenção de duplicidades, registro de tentativas e reconciliação de respostas incertas **antes** de qualquer POST real.

## Testes

Execute a suíte:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

A suíte cobre os copilotos e as validações locais, os contratos MCP e Steering, as simulações e os bloqueios de escrita. Os testes que exercitam transporte POST usam respostas HTTP simuladas; **eles não criam sprints reais no Jira**.

No commit estável `61b901d`, a suíte versionada contém **61 testes**. Existem desenvolvimentos locais posteriores do agente `jiraia-readonly` que ainda não fazem parte dessa versão publicada.

## Estrutura principal

```text
JIRAIA/
├── .kiro/
│   └── steering/
│       ├── product.md
│       ├── tech.md
│       ├── structure.md
│       └── jira-safety.md
├── jiraia/
│   ├── client.py
│   ├── action_engine.py
│   ├── executor.py
│   ├── attempt_ledger.py
│   ├── execution_cli.py
│   └── real_execution.py
├── scripts/
│   └── mcp_jiraia.py
├── tests/
├── .env.example
├── requirements.txt
└── README.md
```

A árvore acima destaca os componentes principais; o projeto contém outros módulos de planejamento, simulação e testes.

## Segurança e limites

- Use contas do Jira com as menores permissões necessárias.
- Nunca versionar `.env`, tokens de API ou arquivos MCP privados.
- Não confunda uma simulação de sucesso com uma operação realizada.
- Não repita automaticamente uma tentativa de escrita cujo resultado seja incerto.
- Revise permissões nativas do Kiro (`shell`, `write`, servidores externos) separadamente das ferramentas MCP.
- Os bloqueios do JIRAIA reduzem operações **acidentais**; não são uma barreira contra código malicioso executado na mesma máquina com acesso a credenciais.

## Situação do projeto

**Versão estável:** consultas ao Jira por Kiro CLI V3, três ferramentas MCP e quatro documentos Steering; Action Engine experimental com escrita real desabilitada.

**Próximo desenvolvimento previsto:** validar um agente Kiro dedicado de somente leitura e suas permissões antes de publicá-lo.

## Licença

Verifique se o repositório possui um arquivo `LICENSE`. Na ausência de licença explícita, não presuma permissão para redistribuição ou uso de código por terceiros.
