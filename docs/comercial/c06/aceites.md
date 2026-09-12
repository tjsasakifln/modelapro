# C06 — tabela dos oito aceites

## Composição corrente de 2026-09-12

O estado integrado está em [integration-matrix.md](integration-matrix.md), com os
48 aceites dos produtores/composição mapeados a consumidores e evidências. Abaixo
fica preservado o diagnóstico anterior à integração; afirmações de que C05 não
existe ou produtores não foram commitados estão superadas. As cinco ancestralidades
estão em [composition-20260912.md](composition-20260912.md).

A01: agregação estrita implementada, candidata final ainda precisa passar.
A02/A03: prova numérica/qualificação reais conectadas e testadas, custo em fechamento.
A04/A05: atos/dados reais não fornecidos; pesquisa atual por perfil em
[profile-process-verification-20260912.md](profile-process-verification-20260912.md).
A06/A07: composição em validação e Windows ainda não verificado.
A08: `COMMERCIAL_RELEASE_READY=false`, sem rebaixar a oferta a uso assistido.

## Histórico dos oito aceites antes da composição

Campanha `MP-COM-20260912/C06`. Estado do **produto** e estado da **frente**
são coisas diferentes e estão separados de propósito.

Legenda de estado da frente: `IMPLEMENTED_VERIFIED`, `IMPLEMENTED_PARTIAL`,
`WAITING_FOR_COMPONENTS`, `BLOCKED_EXTERNAL_EVIDENCE`.

| Aceite | Estado da frente | Evidência | O que falta |
|---|---|---|---|
| **A01** aceite realmente bloqueante | `IMPLEMENTED_VERIFIED` | `r20a_gate.md`; matriz de injeções em `test_ci_aggregator.py` (56 testes); guardas estruturais parseando o YAML; run vermelho real 34666595782 | — |
| **A02** prova numérica independente | `IMPLEMENTED_PARTIAL` | NIST StRD 11 conjuntos com tolerâncias pré-registradas; conferência com numpy por C06; propriedades metamórficas | Cobre o núcleo comparativo/OLS anunciado. Custo de reconstrução não tem rota implementada, então não há o que referenciar |
| **A03** prova de norma e de incapacidade | `IMPLEMENTED_PARTIAL` | `handoff_c01_grade_not_met.md` + `verificacao_c01_grade.md` — C01 corrigiu em `1d40285`; reexecutado por C06 em worktree descartável | A incapacidade de aprovar por ausência está provada. A capacidade de aprovar legitimamente não: o grau fica `pending` porque o classificador normativo (C05) ainda não existe. Critério `not_met` fica armado |
| **A04** casos reais e pareceres | `BLOCKED_EXTERNAL_EVIDENCE` | `real_case_matrix.md` — protocolo, critérios congelados, `STATUS=NOT_RUN` | Dados reais autorizados; avaliador qualificado independente do código; revisão estatística. Nenhum existe. Simulação por agente não substitui pessoa |
| **A05** validação institucional por perfil | `BLOCKED_EXTERNAL_EVIDENCE` | `institution_profiles.md` — fontes primárias BCB/SUSEP/CAIXA consultadas e citadas | Ato externo real. Não há programa formal de homologação de *software*; o que existe é aceitação de trabalho. Não foi criado certificado interno com nome de banco |
| **A06** composição única e operação reproduzível | `WAITING_FOR_COMPONENTS` | — | C01, C02, C03 e C05 ainda em `8d66c797` com trabalho não commitado; só C04 tem commit próprio. Nenhum HEAD estabilizado para incorporar |
| **A07** segurança, licenças e provas adversariais | `IMPLEMENTED_PARTIAL` | `reuse.json` (29 dependências, licença com evidência por entrada); `security_supply_chain.md`; 21 detectores de mutação comercial | Sem gate de vulnerabilidade no CI: `pip-audit`/`safety` não disponíveis no ambiente. 8 dos 10 defeitos comerciais não têm guarda do lado do produto |
| **A08** liberação comercial sustentada | `NOT_REACHED` | — | Depende de A03, A04, A05 e A06 |

**`COMMERCIAL_RELEASE_READY`: NÃO.** Quatro aceites com requisito decisivo
pendente. Não há merge, venda nem deploy.

## Estados de entrega separados

| Estado | Valor | Por quê |
|---|---|---|
| `CODIGO_COMPLETO` | parcial | O que C06 possui está implementado; as cinco frentes produtoras estão em curso |
| `TECHNICAL_QUALIFICATION` | parcial | Núcleo comparativo/OLS referenciado contra NIST e propriedades analíticas. Não cobre custo de reconstrução |
| `NORMATIVE_SCOPE_VERIFICATION` | reprovado | Grau pedido destrói o cálculo em vez de classificá-lo (A03) |
| `COMMERCIAL_PACKAGE_VERIFICATION` | parcial | Wheel instala fora do checkout e sobe `/health`; Windows agora bloqueia o portão. Falta instalador com experiência profissional (C04) |
| `INDEPENDENT_TECHNICAL_REVIEW` | não realizado | Nenhum revisor humano externo. Verificação adversarial por agentes não é revisão independente |
| `REAL_CASE_VALIDATION` | não realizado | Nenhum trabalho real autorizado |
| `INSTITUTION_PROFILE_VERIFICATION` | preparado | Requisitos mapeados das fontes; nenhum ato externo |
| `INSTITUTION_ACCEPTANCE` | inexistente | Por destinatário: nenhum |
| `COMMERCIAL_CLAIMS_ALLOWED` | ver abaixo | |

## Alegações comerciais permitidas hoje

Permitido afirmar, com versão e escopo:

- que o núcleo de mínimos quadrados reproduz os valores certificados do NIST
  StRD nos onze conjuntos testados, dentro de tolerâncias fixadas antes do
  ensaio — uma afirmação sobre **aritmética**;
- que o pacote instala fora do checkout, em venv limpo, e sobe o serviço;
- que existe trilha de evidência reproduzível por bundle.

**Não** é permitido afirmar: certificação NIST, conformidade ABNT/NBR
verificada, homologação por banco ou seguradora, aprovação de qualquer
instituição, adequação a finalidade securitária, nem qualquer grau de
fundamentação garantido independentemente da amostra.

A ausência de aprovação de um destinatário não é aprovação implícita nem
proibição universal de vender um produto com alegações mais restritas. Mas o
objetivo institucional contratado — trabalhos destinados a bancos e
seguradoras — **não** está alcançado, e não deve ser declarado como tal.
