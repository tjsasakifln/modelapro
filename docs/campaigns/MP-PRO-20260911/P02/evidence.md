# P02 — evidência local

- **ID:** MP-PRO-20260911/P02
- **Lote:** MP-PRO-20260911
- **BASE_SHA:** `6d54f902b85a5a37bfbf154d39f74cf854ff9b2b`
- **Branch:** `mp-pro-20260911/p02-rotina-interface`
- **PR #17:** aberta/draft, HEAD = BASE_SHA; esta PR usa `mp-20260911/integracao-final` como base de revisão.
- **Classificação local:** `IMPLEMENTED_PARTIAL`

HEAD final desta branch é registrado no comentário da PR após o commit (não dentro do próprio commit).

## O que foi implementado

A interface Streamlit existente foi recortada em quatro etapas de trabalho do avaliador, sem novo framework e sem cópia da API:

1. **Preparação da amostra** — arquivo, locale explícito, prévia da API, mapeamento editável, amostra interpretada, colunas não usadas com razão, unidade e data-base pendentes se vazias.
2. **Imóvel avaliando** — características nas variáveis-base, execução só no botão.
3. **Resultado e revisão** — valor/unidade/data-base, IC da média e intervalo de predição com rótulos distintos, grau solicitado vs atingido, limitações, contagens, `next_actions`.
4. **Projeto salvo** — lista, abertura, nova revisão, lote, artefatos.

O mapeamento fica preso a um token de arquivo+esquema. Outro arquivo não herda silenciosamente o imóvel anterior. Troca de arquivo, sujeito, unidade, data ou política invalida o resultado dependente e avisa que o que está na tela pertence à versão anterior.

## Contratos

Consumidos da BASE_SHA: `POST /preview`, `POST /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/result`, `GET /jobs/{id}/artifacts/{name}`, `GET /projects`, `GET /projects/{id}`, `POST /projects/{id}/revisions`, `POST /projects/{id}/batch`.

Pedido: só `search_policy.minimum_fundamentacao_grade` como chave de grau. Método em `evaluation_policy.method` escolhido entre `none|holdout|group|temporal|kfold`.

## Testes

Comando (duas execuções):

```text
PYTHONPATH=. python3 -m pytest tests/c09_frontend tests/pro_workflow/p02 tests/test_forms_heuristics.py -q --tb=short
```

| Run | Exit | Resultado |
| --- | ---: | --- |
| 1 | 0 | 71 passed (`p02-unit.log`) |
| 2 | 0 | 71 passed (`p02-unit-2.log`) |

AppTest `frontend/app.py` duas vezes: `p02-launch.log`, exit 0. Headings do percurso presentes; sem «R² Ajustado»; sem banner de certificação.

A04 contra stub HTTP das rotas C11 (não mock do cliente): `p02-a04.log`.

## Aceites

| ID | Situação | Nota |
| --- | --- | --- |
| P02-A01 | BLOCKED | `playwright` ausente neste ambiente. Log em `p02-playwright-unavailable.log`. Sem traces fabricados. |
| P02-A02 | IMPLEMENTED_VERIFIED | Corpo POST contém grau canônico e método escolhido; pending ≠ atingido; validação não pedida = não executada. |
| P02-A03 | IMPLEMENTED_VERIFIED | Token de arquivo; invalidação; preview falha descarta interpretação; POST equivalente bloqueado. |
| P02-A04 | IMPLEMENTED_PARTIAL | Recuperação canônica, PDF falho ≠ cálculo, lote válido/não suportado/pendente. Lista completa de revisões: INTEGRATION_PENDING (P01). |
| P02-A05 | IMPLEMENTED_PARTIAL | 1366 e viewport estreito no presenter. `workflow_context` via fixture rotulada; live = INTEGRATION_PENDING (P01). |
| P02-A06 | IMPLEMENTED_VERIFIED | Tabela abaixo. Hipótese de produtividade até piloto. |

## P02-A06 — caminho anterior vs novo (mesmo caso sintético)

Caso: CSV pt-BR com `id;bairro;area;preco`, imóvel com área `73,5` e bairro categoria, unidade e data-base a declarar.

| | Caminho C09 (BASE_SHA) | Caminho P02 |
| --- | --- | --- |
| Passos obrigatórios visíveis | 6 (importar, papéis, avaliando, executar, revisar, salvar) | 4 (preparação, imóvel, resultado, projeto) |
| Campos repetidos observáveis | Identificador de projeto só na barra; papéis por coluna; unidade do alvo à parte; datas em checkboxes | Idem nas datas/unidade (ainda explícitas). Projeto também na etapa 4. Widget keys passam a incluir o token do arquivo. |
| Correções manuais observáveis | Grau mínimo sempre 1–3 (não havia «não solicitar»). Método de validação oculta (`none`). Coluna identificadora podia reaparecer com outro arquivo de mesmas colunas. Sem razão para coluna não usada. | Grau pode ser não solicitado. Método escolhido na preparação. Troca de arquivo zera o mapeamento. Colunas fora do modelo listadas com razão. Resultado antigo fica rotulado como versão anterior. |
| Tempo de robô / cliques | Não medido como tempo ativo humano | Não medido como tempo ativo humano |
| Produtividade | — | **Hipótese** até piloto real: menos retrabalho de mapeamento entre arquivos e menos dúvida sobre grau/método/PDF |

## Handoffs

Ver `delivery.json` (`handoffs`). Resumo:

- **P01** GET `/projects/{id}/revisions` — lista de revisões. Consumidor degrada para a revisão atual de GET `/projects/{id}`.
- **P01** `provenance.workflow_context` — consumidor completo; live INTEGRATION_PENDING.
- **P03** `report_context` para gráficos de resíduos — sem dados, gráfico indisponível.

## Limitações

- Sem Playwright/Chromium aqui; A01 não foi encenado.
- Sem POST `/projects`; o projeto nasce na primeira revisão.
- Sem rota de adoção de modelo; alternativas são leitura.
- Estimativa de custo só aparece se a API a devolver.
- Não se afirma prontidão normativa nem laudo aprovado.

## Capturas

- `p02-unit.txt` / `p02-unit-2.txt` (71 passed, exit 0, duas execuções)
- `p02-launch.txt` (AppTest duas vezes, exit 0)
- `p02-a04.txt`
- `p02-playwright-unavailable.txt`
