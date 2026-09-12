# C05 — Tabela dos oito aceites

Campanha **MP-COM-20260912/C05**. Branch `mp-com-20260912/c05-normas-perfis`.
BASE_SHA `8d66c7973c659174e06d7223c9a9a8181e8eeabf`.

Estados usados, conforme o contrato comum — e distintos do estado do **PRODUTO**:
`IMPLEMENTED_VERIFIED`, `IMPLEMENTED_PARTIAL`, `WAITING_FOR_COMPONENTS`,
`BLOCKED_EXTERNAL_EVIDENCE`.

## Objetivo reenquadrado (2026-09-12)

O objetivo contratado **não** é ser homologado por instituições, e sim **produzir análises
que seriam aceitas sem ressalvas pelos padrões que elas estabeleceram** — ver
[`objetivo.md`](objetivo.md). Os oito aceites abaixo tratam de *ter a regra e o perfil
verificados*; a pergunta do objetivo é distinta e está respondida em
[`conformance.md`](conformance.md):

> **A análise que o produto emite hoje seria aceita sem ressalvas pelo padrão do Banco do
> Brasil? Não.** Dos 40 requisitos de saída conferidos, o produto entrega 12: 15 parciais,
> 11 ausentes, 2 dependentes do profissional (com porta de entrada existente).

Isso **não** reprova os aceites: levantar a regra corretamente e atendê-la são coisas
diferentes, e a segunda depende de arquivos que C05 não possui. Mas é o número que decide o
objetivo, e por isso vem antes da tabela. As lacunas estão distribuídas em C02 (11,
sobretudo fiação do que já é calculado), C03 (8, apresentação), C01 (5, cálculo inexistente)
e C04 (2, empacotamento).

## Resumo

| # | aceite | estado |
|---|---|---|
| A01 | Fontes autorizadas e vigentes | `IMPLEMENTED_PARTIAL` + `BLOCKED_EXTERNAL_EVIDENCE` (vigência) |
| A02 | Cobertura completa do escopo | `IMPLEMENTED_VERIFIED` |
| A03 | Classificador único e fronteiras | `IMPLEMENTED_VERIFIED` + 1 handoff bloqueante a C01 |
| A04 | Pressupostos e dependência dos dados | `IMPLEMENTED_VERIFIED` |
| A05 | Perfil bancário verificável | `IMPLEMENTED_VERIFIED` (força moderada) |
| A06 | Perfil securitário verificável | **`BLOCKED_EXTERNAL_EVIDENCE`** |
| A07 | Controle profissional e revisão independente | `IMPLEMENTED_PARTIAL` + `BLOCKED_EXTERNAL_EVIDENCE` (parecer externo) |
| A08 | Alegações limitadas por prova | `IMPLEMENTED_VERIFIED` |

Suíte da frente: **604 passed, 1 xfailed** (o xfail estrito é o handoff de A03).

**Consequência declarada, não silenciada.** A correção do default documental (A03) faz
falhar **dois** testes pré-existentes, em arquivos que esta frente **não possui**:

- `tests/test_audit_fixes.py::TestAvaliandoDomainPreFilter::test_full_search_does_not_crash_and_does_not_bottom_rank_on_zero_avaliando` (`grau_fundamentacao is not None`)
- `tests/test_full_flow.py::TestFullFlow::test_end_to_end_logic` (`is_valid is True`)

A causa é a mesma do handoff a C01: a re-validação em `optimal_combination.py` descarta os
itens documentais, o grau fica `None` e `is_valid` fica `False`. Em ambos a asserção é
incidental e dependia do default aprovador. A lista foi levantada por varredura exaustiva
das asserções de grau fora da propriedade desta frente, não por inferência. C05 não editou
os arquivos; a correção de `handoff.md` §2.1 faz os dois passarem sem tocá-los.

## A01 — Fontes autorizadas e vigentes

**`IMPLEMENTED_PARTIAL` + `BLOCKED_EXTERNAL_EVIDENCE`.** Duas perguntas sob um critério,
com respostas opostas; separadas deliberadamente.

- **Conferência dos limiares: atendida.** Os 13 limiares aplicados foram lidos no texto
  das edições em mãos (14653-2:2011, 14653-1:2019), com cláusula, página e SHA-256
  registrados em `THRESHOLD_PROVENANCE` / `SOURCE_DOCUMENTS`. Nenhum vem de README, de
  fonte secundária ou de memória. Reconferível: `verify_sources.py` confirma que cada
  constante aplicada confere com sua proveniência e que o SHA-256 dos exemplares confere.
- **Vigência das edições: bloqueada.** O catálogo ABNT não entrega o registro da norma por
  requisição estática. Permitido: conformidade com as edições **conferidas**. Vedado:
  "a edição vigente".
- **Risco de lavagem de atribuição, tratado:** o MECI do BB enuncia números de sabor
  normativo (IC de 80%, campo de arbítrio, Grau II). No perfil do BB eles estão marcados
  como requisito **contratual do banco**, com `attribution_warning` explícito. Os limiares
  que o produto aplica como normativos vieram do texto da norma.

Evidência: `sources.md`, `tests/comercial/c05/test_a01_fontes_vigentes.py` (67 testes),
`scripts/comercial/referencia/verify_sources.py`.

## A02 — Cobertura completa do escopo

**`IMPLEMENTED_VERIFIED`.** As 33 regras registradas têm **destino explícito**, e
`inventory_audit()` falha se alguma não tiver: 17 `automatic`, 11
`professional_evidenced`, 3 `out_of_announced_offer`, 2 `external_blocked`.

`unverified_rules` foi revisto item a item. Três saíram de "não verificável" para
**implementado** porque a leitura da norma mostrou que eram calculáveis ou especificáveis:
micronumerosidade (Anexo A.2 a), o teto de α do Anexo A.3.1 e o enquadramento do método de
custo (Tabelas 6 e 7). Os que permanecem sem verificação automática carregam motivo e
requisito, e nenhum é decisivo marcado como aprovado — teste prova que nenhum id de
`UNVERIFIED_RULES` aparece em `verified_rule_ids()`.

Fora da oferta anunciada, com razão ligada à oferta e não à conveniência: tratamento por
fatores (Tabelas 3–4), métodos involutivo e evolutivo, e o atalho de amostra homogênea.

Evidência: `test_a02_cobertura_escopo.py`.

## A03 — Classificador único e fronteiras

**`IMPLEMENTED_VERIFIED`**, com um handoff bloqueante em arquivo de outro proprietário.

- Fronteiras conferidas à mão nos dois lados de cada limiar (itens 2/4/5/6, Tabela 2,
  Tabela 5), incluindo os cantos da Tabela 2 em que a pontuação basta mas o item
  obrigatório não.
- Grau pendente **não aciona fallback aprovador**: item ausente ⇒ `grade=None` com
  `pending_items`, e os pontos conhecidos não licenciam grau.
- **Defeito corrigido:** os itens documentais 1 e 3 tinham default de Grau I. Com os itens
  2/4/5/6 em Grau III, os 2 pontos fabricados completavam os 16 da Tabela 2 e produziam
  enquadramento **Grau III sem nenhuma declaração documental e sem proveniência**.
- **Fronteira interpretada, declarada:** o teto do item 4 (a) — `2,0×` o máximo amostral —
  é interpretação do "100%", marcada `literal: false`, com justificativa e leitura
  alternativa (`1,0`) registradas em código.
- **Handoff bloqueante a C01:** `optimal_combination.py` re-executa `validate_model` sem
  os argumentos documentais e **descarta a declaração do chamador**. Fixado por teste que
  registra o comportamento atual, mais um `xfail(strict=True)` que falhará por passar
  quando C01 corrigir — sinalizando a transição em vez de escondê-la.

Evidência: `test_a03_classificador_fronteiras.py`, `handoff.md` §2.1.

## A04 — Pressupostos e dependência dos dados

**`IMPLEMENTED_VERIFIED`.** Cada diagnóstico tem hipótese nula, método, **sentido**,
condição e reação — não apenas p-valor.

- Direção correta: `p ≤ α` rejeita H0 e portanto **viola** o pressuposto. Um p pequeno é
  má notícia, não boa.
- O teto de α do Anexo A.3.1 (10%) é **normativo** e um α acima dele é **recusado**, não
  acomodado.
- Autocorrelação fica pendente sem **pré-ordenamento declarado**, como A.2.1.4 exige: um
  teste na ordem original do arquivo não cumpre a cláusula.
- Micronumerosidade por característica: ausência das contagens é **pendente**, não
  conformidade. E não levanta grau — é pressuposto, não item da Tabela 1.
- **Anexo A.2 g) é vedação, não aviso.** Violada, emite `model_use_prohibited`, bloqueia a
  liberação e **não é superável por revisão nem por assinatura**.
- Exclusão de influenciantes exige justificativa registrada; VIF **não** é limiar
  normativo, e a norma trata correlações > 0,80 como gatilho de exame.

Evidência: `test_a04_pressupostos_dados.py`, `test_defeitos_corrigidos.py`.

## A05 — Perfil bancário verificável

**`IMPLEMENTED_VERIFIED`, força moderada.** Dois perfis, de proveniências independentes.

**Banco do Brasil** (`bb-meci-avaliacao-imovel-pf`, `state: verified`) — fonte primária do
próprio emissor, obtida na origem `bb.com.br`: MECI-202400940-VER01, Normas para
elaboração de laudos e Edital de Credenciamento 2023/01269. Ato estabelecido:
**verificação de laudo**, com credenciamento de pessoa jurídica. Traz método (MCDDM com
regressão linear), formato (memória de cálculo como anexo obrigatório; **"OUTROS
APLICATIVOS" cumprem entregando relatório PDF completo da inferência estatística** — a via
aplicável a este produto), regras (conteúdo estatístico, anexos, geolocalização) e grau
alvo (Grau II, Grau I só com justificativa).

**CAIXA** (`caixa-cr-012-2026-avm-precificacao`, `state: discovery`) — Edital CR 012/2026,
autopublicado pela CAIXA no PNCP. Ato: **contratação de empresa**, escopo **AVM
precificação**, não laudo ("laudo" e "ABNT" ocorrem zero vezes).

**BCB** (`bcb-res-4676-garantia-imobiliaria`) — moldura regulatória, texto consolidado v17
conferido byte a byte; vincula apenas instituições autorizadas.

Conflito registrado sem escolher a saída fácil: o MECI fixa Grau II, enquanto as Normas da
trilha Crédito Geral pedem preferencialmente Grau III. São trilhas distintas e a regra de
uma linha de crédito não se estende à outra.

**Ausência de manual é bloqueador explícito**, como o critério exige: requisitos de laudo
da CAIXA e o Edital BB 2024/00940 estão em `blockers.md` §2 e §3, com material exato,
emissor e rota.

## A06 — Perfil securitário verificável

**`BLOCKED_EXTERNAL_EVIDENCE`. Não atendido.** Declarado como tal em vez de apresentado
como parcial.

Obtido e conferido em fonte primária (PDF do próprio servidor `gov.br/susep`, verbatim em
revisão independente): **Resolução CNSP nº 447/2022** — Art. 19 (LMG do DFI = valor da
avaliação **inicial** do imóvel, indexado), §§1º–2º (índice e periodicidade vêm do
contrato; nenhum índice nomeado), Art. 22 (prêmio incide sobre esse LMG), Art. 30
(indenização = valor necessário à **reposição** ao estado imediatamente anterior ao
sinistro), Art. 18 (LMG do MIP = saldo devedor), Art. 42 (revoga a Res. 205/2009).

**Por que não basta:** o ato é **expressamente silente quanto à base de valor**. Existem um
teto procedimental e uma medida indenizatória de sabor reconstrutivo, **sem a ponte entre
eles** — exatamente a conflação que A06 existe para impedir. Nenhuma condição contratual
de produto comercializado foi obtida, e a Circular SUSEP nº 677/2022 nunca foi recuperada.

O que **não** se fez: converter preço de mercado em custo ou em limite de garantia por
coeficiente. `value_basis_guard` recusa essa conversão, e o perfil da rota de custo está em
`blocked_external_evidence`. Valor de mercado, custo de reprodução, custo de reedição,
valor em risco, LMG e saldo devedor permanecem grandezas distintas.

Evidência: `profiles/institutions/susep-seguro-habitacional-dfi.json`,
`test_a06_bases_de_valor_custo.py`, `blockers.md` §1.

## A07 — Controle profissional e revisão independente

**`IMPLEMENTED_PARTIAL` + `BLOCKED_EXTERNAL_EVIDENCE`.**

Implementado e verificado: requisitos humanos exigem evidência com profissional
identificado, motivo, versão e `result_fingerprint` correspondente — cada omissão
invalida a revisão. Protocolo de duas passagens. Mudança material (dado, parâmetro,
amostra, perfil, regra, modelo, documento **e a amplitude do IC que define a precisão**)
altera o fingerprint, invalida revisão e assinatura dependentes e **preserva o histórico**
em `stale_review_events`, com blocker `review_invalidated_by_material_change`. Assinatura
**não** valida conteúdo técnico: caso com regra decisiva falhada mais assinatura íntegra
permanece `analysis_only`.

Fontes de responsabilidade técnica lidas: Resolução CONFEA nº 1.137/2023 (ART),
Resoluções CAU/BR nº 91/2014 e nº 21/2012 (RRT), norma IBAPE/SP 2011 e a página do serviço
VALIDAR do ITI. **Nenhuma certifica software**; o ITI atesta autoria e integridade da
assinatura, nada sobre o conteúdo técnico do laudo.

**Bloqueado:** parecer de revisor profissional qualificado **independente dos autores** não
existe. Não foi simulado, e não foi atribuído a quem não participou. Pendência
identificada, sem assinatura fabricada de colegiado. **Ressalvas de versão, em todas as fontes deste bloco:** a Res. CONFEA
1.137/2023 está alterada pela Res. 1.160/2025, cujo texto não foi lido (nenhuma alteração
aos arts. 1º–4º foi identificada); e as Resoluções CAU/BR nº 91/2014 (art. 3º) e nº 21/2012
(art. 2º, VI) foram lidas em versões que **carregam alterações posteriores não revisadas**.
A conclusão que nenhuma delas certifica software não depende dessas ressalvas, mas
nenhuma das três pode ser citada como "texto vigente".

Evidência: `test_a07_revisao_profissional.py`.

## A08 — Alegações limitadas por prova

**`IMPLEMENTED_VERIFIED`.** Registro versionado (`c05.claims/1`) com quatro tipos de
alegação de **escopos distintos**: `calculation_verified` (versão do software),
`implements_requirements` (versão + edição), `profile_compatible` (versão + perfil),
`institution_accepted` (instituição + perfil + versão).

O que os testes provam que fica **bloqueado**: alegação sem pré-requisito; alegação cujo
sujeito não nomeia versão, ato ou escopo (inclusive campo presente mas vazio); alegação de
escopo de perfil quando o perfil não está `verified`; e todo substituto vedado —
credenciamento profissional, cadastro de fornecedor, participação em licitação, assinatura
digital ou registro de autoria, certificação do próprio profissional, licença permissiva de
biblioteca, e oráculo gerado pelo mesmo código sob teste. Reaproveitamento de aceite fora
do perfil e da versão concedidos é recusado, e uma verificação sem escopo de destino não
confirma reaproveitamento.

**Alegação permitida hoje**, dado o que foi provado: "implementa os requisitos da Tabela 1,
Tabela 2, Tabela 5, 8.2.1.5 e Anexo A.2/A.3.1 da ABNT NBR 14653-2:2011, com limiares
conferidos contra o texto dessa edição" e "compatível com o perfil documental
`bb-meci-avaliacao-imovel-pf`", esta última condicionada à redação de vigência do §2 de
`blockers.md`.

**Alegação bloqueada:** "aceito/homologado por" qualquer instituição — não há ato real de
nenhum destinatário. E "cálculo verificado" depende de referência numérica independente,
que é escopo de outra frente.

Evidência: `test_a08_alegacoes.py`, `test_defeitos_corrigidos.py`.

## Estado do PRODUTO, distinto do estado desta frente

Esta frente não pode declarar, e não declara:

| estado de entrega | situação |
|---|---|
| **conformidade da saída ao padrão do destinatário** | **não atendida — 12 de 40 requisitos emitidos** ([`conformance.md`](conformance.md)) |
| `NORMATIVE_SCOPE_VERIFICATION` | atendido para o recorte anunciado (imóvel urbano, valor de mercado, comparativo com regressão), com a vigência das edições bloqueada |
| `INSTITUTION_PROFILE_VERIFICATION` | atendido para **um** destinatário (BB), em força moderada; CAIXA em `discovery`; securitário bloqueado |
| `INSTITUTION_ACCEPTANCE` | **inexistente** para todo destinatário |
| `INDEPENDENT_TECHNICAL_REVIEW` | **não realizada** — dependência externa objetiva |
| `TECHNICAL_QUALIFICATION`, `COMMERCIAL_PACKAGE_VERIFICATION`, `REAL_CASE_VALIDATION` | fora do escopo desta frente |
| `COMMERCIAL_RELEASE_READY` | **não** declarável a partir daqui |

O objetivo institucional contratado — trabalhos destinados a **bancos e seguradoras** —
**não** está alcançado, e agora por um motivo medido em vez de genérico:

1. **Padrão bancário levantado, não atendido.** O perfil do BB está verificado em fonte
   primária, mas a saída do produto cumpre 12 dos 40 requisitos desse padrão. Enquanto
   `product_can_meet_standard` for `False`, a alegação "compatível com o perfil documental
   P" está **bloqueada por construção** — o registro de alegações não a emite.
2. **Padrão securitário nem levantado por inteiro.** A base de valor não foi estabelecida
   (o ato regulatório é silente) e nenhuma condição contratual foi obtida.

A diferença em relação à redação anterior é de natureza: "nenhuma instituição homologa
software" era beco sem saída; "faltam 28 requisitos, com dono e descrição em cada um" é
plano de trabalho. A alegação permitida continua mais restrita do que o objetivo
contratado, e isso está registrado em vez de arredondado.
