# MP-20260911 — integração C17

Campanha integradora. Não é merge em `main` nem deploy.

## Heads congelados

Base `origin/main`: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`

Ausências: nenhuma. As 16 campanhas publicaram PR e evidência.

| ID | PR | branch | HEAD_SHA | handoff/acceptance SHA (se diferente) | testes locais | lacunas |
| --- | --- | --- | --- | --- | --- | --- |
| C01 | [#4](https://github.com/tjsasakifln/modelapro/pull/4) | `mp-20260911/c01-dados_integros` | `04fd0d5eb914afcce38fe477114417f9e3fdb0bd` | acceptance `7c665df5` | `tests/c01_input` | — |
| C02 | [#2](https://github.com/tjsasakifln/modelapro/pull/2) | `mp-20260911/c02-esquema_categorias` | `963002b80253f3b36c9ec089d4df9228450ad637` | impl `797c75db` | `tests/c02_schema` | dataclass sem `.get` (ligado na integração) |
| C03 | [#5](https://github.com/tjsasakifln/modelapro/pull/5) | `mp-20260911/c03-validacao_normativa` | `88a24b5a57e73bd2894fb573104a69317f95876a` | acceptance `f3c9409f` | `tests/c03_normative` | regras listadas em `unverified_rules.md` |
| C04 | [#7](https://github.com/tjsasakifln/modelapro/pull/7) | `mp-20260911/c04-ajuste_amostra_influencia` | `2cec4051aaf8427a1b4f19e4ed7e852e92cd0911` | impl `6194a020` | `tests/c04_fitting` | `y_transformation` dict da C05 (normalizado) |
| C05 | [#15](https://github.com/tjsasakifln/modelapro/pull/15) | `mp-20260911/c05-busca_ranking_desempenho` | `e93f4690ad290bbcd61f423967fb11aab5607ee4` | impl `98532e68` | `tests/c05_search` | winner público sem `candidate_fit` (ligado) |
| C06 | [#1](https://github.com/tjsasakifln/modelapro/pull/1) | `mp-20260911/c06-transformacoes_alvo` | `a2a9fe140d6f481510f8974d336d48534312ee9a` | impl `a416db2e` | `tests/c06_transformations` | — |
| C07 | [#8](https://github.com/tjsasakifln/modelapro/pull/8) | `mp-20260911/c07-validacao_estabilidade` | `d63af53f7ce091013d1850db11c3cd23876500be` | impl `b1a57459` | `tests/c07_validation` | holdout HTTP completo ainda não é o caminho feliz |
| C08 | [#16](https://github.com/tjsasakifln/modelapro/pull/16) | `mp-20260911/c08-relatorio_revisavel` | `5899308496e0325354f2a8b7c1dcace3a1c44239` | impl `ef274a69` | `tests/c08_report` | extração de texto do PDF exige pypdf/pdftotext ou inflate |
| C09 | [#10](https://github.com/tjsasakifln/modelapro/pull/10) | `mp-20260911/c09-interface_avaliador` | `a68226d05429d7bf02be47339bb967772f817982` | impl `081dc4c6` | `tests/c09_frontend` | UI E2E Streamlit `NOT_RUN` neste host |
| C10 | [#14](https://github.com/tjsasakifln/modelapro/pull/14) | `mp-20260911/c10-api_pipeline_contrato` | `0ef07c8add763588875068374d9117128ba4d090` | impl `8581d67f` | `tests/c10_pipeline` | `row_ledger` lista C01; `output_dir` do dossiê |
| C11 | [#12](https://github.com/tjsasakifln/modelapro/pull/12) | `mp-20260911/c11-persistencia_execucoes` | `b4d2f2b68361bbf94a00939d18fb4762ba9190f8` | handoff `16778f23` | `tests/c11_persistence` | — |
| C12 | [#6](https://github.com/tjsasakifln/modelapro/pull/6) | `mp-20260911/c12-dossie_reprodutivel` | `09303508b9832d6f02747d6ba5f30464eedbdb27` | impl `62be2624` | `tests/c12_evidence` | precisa de `output_dir` real |
| C13 | [#3](https://github.com/tjsasakifln/modelapro/pull/3) | `mp-20260911/c13-acoes_para_concluir` | `a76f53acd59eefdf70244c71ddd9f48eda1bb1ee` | impl `33a6ef72` | `tests/c13_decisions` | — |
| C14 | [#9](https://github.com/tjsasakifln/modelapro/pull/9) | `mp-20260911/c14-lotes_reuso_modelos` | `b24ad1d36546144c3c827f9075bdce1a15f52488` | impl `1a9f80d6` | `tests/c14_batch` | modelo `subject_specific` não reusa como população |
| C15 | [#13](https://github.com/tjsasakifln/modelapro/pull/13) | `mp-20260911/c15-instalacao_ci_local` | `65943304068fbc8d439a137b6d5528f20bbd0cbe` | acceptance `9e864419` | `tests/c15_packaging` | Windows não executado aqui |
| C16 | [#11](https://github.com/tjsasakifln/modelapro/pull/11) | `mp-20260911/c16-oraculos_aceite_independente` | `b2939d57d63400c875cff10fca8dda5825f8da64` | impl `875f7040` | `tests/acceptance` | harness contra o snapshot antigo de `main` |

Composição: merges `--no-ff` na ordem C15 → C01 → C02 → C06 → C03 → C04 → C07 → C05 → C11 → C12 → C13 → C14 → C10 → C08 → C09 → C16. Histórico completo de cada campanha está na branch (não só o tip).

Handoff SHA ≠ HEAD: commits posteriores só registraram URL da PR, SHA de evidência, ou correção pontual já no HEAD incorporado. C17 congela o HEAD da PR, não o SHA do handoff atrasado.

## Ligação MP/1 (produção)

`backend.worker.resolve_peers` importa os caminhos congelados. Simuladores `contract_simulator=True` ficam em `tests/c10_pipeline/doubles.py`.

Ajustes só na branch consolidada (não reescritos nas branches dos donos):

1. `PreparedDataset` / `SubjectDesign` / `CandidateSpec` / `CandidateFit` / `CandidateAssessment` / `InputBundle` respondem `.get` (mappings no processo).
2. `CandidateSpec.from_obj` aceita `y_transformation={name: ...}` da C05 e grava o nome.
3. `search_models` converte dataclass C02 em mapping; o winner público conserva `candidate_fit` / `model_object` para `evaluate_fitted`.
4. C10 conta `row_ledger` lista da C01 (`observed_target` ≠ `received` quando há alvo ausente).
5. C10 passa `output_dir` do dossiê sob o root C11 quando o caller não informa.
6. CORS da API usa `config.cors_origin_list()` (C15), nunca `*`.
7. Adaptador legado C05 preenche `ModelResult.coefficients` a partir do winner MP/1.

## Ambiente executado

- OS: Linux (WSL2), `uname` em evidência de aceite. Windows: `NOT_RUN`.
- Python 3.12.3, venv `.venv`, `PYTHONPATH` vazio.
- Instalação: `pip install -c constraints/linux-py3.txt -e ".[dev]"`
- Redis: não usado. Bind: `127.0.0.1`.
- WeasyPrint: probe `ok` neste host.

## Comando único de aceite

```text
python scripts/c17_acceptance/run.py --output DIR
python scripts/c17_acceptance/run.py --output DIR --full
```

O script grava `git rev-parse HEAD` **antes** de qualquer pytest.

## Parecer I01–I11 (composto atual)

| ID | Parecer | Prova |
| --- | --- | --- |
| I01 | Corrigido | `PreparedDataset`/`SubjectDesign` são Mapping; `tests/c17_integration/test_review_i01_i11.py::TestI01CanonicalObjects` |
| I02 | Corrigido | C02 `parse_numeric` delega a C01 `parse_numeric_token`; matriz no teste I02 |
| I03 | Corrigido | winner público carrega `candidate_fit`; frozen `model_state.coefficients` não vazio; teste I03 |
| I04 | Corrigido | C10 reutiliza `assessment.normative` da C04; `predict_original` devolve `{point}`; teste I04 |
| I05 | Corrigido | `_FoldPredictor.predict` + encoder do fold; métricas C07 em `validation.statistical.procedure` |
| I06 | Corrigido | `POST /preview` com `{}` devolve `feature_schema`, `row_ledger`, `sample_preview`; alvo pode estar vazio |
| I07 | Corrigido | `report_context.used_rows` com valores; `snapshot.model.coefficients` |
| I08 | Corrigido | `delivered_matches_used` compara fit vs assessment; mutação de `used_row_ids` falha o match |
| I09 | Pendente (Windows) | Linux: WeasyPrint probe ok + PDF gerado. Windows CI C15: `--check-pdf` exit 1 (libgobject). Não declarar PDF Windows. |
| I10 | Parcial | Matriz abaixo (achado original ≠ ID C16). Oráculos C17 no composto; harness C16 do snapshot antigo não é evidência deste SHA. |
| I11 | Declarado | RMSE de treino não é generalização; modo limitado não afirma ótimo global (`exact_optimum_guaranteed` false). |

Auditoria original vs C16 (mesmo problema, IDs diferentes):

| Achado original | ID C16 | Observação |
| --- | --- | --- |
| F01 extrapolação | C16-F04 | item 4 / faixa |
| F02 preço ausente | C16-F01 | never impute |
| F03 parsing | C16-F02 | locale / ambíguo |
| F04 categorias | C16-F03 | categoria não vista |
| F05 ranking | C16-F06 | escalas / audit |
| F06 exclusões | C16-F05 | report_only |
| F07 avisos/verde | C16-F07 / F10 | estados / point null |
| F08 anexos | C16-F08 | PDF/dossiê >200 |
| F09 data-base | C16-F09 | unit/date pending |
| F10 interface valor | C16-F07 | GET result |
| F11 busca | C16-F11 | search_audit |
| F12 transformações | C16-F12 | sqrt(0) |
| F13 recuperação | C16-F13 | GET sem WS |
| F14 isolamento | C16-F14 | dois jobs |
| F15 instalação | C16-F15 | C15 venv |
| F16 seleção vazia | C16-F16 | `[]` |

## Resultado

Preenchido após o commit de integração e a execução no mesmo SHA (ver `ACCEPTANCE_MATRIX.json`).

- `TECHNICAL_E2E`: ver matriz (PASS só com fluxo A–J no SHA anunciado).
- `NORMATIVE_VERIFICATION`: `PARTIAL` — regras calculadas pela C03 com edição/fonte; cláusulas em `docs/campaigns/MP-20260911/C03/unverified_rules.md` permanecem pendentes. Não é “norma inteira certificada”.
- `DELIVERY`: PR consolidada; merge/deploy **não** autorizados.
- `MAIN_MERGED`: NO
- `DEPLOYED`: NO

## Próximo ato humano

Revisar a PR `mp-20260911/integracao-final` → `main`. Merge e deploy exigem autorização explícita fora deste lote.
