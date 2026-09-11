# P03 — Relatório técnico revisável e recomendações coerentes

- ID: P03
- Lote: MP-PRO-20260911
- BASE_SHA: `6d54f902b85a5a37bfbf154d39f74cf854ff9b2b`
- Branch: `mp-pro-20260911/p03-relatorio-tecnico`
- Base da PR: `mp-20260911/integracao-final` (PR #17 aberta/draft)
- Classificação local: `IMPLEMENTED_VERIFIED`
- Integração P01: pendente de transporte (handoff.json)
- Isto é minuta para revisão profissional, não laudo automaticamente aprovado.

## O que foi implementado

`render_report` / `build_report_view` / `recommend_next_actions` preservam as assinaturas. A apresentação lê `search.audit`, compõe a equação dos coeficientes canônicos, distingue escala de ajuste e estimativa monetária, recusa séries desalinhadas, completa o anexo 210+ e desloca `MP1_*` / hashes / job para a trilha técnica.

`recommend_next_actions` reconhece `provenance.workflow_context.subject_raw` (MP-PRO/1 opcional), trata validação não solicitada como ação opcional, não recomenda excluir dado para elevar R²/grau, e não compara alternativas de busca sem valor pontual como se fossem avaliações incompatíveis.

## Testes

```
python3 -m pytest tests/c08_report tests/c13_decisions tests/test_results_generator.py tests/pro_workflow/p03 -q --tb=line
```

54 passed, exit 0 (Python 3.12.3, pytest, WeasyPrint 70.0). Log: scratch `p03_pytest.txt`.

C08 e C13 herdados continuam verdes. P03-A01–A06 em `tests/pro_workflow/p03/` chamam as funções publicadas (não reimplementação).

Launch em processo fresco (duas vezes): `p03_launch_run1.pdf` / `run2.pdf`, `MP1_POINT=350000` nos dois; `p03_actions_run1.json` / `run2.json` idênticos, sem `provide_subject_characteristic` quando o avaliando está em `workflow_context`.

## Antes / depois (avaliação real na BASE_SHA)

Não é a fixture C08 conhecida. `compose_valuation_job` no SHA `6d54f90`, mercado linear sintético identificado (`preco = 10000 * area`, n=24, avaliando area=73.5). Ponto 735000 BRL. Sem dados pessoais de cliente.

| | Antes (BASE_SHA renderer) | Depois (esta branch) |
| --- | --- | --- |
| PDF | `evidence/before.pdf` (8 páginas) | `evidence/after.pdf` (10 páginas) |
| Ponto congelado | `MP1_POINT=735000` | `MP1_POINT=735000` |
| Busca | «Pendência: o snapshot não declara se a busca foi exaustiva» (`search` só tem `audit`) | Cobertura lida do audit: enumeração do espaço declarado, 7 especificações, sem ótimo global inventado |
| Fórmula | «Pendência: fórmula não informada» (coeficientes `const`, `area=10000` presentes) | `preco = -9.50527122392932e-10 + 10000·area` |
| R² | «—» (estava em `validation.statistical`) | 1.0000, rotulado como ajustamento da amostra usada, não desempenho externo |
| Gráficos | «seção pendente» | Ausência explicada; cálculo preservado |
| Frozen MP1 | primeira página | trilha técnica |

Snapshot sanitizado: `evidence/base_sha_snapshot.json`.

## Correções editoriais ainda necessárias

Contagem no documento gerado da avaliação BASE_SHA (classes, não horas poupadas — nenhuma hora inventada): **11**.

1. `next_actions` congeladas pelo C10 ainda trazem `provide_subject_characteristic` (avaliando não está no snapshot; P01 precisa de `workflow_context.subject_raw`).
2. `incompatible_alternative_comparison` ainda no snapshot congelado (alternativas de busca sem `value.point`); o recálculo P03 já deixa de emití-la.
3. Fonte/justificativa por linha ausentes no `report_context` do C10 («Fonte não informada no contexto»).
4. Séries de gráfico não transportadas.
5. Estimando `subject_prediction` em inglês técnico.
6. Identificadores duplos `R000000` / `IM-00`.
7. Amplitude de precisão em notação científica (~3e-14) no ajuste perfeito.
8. Fundamentação «Não classificado» com 12 pontos (classificação do produtor).
9. Códigos técnicos nos textos de issue (`grau_nao_e_emissao`, `C10: draft / review_required`).
10. Data de emissão em ISO com `T`.
11. Alternativas listadas pelo `candidate_id` cru.

Itens 1–4 são handoff P01. Os demais são redação residual da minuta, não recálculo.

## Verificador e falha estruturada

- PDF antigo MP/1 sem MP-PRO/1: `p03_old_snapshot.pdf`, ponto e graus iguais ao input.
- Motor de PDF forçado a falhar: `ReportRenderError` código `C08_PDF_ENGINE_FAILED` (`p03_render_error.txt`); não devolve bytes vazios.
- Verificador: original limpo; mutações de valor, unidade, grau, linha de anexo e equação sinalizadas (`p03_verifier.txt`).
- Anexo 210+: `used-0201` presente; 20 páginas; rasters pypdfium2 das páginas 1, 11 e 20 preenchidos (não brancos). Extrema de luminância (26–255), (29–255), (26–255).

## Handoff P01

`handoff.json`. Fixtures enriquecidas em `tests/pro_workflow/p03/fixtures.py` estão rotuladas `synthetic P03 presentation fixture — not P01 integration`.

## Limitações

- Não emite laudo, ART, vistoria, assinatura nem dados cadastrais do avaliador.
- Windows PDF não verificado.
- P04 confere o relatório do pipeline conjunto, não só o render sobre fixture.
