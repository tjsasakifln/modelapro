# C08 — Relatório coerente, integral e pronto para revisão

Campanha do lote MP-20260911. Componente local; a composição E2E cabe à C17.

## Achados reproduzidos no código de `c92949e`

No `generate_pdf_report` legado, antes desta correção:

- F07: a estimativa pontual era reconstruída invertendo o campo de arbítrio (`central = bound / (1 ± CAMPO_ARBITRIO)`), não copiada de um snapshot.
- F08: `datetime.now()` era gravado como data-base; gráficos de resíduos usavam títulos em inglês (`Residuals vs Fitted`, `Histogram of Residuals`).
- F09: `market_data.head(200)` truncava a planilha e o HTML dizia "Exibindo 200 de N". Repro: 220 linhas, nota de truncamento presente, `row-0219` ausente.
- F10: qualquer exceção era logada e a função devolvia `None` (o worker tratava isso como PDF ausente sem falha de artefato).

Log: `/tmp/grok-goal-5bf97f948c30/implementer/repro_f07_f10.txt`.

## O que foi implementado

- `modules.results_generator.render_report(snapshot, report_context) -> bytes` consome um mapping MP/1 e **não** ajusta OLS nem inverte intervalos.
- `build_report_view` é mapeamento puro snapshot→visão (sem I/O, sem statsmodels).
- `generate_pdf_report` permanece adaptador de `ModelResult` para C16/worker: data-base fica pendente, ponto só se já persistido, planilha integral, `None` só para entrada inválida.
- `ReportRenderError` (código `C08_PDF_ENGINE_FAILED` / `C08_INVALID_SNAPSHOT` / …) com `to_issue()` para C10. `render_report` nunca devolve `None`.
- Template: minuta (não laudo aprovado), data-base/vistoria/fontes/emissão separados, pendências visíveis, n recebido/observado/preparado/usado/excluído distintos, issues por origem, precisão `unclassified`, busca aproximada, documentos declarado/presente/verificado, next_actions, coeficientes com precisão integral, R² sem pretender avaliação superior, descritiva amostral (não diagnóstico completo), planilha paisagem integral + anexo de IDs, gráficos em português.

## Aceites locais

| ID | Resultado | Prova |
| --- | --- | --- |
| C08-A01 | passou | `tests/c08_report/test_a01_snapshot_numbers.py` extrai `MP1_POINT`/`IC`/`datas`/`unidade` do PDF gerado por `render_report`; OLS/`build_model` monkeypatched para falhar se chamados. Unidade ausente → pendência, sem `R$` nem data de hoje como data-base. BRL e BRL/m² formatados quando confirmados. |
| C08-A02 | passou | `test_a02_warnings.py`: issues normativo/estatístico/documental/busca/inferência distinguíveis; `precisao.status=unclassified`; busca aproximada; documentos declarado≠presente≠verificado; next_actions; minuta; R² não é avaliação superior. |
| C08-A03 | passou | `test_a03_integral_rows.py`: 210 usados + 12 excluídos; `used-0001`, `used-0210`, `used-0201`, `excl-0001` no PDF; n do snapshot = listas. Sem "Exibindo 200 de". |
| C08-A04 | passou | PDF sintético 24 páginas rasterizado com pypdfium2 (pdftoppm ausente no ambiente). Páginas não brancas; IDs e "José da Silva — Avaliação nº αβ € ção" visíveis; tabelas em paisagem sem quebra no `row_id`; gráficos PT. Evidência visual só com fixture sintética. |
| C08-A05 | passou | `test_a05_exception.py`: `weasyprint.HTML.write_pdf` levanta `RuntimeError` → `ReportRenderError` código `C08_PDF_ENGINE_FAILED`; snapshot `None` → `C08_INVALID_SNAPSHOT`. |

Launch em processo fresco (duas vezes): `tests/c08_report/test_library_launch.py` escreve `{SCRATCH}/render_report_run1.pdf` e `run2.pdf`; `MP1_POINT=350000` nos dois.

## Inspeção de PDF

- `pdftotext`/`pdftoppm`: não instalados (`c08_pdf_tools.log`, rc 127). Rasterização com pypdfium2 (ferramenta de inspeção, **não** dependência de produto).
- WeasyPrint 70.0; extração de texto via pypdf com normalização de NULs UTF-16.
- Páginas inspecionadas: minuta/valores (known-01), avisos (known-02), documentos/ações (known-03), gráficos PT (known-04/05), planilha paisagem (fix-page-07/08/22/23), anexo integral de IDs (page-26). Sem sobreposição de células; nomes longos quebram na coluna de rótulo; `row_id` permanece numa linha.

## Testes

```
python3 -m pytest tests/c08_report/ tests/test_results_generator.py \
  tests/test_audit_fixes.py::TestExhaustiveDisclosurePropagation -q
```

22 passed (pytest 9.1.1, Python 3.12.3, weasyprint 70.0, jinja2 3.1.6). Duração ~2 min.

C16 `generate_pdf_report(..., exhaustive=, search_message=)` continua a devolver `%PDF`.

## Fora de escopo / não feito

- DOCX (C15).
- Edição de `backend/worker.py` / frontend / `result_contract.py` (C10 ainda chama o adaptador e trata `None` como PDF ausente).
- Dados reais de cliente no repositório.
