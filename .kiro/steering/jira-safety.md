---
inclusion: always
---

# JIRAIA - Politica obrigatoria de operacoes Jira

Este Steering orienta o Kiro. Os controles tecnicos devem continuar implementados e testados em Python.

## Autorizacao

- Consultas por GET sao permitidas conforme as credenciais disponiveis.
- Nenhuma operacao de escrita pode ocorrer apenas por recomendacao ou iniciativa do Kiro.
- Criar, editar, mover, iniciar ou excluir dados exige aprovacao humana especifica para a operacao exata.
- Nao tratar uma simulacao, frase gerada ou arquivo JSON como prova suficiente de autorizacao.
- Nao contornar os bloqueios da CLI, do executor ou de `JiraClient.post`.

## Estado atual

- O transporte POST de producao esta desabilitado.
- O executor rejeita o cliente Jira real.
- O comando `--execute` permanece bloqueado.
- `allow_write=True` nao autoriza envio HTTP real.
- As ferramentas MCP permanecem somente de leitura.

## Futuras operacoes autorizadas

- Apresentar destino, board, operacao e parametros exatos.
- Exigir aprovacao humana fora do fluxo autonomo do Kiro.
- Revalidar a proposta, a aprovacao e o estado atual do Jira.
- Registrar a tentativa antes de qualquer envio.
- Nao repetir automaticamente uma operacao apos resposta incerta.
- Reconciliar resultados desconhecidos antes de novas propostas.

## Protecao de informacoes

- Nunca imprimir ou versionar tokens, senhas ou cabecalhos de autenticacao.
- Respeitar arquivos ignorados pelo Git.
- Nao realizar push sem solicitacao explicita.
- Nunca afirmar que o Jira foi alterado com base somente em testes ou simulacoes.
