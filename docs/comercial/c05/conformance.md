# Conformidade da saída contra os padrões estabelecidos

**Pergunta respondida:** a análise que o MODELA PRO emite hoje seria aceita **sem
ressalvas** pelos padrões que as instituições destinatárias publicaram?

**Resposta: não.** Dos 40 requisitos de saída conferidos, o produto entrega 12.

| estado | itens | o que significa |
|---|---|---|
| emitido | 12 | o produto entrega hoje, verificado em execução |
| parcial | 15 | entrega algo próximo, **não** o exigido — conta como falha |
| ausente | 11 | não entrega |
| humano | 2 | conteúdo do profissional, com porta de entrada existente |

Apuração em 2026-09-12, por leitura do código **e execução do pipeline real de produção**
(`backend.worker.compose_valuation_job`). Reexecutável:

```python
from modules.qualification_profile import product_conformance_baseline, resolve_profile
product_conformance_baseline(resolve_profile({'id': 'bb-meci-avaliacao-imovel-pf'}))
# -> product_can_meet_standard: False
```

## O achado estrutural, e o de maior alavancagem

A revisão cética derrubou vários itens que o levantamento inicial dera por emitidos, por um
motivo único e corrigível: o levantamento validou contra um **render de fixture de teste**,
que injeta campos que o caminho de produção nunca preenche. Rodando o produto de verdade,
o template do laudo mostrou-se com **seções que são código morto em produção** — existem,
passam nos testes, e não saem no PDF do usuário porque `build_report_context`
(`backend/worker.py`) não passa as chaves que o template consome.

Isso é boa notícia operacional: parte das lacunas não é cálculo faltando, é **fiação**. O
valor já existe; não chega ao laudo. Itens nesse caso: atributos do avaliando (`3.3.1.e`),
p-valores por variável (`3.3.1.c`), campo de arbítrio e admissíveis (`3.3.1.f`), F calculado
(`3.3.1.m1`), contagem de outliers (`3.3.1.m2`).

Corolário desconfortável, e que vale registrar: **a suíte verde não provava o laudo**. Os
testes de laudo montavam o contexto à mão, de modo que o caminho de produção nunca era
exercido nessas seções.

## Lacunas por frente dona

| frente | lacunas | natureza predominante |
|---|---|---|
| C02 (fluxo) | 11 | fiação: levar ao snapshot/contexto o que já é calculado |
| C03 (laudo) | 8 | apresentação: campos, seções e anexos do laudo |
| C01 (cálculo) | 5 | cálculo inexistente: R, cotejo 68/90/95, matriz de correlações, elasticidades |
| C04 (produto) | 2 | empacotamento: exportação Excel e assinatura ICP-Brasil |

C05 não possui nenhum desses arquivos. Cada lacuna carrega `gap` e `owner` no perfil, e o
catálogo **recusa** lacuna sem descrição (não auditável) ou sem dono (não endereçável).

## Matriz completa

### ABNT NBR 14653-2:2011, item 10.1

| req | estado | requisito | lacuna | dono |
|---|---|---|---|---|
| `10.1.a` | humano | identificação do solicitante | — | — |
| `10.1.b` | humano | finalidade do laudo, quando informada pelo solicitante | — | — |
| `10.1.c` | parcial | objetivo da avaliação | Falta campo próprio de objetivo (valor de mercado de compra e venda, valor de locação, valor patrimonial etc.) distinto da finalidade, e a seção correspondente. Deveria entrar em f… | C03 |
| `10.1.d` | parcial | pressupostos, ressalvas e fatores limitantes (7.2 da Parte 1) | Falta porta de entrada e seção para os pressupostos/ressalvas/fatores limitantes do avaliador (situação-paradigma sem vistoria, documentação não exibida, restrição de escopo). Deve… | C03 |
| `10.1.e` | parcial | identificação e caracterização do imóvel avaliando (7.3 da Parte 1, no que couber) | A seção report.html:616-626 é código morto no fluxo real. Falta (1) `"subject"` em build_report_context (worker.py:473-499); (2) identificação registral/endereço/descrição física d… | C03 |
| `10.1.f` | ausente | diagnóstico do mercado (7.7.2 da Parte 1) | Nem calculado nem declarável. Deveria entrar como (a) texto livre em forms.py:1462-1495 e (b) seção própria em templates/report.html antes de :628; adicionalmente `market_summary` … | C03 |
| `10.1.g` | **emitido** | indicação do(s) método(s) e procedimento(s) utilizado(s) (Seção 8 da Parte 1) | — | C03 |
| `10.1.h` | **emitido** | especificação da avaliação: grau de fundamentação e de precisão atingidos; demonstrativo da pontuação quando solicitado pelo contr… | — | C03 |
| `10.1.i` | parcial | planilha dos dados utilizados | A planilha entrega os DADOS integralmente, mas nunca a procedência por elemento: as colunas Fonte e Justificativa são estruturalmente mortas no fluxo real (nenhum produtor escreve … | C02 |
| `10.1.j` | parcial | método comparativo: descrição das variáveis do modelo, com o critério de enquadramento de cada característica dos elementos amostr… | Faltam as duas metades específicas: (1) o critério de enquadramento de cada característica dos elementos amostrais (como 'padrao' baixo/medio/alto foi classificado e codificado) e … | C03 |
| `10.1.k` | parcial | tratamento dos dados e identificação do resultado: cálculos efetuados, campo de arbítrio se for o caso, justificativas do resultad… | Três faltas distintas: (1) CAMPO DE ARBÍTRIO calculado e nunca apresentado — corrigir em backend/worker.py:1589-1652 `_map_validation` / worker.py:633-665, propagando `intervals.ar… | C02 |
| `10.1.l` | **emitido** | resultado da avaliação e sua data de referência | — | — |
| `10.1.m` | ausente | qualificação legal completa e assinatura do(s) profissional(is) responsável(is) | Sem porta de entrada — por isso MISSING e não HUMAN. Deveriam entrar nome, registro profissional (CREA/CAU), número de ART/RRT e bloco de assinatura em frontend/components/forms.py… | C03 |

### ABNT NBR 14653-2:2011, item 9.2.1.1 b)

| req | estado | requisito | lacuna | dono |
|---|---|---|---|---|
| `abnt.9.2.1.1.elasticidades` | ausente | Para o Grau III, analisar as ELASTICIDADES em torno do ponto de estimação (NBR 14653-2, 9.2.1.1). | Nada e calculado nem apresentado, e o laudo declara expressamente que NAO faz essa analise. NAO e HUMAN: profiles/normative/abnt-14653-2-regressao-mercado.json e modules/normative_… | C01 |

### GUIAR 2024/00940(7421), item 3.4.7

| req | estado | requisito | lacuna | dono |
|---|---|---|---|---|
| `bb.guiar.assinatura_icp` | ausente | Via de assinatura digital do PDF por certificado ICP-Brasil | SUSTENTADO COMO MISSING, e reconfirmei as duas camadas com grep próprio. (1) NENHUMA integração criptográfica: grep case-insensitive por pyhanko\|endesive\|pades\|pkcs11\|asn1crypt… | C04 |

### MECI-202400940-VER01, item 3.1.7.2

| req | estado | requisito | lacuna | dono |
|---|---|---|---|---|
| `meci.3.1.7.2.anexo` | **emitido** | Memória de cálculo entregue como anexo do laudo — arquivo separado ou seção identificada, entregável em conjunto | — | C03 |

### MECI-202400940-VER01, item 3.2.2

| req | estado | requisito | lacuna | dono |
|---|---|---|---|---|
| `meci.3.2.2.mcddm` | **emitido** | O método padrão do produto é o comparativo direto de dados de mercado com tratamento por regressão linear (MECI 3.2.2). | — | C03 |

### MECI-202400940-VER01, item 3.3.1

| req | estado | requisito | lacuna | dono |
|---|---|---|---|---|
| `meci.3.3.1.a` | parcial | Equação utilizada com a variável dependente apresentada no laudo na forma NÃO TRANSFORMADA | Sustentado. O laudo imprime a equação apenas na escala de ajuste. modules/report_presenter/formula.py:80-86 (_lhs) devolve 'ln(col)' quando o alvo é log e 'transform(col)' para qua… | C03 |
| `meci.3.3.1.b` | parcial | Coeficientes atingidos: correlação (R), determinação (R²) e determinação ajustado (R² ajustado) | Sustentado. R² e R² ajustado saem no laudo de produção; o coeficiente de correlação R não existe em camada alguma. modules/results.py:47 tem r2_adjusted e não há campo de correlaçã… | C01 |
| `meci.3.3.1.c` | parcial | Significâncias do modelo e das variáveis independentes | REBAIXADO de EMITTED. A significância do MODELO sai (p-valor do teste F). A significância DAS VARIÁVEIS INDEPENDENTES não sai no laudo de produção: a coluna p-valor da tabela de co… | C02 |
| `meci.3.3.1.d` | **emitido** | Número de dados utilizados | — | — |
| `meci.3.3.1.e` | ausente | Atributos do imóvel avaliando (valores) | REBAIXADO de PARTIAL. Na execução real de produção a tabela 'Imóvel avaliando' não aparece no laudo — nem o cabeçalho da seção existe no HTML (`grep -n 'Imóvel avaliando' prod.html… | C02 |
| `meci.3.3.1.f` | parcial | Resultado da avaliação e intervalos atingidos (IC 80% E campo de arbítrio) | REBAIXADO de EMITTED — e é exatamente a confusão que se pedia evitar (IC no lugar de campo de arbítrio). Saem no laudo de produção: estimativa pontual, IC 80% da média e intervalo … | C02 |
| `meci.3.3.1.g` | **emitido** | Gráfico de resíduos | — | — |
| `meci.3.3.1.h` | **emitido** | Gráfico de aderência (observados versus estimados) | — | — |
| `meci.3.3.1.i` | **emitido** | Demonstrativo da pontuação atingida (tabela de fundamentação e precisão) | — | — |
| `meci.3.3.1.j` | parcial | Histograma dos resíduos amostrais PADRONIZADOS | Sustentado. O histograma emitido é de resíduos BRUTOS. modules/results_generator.py:1202-1208: sns.histplot(resid_arr, kde=True) com xlabel = axis_resid ('Resíduos') e título 'Hist… | C01 |
| `meci.3.3.1.k` | ausente | Probabilidades da distribuição normal padrão nos intervalos [-1;+1], [-1,64;+1,64] e [-1,96;+1,96] (68%, 90%, 95%) cotejadas com a… | Sustentado, com prova de execução. O produto não calcula nem apresenta o cotejo de frequências. A única aferição de normalidade é um p-valor (Shapiro-Wilk em modules/model_builder.… | C01 |
| `meci.3.3.1.l` | ausente | Matriz de correlações das variáveis independentes e dependente | Sustentado. Não existe matriz de correlações disponível para apresentar. O único corr() é intermediário e descartado: modules/variable_schema.py:951 'corr = sub.corr().abs()' — val… | C01 |
| `meci.3.3.1.m1` | parcial | Valor do teste F de Snedecor (F calculado) | REBAIXADO de EMITTED. O F calculado existe em memória mas NÃO chega ao laudo: o laudo de produção imprime 'Estatística F (p-valor) — (0.0000)', isto é, o p-valor sai e o VALOR de F… | C02 |
| `meci.3.3.1.m2` | ausente | Quantidade de outliers do modelo | Sustentado. A detecção existe (modules/model_builder.py, detect_outliers por Cook/resíduos studentizados; ModelResult.outliers_removed em modules/results.py:66) mas a contagem nunc… | C02 |
| `meci.3.3.1.n` | ausente | Intervalos de valores admissíveis, quando for o caso, informados no campo "Observações" do laudo | REBAIXADO de PARTIAL. Nem o conteúdo nem o campo existem no laudo de produção. (1) O intervalo de valores admissíveis é calculado em modules/normative_rules.py:817-822 (interseção … | C02 |

### MECI-202400940-VER01, item 3.4.1

| req | estado | requisito | lacuna | dono |
|---|---|---|---|---|
| `meci.3.4.1.grau_ii` | **emitido** | Permitir DEFINIR o Grau de Fundamentação II como alvo e REPORTAR o grau atingido no laudo (MECI 3.4.1). | — | C03 |
| `meci.3.4.1.justificativa_grau_i` | ausente | Havendo Grau I, existir campo para a JUSTIFICATIVA exigida pelo MECI 3.4.1 ('Grau I admitido somente com justificativa'). | Nao existe porta de entrada para a justificativa de adocao do Grau I e nada disso chega ao laudo. Onde deveria entrar: na RequestSpec ao lado de search_policy.minimum_fundamentacao… | C02 |

### MECI-202400940-VER01, itens 2.3.3.2 e 3.1.7.2 II

| req | estado | requisito | lacuna | dono |
|---|---|---|---|---|
| `meci.2.3.3.2.excel` | parcial | A amostra exportada em arquivo formato Excel (.xlsx/.xls) | CORREÇÃO DE CAMADA (o levantamento anterior marcou layer='present_in_report'): não existe NADA em Excel em camada alguma — nem calculado, nem apresentado. Portanto layer='absent'. … | C04 |
| `meci.2.3.3.2.pdf` | **emitido** | Relatório completo da inferência estatística em formato PDF, com gráficos (não só texto) | — | C03 |
| `meci.2.3.3.2.projecoes` | parcial | O PDF contém "projeções" e "informações auxiliares" exigidas pela norma de avaliações | REBAIXADO DE EMITTED PARA PARTIAL. O levantamento anterior provou PRESENÇA DE RÓTULO, não presença de VALOR, e provou-a contra uma FIXTURE DE TESTE, não contra o pipeline de produç… | C02 |

### Normas para elaboração de laudos (Edital 2023/01269), item 12.1.15

| req | estado | requisito | lacuna | dono |
|---|---|---|---|---|
| `normas.12.1.15.graficos` | **emitido** | Gráfico de resíduos E gráfico de preços observados versus estimados chegarem ao laudo (Normas para elaboração de laudos, 12.1.15). | — | C03 |

### Normas para elaboração de laudos (Edital 2023/01269), item 12.1.16.1

| req | estado | requisito | lacuna | dono |
|---|---|---|---|---|
| `normas.12.1.16.tabela_anexa` | parcial | Apresentar em TABELA ANEXA o demonstrativo da pontuação atingida para enquadramento nos graus de fundamentação e precisão (Normas … | (a) A pontuacao POR ITEM e calculada e nao e apresentada: so o total chega ao laudo. Ponto exato da queda: modules/results_generator.py:992-1006, que monta cada entrada de item_sco… | C03 |

### Normas para elaboração de laudos (Edital 2023/01269), itens 12.1.8 e 12.1.9

| req | estado | requisito | lacuna | dono |
|---|---|---|---|---|
| `normas.12.1.8.geolocalizacao` | ausente | Registrar geolocalização do avaliando e de TODOS os elementos amostrais em graus decimais, com endereço completo e fonte por dado … | O produto nao tem conceito de geolocalizacao: nenhum campo de coordenada, nenhuma validacao de par lat/long, nenhuma normalizacao para graus decimais, nenhuma coordenada do avalian… | C02 |

## Lacunas de correção mais barata

Ordenadas por esforço aparente, para quem for priorizar. Não é promessa de prazo:

1. **`R` (correlação)** — `3.3.1.b`. Para MQO com intercepto é a raiz de R², que já existe.
   Falta o campo em `ModelMetrics` e uma linha no laudo.
2. **Contagem de outliers** — `3.3.1.m2`. Já detectados via Cook e resíduos studentizados;
   a contagem nunca é propagada.
3. **F calculado** — `3.3.1.m1`. Calculado; não propagado ao snapshot.
4. **Pontuação por item** — `normas.12.1.16.tabela_anexa`. Os seis itens já são
   classificados individualmente; só o total é impresso. O padrão pede o demonstrativo.
5. **Histograma padronizado** — `3.3.1.j`. Hoje o histograma é de resíduos **brutos**; o
   padrão pede padronizados. É uma divisão pelo desvio-padrão dos resíduos.
6. **Atributos do avaliando** — `3.3.1.e`. A tabela existe no template; basta passar
   `subject_raw` como `ctx['subject']` em `build_report_context`.

As mais custosas, por exigirem cálculo ou integração novos: cotejo de frequências
68/90/95% (`3.3.1.k`), matriz de correlações (`3.3.1.l`), elasticidades
(`abnt.9.2.1.1.elasticidades`), geolocalização (`normas.12.1.8`), exportação Excel
(`2.3.3.2.excel`) e assinatura ICP-Brasil (`bb.guiar.assinatura_icp`).

## Dois itens que merecem atenção fora da lista

- **`10.1.m` — qualificação legal e assinatura do responsável: `missing`.** É item
  obrigatório de **todo** laudo pela ABNT NBR 14653-2, e não existe porta de entrada. Sem
  campo, o profissional não tem como cumprir — por isso `missing` e não `humano`.
- **`10.1.f` — diagnóstico de mercado: `missing`.** Nem é calculado nem tem campo para o
  profissional escrever.

## O que este documento não afirma

- Não afirma que o padrão conferido é o vigente: é `MECI-202400940-VER01`, cuja atualidade
  não foi estabelecida (ver `blockers.md` §2).
- Não afirma nada sobre aceitação pelo Banco do Brasil. Atender ao padrão publicado é o que
  se pode provar; aceitar é ato do banco, e o aceite de cada laudo é feito por engenheiro
  do próprio Banco (Edital 2023/01269, DOCUMENTO 02).
- Não dispensa a revisão do profissional responsável.
- Não vale para a trilha 'Crédito Geral BB', que pede preferencialmente Grau III e tem
  norma própria: a regra de uma linha de crédito não se estende à outra.
