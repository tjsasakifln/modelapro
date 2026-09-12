> **⚠️ DEFEITOS PROVADOS E ABERTOS NESTE DOCUMENTO.** A verificação
> adversarial provou defeitos aqui que **não** foram corrigidos (remediação
> interrompida por limite de sessão). Não leia este arquivo como verificado.
> Lista exata: `docs/comercial/c06/defeitos_abertos_nos_documentos.md`.

---

# C06-A04 — Matriz de validação em casos reais (protocolo)

**Campanha:** MP-COM-20260912 / C06
**Status do aceite:** `BLOCKED_EXTERNAL_EVIDENCE`
**Status de todas as linhas da matriz:** `STATUS=NOT_RUN`
**Data de emissão do protocolo:** 2026-09-11

> **Este documento não contém resultado nenhum.** Ele define, *antes* de qualquer
> dado existir, quais casos reais serão executados, com que critério de aceitação
> congelado, e quais atos humanos e materiais faltam para que a execução seja
> possível. Nenhuma célula de resultado foi preenchida, estimada ou simulada.

---

## 1. O que este aceite exige e por que ele não pode passar nesta sessão

O aceite C06-A04 pede validação do produto contra **trabalhos de avaliação reais
autorizados**, revisados por **revisor independente**. Nesta sessão:

- não existe base de dados real autorizada no repositório nem fora dele;
- não existe revisor independente contratado, identificado ou consultado;
- não existe autorização do titular dos dados para uso dos laudos/amostras;
- não existe autorização para submeter material a qualquer instituição.

Portanto o aceite está **BLOCKED_EXTERNAL_EVIDENCE**. O entregável desta sessão é
o protocolo congelado e a lista precisa de dependências — não o resultado.

### 1.1 O que NÃO conta como evidência para este aceite

- **Fixtures sintéticas e o oráculo OLS independente**
  (`tests/fixtures/pro_workflow/ols_oracle.py`) verificam a *aritmética* do produto
  contra uma implementação que não importa código de produto. Isso é uma afirmação
  sobre corretude numérica em dados construídos. **Não é** afirmação sobre
  desempenho em mercado real e não pode ser citada como evidência de C06-A04.
- **Simulação por agente / LLM** de um parecer de revisor. Não substitui pessoa
  real (ver §4).
- Qualquer execução em dados reais **sem** autorização documentada do titular.

---

## 2. Regras congeladas do protocolo

**R1 — Piso de dez casos.** Dez casos é o **piso de protocolo deste projeto**,
escolhido por nós. **Não** é suficiência estatística universal, **não** é tamanho
amostral derivado de teoria, e **não** é exigência atribuível à ABNT, à
NBR 14653-2 ou a qualquer outra norma. Nenhum texto normativo foi consultado para
fixar o número dez. É uma decisão de engenharia deste projeto, e assim deve ser
descrita em qualquer material comercial.

**R2 — Seleção por risco e cobertura, não por facilidade.** A matriz inclui
deliberadamente casos difíceis: mercado fino, bem atípico, população misturada,
fonte enviesada, data-base retroativa. Um protocolo em que todos os casos são
fáceis não valida nada.

**Correção de uma afirmação anterior desta regra, que era falsa.** Uma versão
anterior de R2 dizia que "no mínimo três linhas (RC-03, RC-06, RC-09) são casos
em que a expectativa prévia registrada é de *não atingimento* do critério". Isso
confundia **duas coisas diferentes**:

1. a expectativa de que a **avaliação** seja infundamentável (é o que esperamos
   em RC-03, RC-06 e RC-09 — amostra insuficiente, bem sem mercado comparável,
   populações distintas na mesma amostra); e
2. a expectativa de que o **critério congelado de aceitação** seja *não
   atingido*.

Os critérios congelados dessas três linhas são **comportamentais**: aprovam se o
produto *declarar* insuficiência amostral (RC-03), *sinalizar* inadequação do
método comparativo direto (RC-06), e *não fundir* as populações silenciosamente
(RC-09). São exatamente os comportamentos que **esperamos** do produto. Logo a
expectativa prévia, para o critério, é de **atingimento**, não de falha.

**O que a matriz efetivamente garante, dito sem inflação:** tal como congelada,
ela contém **zero** linhas cujo critério congelado se espera ver *não atingido*.
A proteção contra seleção conveniente **não** vem de uma cota de falhas
previstas — vem de **R3** (o critério é fixado antes de a amostra existir e não
pode ser editado depois) e de **R4** (o denominador é imutável; caso reprovado
permanece na conta). Essas duas regras é que impedem escolher o critério depois
de ver o resultado.

Não foram acrescentadas linhas com falha prevista para "consertar" a regra:
prever a falha de um produto que ainda não foi executado em dado real nenhum
seria trocar uma afirmação inflada por outra. Se a execução de RC-03, RC-06 ou
RC-09 revelar que o produto **não** tem o comportamento esperado, isso é
reprovação registrada sob R4, e é essa a informação que o protocolo existe para
produzir.

**R3a — Quem apura o critério.** Cada linha declara se o critério é apurado
pelo **revisor independente** (comparação contra o trabalho humano de referência)
ou se é um **teste do comportamento declarativo do produto** (o produto deve
sinalizar insuficiência, heterogeneidade, viés de fonte etc.). Onde o critério
mistura os dois — caso de RC-01, RC-02 e RC-04 —, a parte numérica de divergência
vs. laudo humano e a adequação do grau de fundamentação declarado são **apuradas
pelo revisor independente**, não aceitas pela autoavaliação do produto. O produto
nunca corrige a própria prova.

Adjudicação por linha: RC-01 revisor independente (com verificação do grau
declarado) · RC-02 revisor independente + comportamento declarativo ·
RC-03 comportamento declarativo · RC-04 revisor independente (estatístico) ·
RC-05 revisor independente (estatístico) · RC-06 comportamento declarativo ·
RC-07 comportamento declarativo · RC-08 comportamento declarativo ·
RC-09 comportamento declarativo · RC-10 verificação objetiva de datas (revisor).

**R3 — Congelamento do critério.** O critério de aceitação de cada linha é fixado
no commit deste documento, **antes** de a amostra existir. Alterar o critério de
uma linha exige **abrir um novo `case id`**, preservando a linha original com seu
resultado. É proibido editar o critério de uma linha já executada.

**R4 — Denominador imutável da taxa de cobertura.** A taxa de aprovação é
`casos aprovados / 10` (ou `/N` se linhas forem *acrescentadas*). Um caso que
falha **permanece no denominador**. É proibido remover, trocar, substituir ou
reclassificar um caso reprovado para melhorar a taxa. Casos podem ser
**acrescentados**; nunca retirados.

**R5 — Rastreabilidade.** Cada execução registra: hash do dataset de entrada,
SHA do código, versão do contrato de resultado, data-hora, e o parecer assinado do
revisor. Execução sem os cinco itens é inválida.

**R6 — Dado pessoal.** Trabalhos reais contêm endereço preciso, identificação de
proprietário e valores de transação. Nenhuma amostra entra na matriz sem (a)
consentimento documentado do titular/contratante **ou** (b) protocolo de
anonimização escrito e aplicado antes da ingestão. Ver §5.

---

## 3. Matriz de casos

Colunas: `case id` · tipologia · localidade · período · dificuldade amostral ·
perfil de destinatário anunciado · o que o torna caso de risco · critério de
aceitação **congelado antes da execução** · resultado (vazio) · status.

| case id | Tipologia | Localidade (classe) | Período | Dificuldade amostral | Destinatário anunciado | Por que é caso de risco | Critério de aceitação CONGELADO (fixado antes da execução) | Resultado | Status |
|---|---|---|---|---|---|---|---|---|---|
| RC-01 | Apartamento padrão, condomínio vertical | Capital, mercado ativo | Janela de 12 meses anteriores à data-base | Alta, n ≥ 40, atributos bem distribuídos | Bancário | Caso-âncora: se falhar aqui, o produto não é utilizável. Risco de falso conforto — não valida nada sozinho. | **Apurado pelo revisor independente** (o grau declarado pelo produto é conferido pelo revisor, não aceito): grau de fundamentação ≥ II confirmado em revisão; amplitude do IC 80% da média ≤ 30% da estimativa central; resíduos sem violação grave declarada; divergência vs. laudo humano de referência ≤ 15% | | NOT_RUN |
| RC-02 | Casa térrea isolada, padrão médio | Cidade média | 12 meses | Média, n entre 20 e 30 | Bancário | n próximo do mínimo prático; risco de superajuste e de IC otimista | Mesmo critério de fundamentação declarado; IC 80% ≤ 40%; **o produto deve rebaixar o grau de fundamentação por si**, sem intervenção manual, se o n não suportar | | NOT_RUN |
| RC-03 | Imóvel rural / gleba | Município rural, mercado fino | 24 meses (janela alargada por escassez) | **Baixa**, n < 15, comparáveis heterogêneos | Bancário | **Espera-se avaliação INFUNDAMENTÁVEL** (não falha do critério — ver R2). Mercado fino, amostra insuficiente, heterogeneidade de área e benfeitorias. Teste real: o produto deve *recusar-se a fundamentar* em vez de entregar número bonito, e é esse comportamento que o critério congelado exige | Critério de aprovação = o produto **declara explicitamente** insuficiência amostral / grau mínimo e não emite estimativa com aparência de fundamentada. Emitir número com fundamentação alta = **reprovação** | | NOT_RUN |
| RC-04 | Sala comercial / conjunto de escritórios | Capital, eixo corporativo | 18 meses | Média, colinearidade forte entre área, andar e vaga | Bancário | Colinearidade entre atributos; risco de coeficiente com sinal invertido e de inferência instável | Diagnóstico de colinearidade emitido e visível no laudo; nenhum coeficiente com sinal contrário à teoria sem justificativa registrada; divergência vs. laudo humano ≤ 20% | | NOT_RUN |
| RC-05 | Galpão logístico | Região metropolitana | 24 meses | Média-baixa, n pequeno, alta dispersão de área | Bancário | Escala de área varia por ordem de grandeza; risco de alavancagem por ponto influente | Pontos influentes identificados e reportados; remoção de qualquer ponto influente único não desloca a estimativa central em mais de 20%; se deslocar, o produto deve sinalizar | | NOT_RUN |
| RC-06 | Imóvel atípico (benfeitoria singular, padrão construtivo fora da vizinhança) | Capital, bairro homogêneo | 18 meses | **Baixa**, sem comparáveis realmente análogos | Bancário | **Espera-se avaliação INFUNDAMENTÁVEL pelo método comparativo direto** (não falha do critério — ver R2). O bem não tem mercado comparável; o critério congelado exige que o produto sinalize essa inadequação | Aprovação = o produto sinaliza inadequação do método comparativo direto para o caso e não apresenta o resultado como fundamentado. Silêncio do sistema = **reprovação** | | NOT_RUN |
| RC-07 | Apartamento em empreendimento novo (lançamento) | Capital | 12 meses | Média, dados majoritariamente de **preço de oferta**, não de transação | Bancário | Fonte censurada/enviesada: oferta ≠ transação. Risco de viés sistemático para cima não declarado | O laudo **explicita** a natureza da fonte (oferta) e o tratamento aplicado ao viés; ausência dessa declaração = reprovação, independentemente do valor obtido | | NOT_RUN |
| RC-08 | Imóvel residencial para fim securitário (base de reconstrução) | Cidade média | 12 meses | Média | **Securitário** | Base de valor diferente: custo de reedificação/reposição ≠ valor de mercado. Risco de o produto entregar valor de mercado rotulado como base securitária | O laudo identifica sem ambiguidade a base de valor produzida; se a base exigida pelo destinatário for reposição/reedificação e o produto só gerar valor de mercado, isso deve ser **declarado como limitação** no laudo. Entrega ambígua = reprovação | | NOT_RUN |
| RC-09 | Uso misto (residencial + comercial na mesma matrícula) | Cidade média | 18 meses | **Baixa**, tipologia heterogênea dentro da mesma amostra | Outro (judicial / particular) | **Espera-se amostra NÃO UNIFICÁVEL** (não falha do critério — ver R2). A amostra mistura populações distintas; segmentação correta é decisão humana, não automática, e o critério congelado exige que o produto não funda as populações em silêncio | Aprovação = o produto detecta ou permite segmentar e **não** funde as populações silenciosamente. Estimativa única sem alerta de heterogeneidade = reprovação | | NOT_RUN |
| RC-10 | Apartamento padrão, **data-base retroativa** (avaliação retrospectiva) | Capital | Janela histórica encerrada há ≥ 24 meses | Média, dados desatualizados em relação à data de execução | Outro (judicial) | Defasagem temporal: risco de o produto usar dados posteriores à data-base ou não tratar atualização temporal | Nenhum comparável com data posterior à data-base entra no modelo; tratamento temporal documentado; violação = reprovação automática, independentemente do valor | | NOT_RUN |

**Verificação automática do estado da matriz.** O `STATUS=NOT_RUN` não é
verificado por contagem global de ocorrências da palavra no arquivo — a
verificação anterior fazia isso (`grep -c NOT_RUN ... -ge 12`, contra uma matriz
de dez linhas), ficando acoplada a menções incidentais na prosa e sem garantir
que *cada linha* traga o status. `scripts/comercial/aceite/verify_c06.py` agora
lê **linha a linha**: para cada linha que começa com `| RC-`, exige que a coluna
de status seja exatamente `NOT_RUN` **e** que a célula de resultado esteja
vazia; exige ainda que o número de linhas `RC-` seja exatamente dez, o número
declarado. Escrever um resultado em qualquer célula faz a conferência falhar.

**Cobertura pretendida por eixo** (para auditoria da seleção): tipologia
(residencial vertical, residencial horizontal, rural, comercial, industrial,
atípico, misto) · porte de mercado (capital, cidade média, rural) · qualidade da
amostra (alta, média, baixa, n < 15) · fonte (transação vs. oferta) ·
temporalidade (corrente vs. retroativa) · destinatário (bancário, securitário,
outro).

---

## 4. Definição de "revisor independente" neste protocolo

Para efeito de C06-A04, **revisor independente** significa, cumulativamente:

1. **Avaliador tecnicamente habilitado** — profissional habilitado para
   responder tecnicamente por avaliação de imóveis no Brasil, com registro
   profissional válido, **sem vínculo** com o desenvolvimento, a especificação, o
   teste ou a comercialização deste software, e sem interesse econômico no
   resultado da validação.
2. **Revisão estatística proporcional ao risco** — para os casos de maior risco
   (RC-03, RC-04, RC-05, RC-06, RC-09), revisão adicional por pessoa com
   competência em inferência estatística aplicada, que examine diagnósticos,
   pressupostos e a coerência entre o grau de fundamentação declarado e a
   amostra efetivamente usada. Para os casos de baixo risco, basta a revisão do
   avaliador.
3. **Registro assinado** — parecer nominal, datado e assinado, indicando
   concordância, concordância parcial ou discordância com o resultado do produto
   em cada caso, e as razões.

**Simulação por agente não substitui pessoa real.** Nenhum parecer produzido por
modelo de linguagem, agente automatizado ou heurística interna conta como revisão
independente neste aceite, ainda que rotulado como tal. Se em algum momento um
parecer simulado for gerado para fins de ensaio interno, ele deve ser marcado
`SIMULADO — NÃO É REVISÃO INDEPENDENTE` e não pode ser contado na matriz.

Também não é revisor independente: integrante da equipe do produto; pessoa
indicada e remunerada pela parte interessada no resultado favorável; ou revisor
que tenha participado da seleção das amostras.

---

## 5. Dependências — o que falta exatamente, e quem fornece

O aceite permanece bloqueado até que **todos** os itens abaixo existam. Cada item
indica o **ato humano** e o **fornecedor responsável**.

### 5.1 Material

| # | Item necessário | Forma aceitável | Quem deve fornecer |
|---|---|---|---|
| M1 | 10 conjuntos de dados amostrais reais, um por linha da matriz | Planilha/CSV com comparáveis, atributos e fonte de cada elemento | Contratante / empresa de avaliação parceira detentora dos trabalhos |
| M2 | 10 laudos humanos de referência correspondentes | PDF ou equivalente, com data-base e método declarados | Mesma origem de M1 |
| M3 | Identificação da data-base e da finalidade declarada de cada trabalho | Registro documental | Contratante |
| M4 | Indicação do destinatário real ou pretendido de cada laudo | Registro documental | Contratante |

### 5.2 Atos humanos e autorizações

| # | Ato necessário | Por que é indispensável | Quem deve praticar o ato |
|---|---|---|---|
| A1 | **Autorização escrita de uso dos dados** (consentimento do titular/contratante) **ou** protocolo de anonimização aprovado | Sem isso as amostras não podem ser ingeridas; há dado pessoal e endereço preciso (R6) | Titular dos dados / contratante, com validação jurídica do responsável pela empresa |
| A2 | **Contratação do revisor independente** (avaliador habilitado, §4.1) | Sem revisor real não existe validação independente | Direção do projeto / contratante |
| A3 | **Contratação da revisão estatística** para os casos de alto risco (§4.2) | Proporcionalidade ao risco declarada no protocolo | Direção do projeto / contratante |
| A4 | **Declaração de independência** assinada pelo(s) revisor(es) | Atesta ausência de vínculo e de interesse econômico | O próprio revisor |
| A5 | **Congelamento formal** desta matriz (commit assinado) antes da primeira execução | Impede ajuste retroativo de critério (R3) | Responsável técnico do projeto |
| A6 | **Pareceres assinados** caso a caso ao final | Constituem a evidência do aceite | Revisor(es) |

### 5.3 O que NÃO é dependência deste aceite

Homologação, certificação ou aprovação por qualquer instituição bancária,
seguradora, órgão regulador ou entidade normalizadora **não** é dependência de
C06-A04 e não deve ser buscada nem alegada aqui. Essa distinção de escopos é
tratada em `institution_profiles.md` (C06-A05).

---

## 6. Conclusão

`C06-A04 = BLOCKED_EXTERNAL_EVIDENCE`.

Faltam: material real autorizado (M1–M4), autorização de dados (A1), revisor
humano independente contratado e declarado (A2–A4, A6) e congelamento formal
(A5). Até lá, todas as dez linhas permanecem `STATUS=NOT_RUN` e nenhuma
afirmação de validação em casos reais pode ser feita em material comercial,
técnico ou de venda.
