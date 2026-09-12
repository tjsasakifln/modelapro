# C05 — Handoff retomável e pedidos de alteração a outros proprietários

Campanha: **MP-COM-20260912/C05**. Branch: `mp-com-20260912/c05-normas-perfis`.
BASE_SHA: `8d66c7973c659174e06d7223c9a9a8181e8eeabf` (composição SEALED vigente da PR #20).
PR incremental contra `mp-pro-20260911/p04-referencia-consolidacao`.

O SHA do candidato é publicado **em comentário após o push**, nunca gravado dentro do
próprio commit.

## 1. O que esta frente entregou nos arquivos que possui

| arquivo | o que mudou |
|---|---|
| `modules/normative_rules.py` | proveniência de todo limiar (`SOURCE_DOCUMENTS`, `THRESHOLD_PROVENANCE`, `CROSS_EDITION_NOTES`); micronumerosidade Anexo A.2 a); pressupostos A.2 c)–i) + A.8 com α do A.3.1; Tabelas 6/7 do método de custo; bases de valor com guard; itens 10.1 do laudo completo; inventário de regras com **destino explícito** por regra |
| `modules/nbr14653_validation.py` | itens documentais 1 e 3 deixam de ter default aprovador; micronumerosidade e pressupostos passam a integrar `assess_normative`; `rule_sources` carrega o destino |
| `modules/qualification_profile/` | novo: contrato `MP-QUAL/1` — `assess_qualification(context, profile)`, catálogo de perfis, `RuleResult`, fluxo de liberação do caso, registro versionado de alegações |
| `profiles/normative/` | perfil do núcleo da oferta (verificado) e perfil da rota de custo (bloqueado por insumo externo) |
| `profiles/institutions/` | perfis de destinatário com o **ato** que cada fonte estabelece |
| `scripts/comercial/referencia/verify_sources.py` | reconferência reexecutável limiar↔proveniência e integridade SHA-256 das fontes |
| `tests/comercial/c05/`, `tests/c03_normative/`, `tests/test_nbr14653.py` | suíte de aceite dos oito critérios |

## 2. Pedidos de alteração — arquivos de outros proprietários

Conforme o contrato comum, C05 **não escreve** nestes arquivos. Cada pedido traz payload
mínimo, evidência e teste. O proprietário implementa.

### 2.1 → C01 — `modules/optimal_combination.py` (BLOQUEANTE, defeito de produção)

**Defeito.** `find_best_model` aceita `grau_item1`/`grau_item3` e os encaminha à validação
por especificação, mas em seguida o módulo **re-executa** `NBRValidator.validate_model`
sobre o modelo vencedor **sem passar os argumentos documentais**, sobrescrevendo a
avaliação correta. A declaração do chamador é silenciosamente perdida.

**Localização.** `modules/optimal_combination.py`, chamada a
`NBRValidator.validate_model(best_model, X_design, y_design, degree)` (~linha 1024),
dentro de um `try/except Exception: pass`.

**Por que só apareceu agora.** Enquanto `validate_model` tinha default
`grau_item1=grau_item3=1`, a re-validação atribuía Grau I aos dois itens documentais.
O resultado *parecia* classificado, mas **nunca** refletia o que o chamador declarou: quem
declarava Grau III recebia Grau I do mesmo jeito. Pior, com os itens 2/4/5/6 em Grau III,
os 2 pontos fabricados completavam 16 pontos e produziam **enquadramento Grau III sem uma
única declaração documental e sem proveniência alguma** — violação direta de
"declaração ≠ verificação" (Tabela 1 itens 1 e 3).

**Payload mínimo.** Propagar as declarações e a proveniência para a chamada final:

```python
best_model.validation_result = NBRValidator.validate_model(
    best_model, X_design, y_design, degree,
    grau_item1=evaluation_policy.get("grau_item1"),
    grau_item3=evaluation_policy.get("grau_item3"),
    item1_provenance=evaluation_policy.get("item1_provenance"),
    item3_provenance=evaluation_policy.get("item3_provenance"),
)
```

Além disso: retirar o `except Exception: pass` em torno do classificador normativo. Uma
exceção ali produz silenciosamente um resultado sem grau, indistinguível de "grau não
atingido" — são coisas diferentes e a segunda não pode absorver a primeira.

**Evidência e teste.** `tests/test_nbr14653.py::TestOptimalCombinationTargetAchieved`:
- `test_declared_documentary_grades_are_discarded_by_legacy_revalidation` fixa o
  comportamento **atual** (itens 1 e 3 em 0, grau `None`) para que o handoff não seja
  fechado por acidente;
- `test_target_achieved_true_when_reachable` está marcado `xfail(strict=True)` com este
  handoff como motivo. Quando C01 aplicar a correção, o `xfail` estrito **falha por passar**
  e sinaliza que o teste deve voltar a ser um teste normal, e que o teste-gêmeo de
  documentação do defeito deve ser removido.

Reprodução:
```bash
cd <worktree> && PYTHONPATH= python3 -m pytest \
  tests/test_nbr14653.py::TestOptimalCombinationTargetAchieved -q
```

### 2.2 → C01/C02 — `backend/api.py`: defaults de formulário

`grau_item1: int = Form(1)` e `grau_item3: int = Form(1)` fazem a API atribuir Grau I a
itens documentais que o usuário não declarou. Pedido: default `None`, e transportar a
proveniência ao lado do grau (`item1_provenance`, `item3_provenance`). Um `selectbox` na
tela não gera evidência documental; sem proveniência o item deve chegar ao classificador
como **pendente**, e o caso fica `review_required`, não liberado.

Vale também para `frontend/components/forms.py`, que já coleta
`item1_grade_declared`/`item3_grade_declared`: o par grau+proveniência precisa viajar
junto até o classificador.

### 2.3 → C01 — produzir `provenance.qualification_context`

C05 fornece o contrato; **C01 é o produtor** do bloco, porque possui
`modules/result_contract.py` e `modules/provenance.py`.

```python
from modules.qualification_profile import assess_qualification

context = {
    "normative_assessment": assess_normative(normative_context),
    "requested_minimum_grade": search_policy.get("minimum_fundamentacao_grade"),
    "profile_evidence": {...},      # {requirement_id: evidence_ref}
    "review_events": [...],         # {professional_id, motive, version, fingerprint}
    "signature": {...},             # {integrity_verified, fingerprint}
    "software_version": "...",
    "result_snapshot_id": "...",
}
block = assess_qualification(context, request_spec["qualification_profile"])
provenance["qualification_context"] = block   # schema_version == "MP-QUAL/1"
```

Extensão aditiva proposta em `RequestSpec`:
`qualification_profile = {id, version, source_set_sha256, purpose, value_basis, method, asset_scope, recipient_id}`.
C01 valida/resolve o perfil (`resolve_profile` devolve erro estruturado para id ou versão
desconhecidos) e compõe o contexto. C02 apenas **escolhe** entre `known_profile_ids()`;
não escreve regra. C03 **apresenta** e não recalcula grau.

**Protocolo de duas passagens** (importante): a primeira chamada devolve
`result_fingerprint`; a revisão e a assinatura são registradas **contra aquele**
fingerprint; a segunda chamada então alcança `ready_for_professional_signoff` e
`signed_integrity_verified`. Qualquer mudança material — dado, parâmetro, amostra, perfil,
regra, modelo, documento, **inclusive a amplitude do IC que define o grau de precisão** —
altera o fingerprint, invalida as decisões dependentes e preserva o histórico em
`stale_review_events`.

### 2.4 → C01 — rota de cálculo do custo (necessária ao perfil securitário)

O perfil `abnt-14653-2-custo-reedicao` está em `blocked_external_evidence`: a **regra** de
enquadramento (Tabelas 6 e 7) está implementada em `classify_custo_fundamentacao`, e as
bases de valor estão especificadas em `VALUE_BASES`, mas a **rota de cálculo** não existe.

Especificação para C01:
- Base correta: `custo_de_reedicao` = custo de reprodução − depreciação
  (ABNT NBR 14653-1:2019, 3.1.11.3 e 3.1.11.5). **Não** é valor de mercado.
- É **vedado** converter preço de mercado em custo por coeficiente. `value_basis_guard`
  recusa essa conversão, e a regressão comparativa **não deve "fingir" custo**.
- Memória de cálculo exigida: custo direto (orçamento sintético **ou** CUB para projeto
  semelhante/diferente do padrão, com ajustes), BDI (calculado/justificado/arbitrado) e
  depreciação física (levantamento do custo de recuperação / métodos técnicos consagrados
  com idade, vida útil e estado de conservação / arbitrada).
- Insumo externo faltante: série **CUB vigente por região e padrão** e o projeto padrão da
  ABNT NBR 12721. Não obtidos nesta campanha — ver `docs/comercial/c05/blockers.md`.

### 2.5 → C04 — dependências

C05 **não instalou nem alterou** dependências. `pypdf` foi usado apenas em ambiente de
desenvolvimento local, para ler os exemplares licenciados e conferir limiares; **não é
dependência de runtime do produto** e nenhum código de produto passou a importá-lo. Ver
`docs/comercial/c05/reuse.json`. C04 é o único editor das constraints globais.

## 3. Retomada

Estado por critério de aceite: `docs/comercial/c05/acceptance.md`.
Fontes e limiares: `docs/comercial/c05/sources.md`.
Dependências externas bloqueadas, com material exato e responsável:
`docs/comercial/c05/blockers.md`.
Reuso de terceiros: `docs/comercial/c05/reuse.json`.

Para reexecutar o aceite desta frente:

```bash
cd <worktree>
PYTHONPATH= python3 -m pytest tests/comercial/c05 tests/c03_normative tests/test_nbr14653.py -q
PYTHONPATH= python3 scripts/comercial/referencia/verify_sources.py \
  --normas-dir docs/normas --require-sources
```

A segunda linha só verifica integridade das fontes onde os exemplares licenciados estejam
presentes localmente; em CI público ela roda apenas a coerência interna, porque as normas
**não** são versionadas.
