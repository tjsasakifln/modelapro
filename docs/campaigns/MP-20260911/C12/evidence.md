# C12 — Dossiê de evidências e reprodução numérica segura

Campanha do lote MP-20260911. Base auditada: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`.
Fixtures e evidências desta pasta/PR são sintéticas (`SYNTHETIC_FIXTURE_C12_NOT_PRODUCTION`). Nenhum dataset real de cliente foi empacotado.

## O que foi entregue

- `modules.evidence_bundle.build_evidence_bundle(snapshot, input_bundle, prepared_dataset, artifacts, output_dir) -> manifest`
- Pacote local: snapshot congelado primeiro, bases original/interpretada, amostra efetiva, exclusões com justificativa, colunas de identificação/fonte mesmo fora de X, esquema/encoder declarativos, políticas, coeficientes integrais, transformações, datas, versões, artefatos opacos, ledger de completude (`presente` | `declarado` | `verificado` | `faltante`).
- Manifesto com SHA-256, tamanho, tipo, versão e função de cada arquivo, mais `input_id` / `code_id` / `schema_id` / `policy_id`. O manifesto **não** inclui o próprio hash.
- CSV bruto preserva células iniciadas por fórmula; `data/visualization/*.safe.csv` prefixa essas células. UTF-8, delimitador `,`, precisão numérica em texto decimal / `ieee_hex`.
- Reprodução a partir do disco: coeficientes declarados + whitelist fechada de transformações + inversa para a unidade original. Recusa pickle/eval/exec e não devolve `snapshot.value.point` memorizado.
- CLI: `python scripts/c12_reproduce/reproduce.py --bundle PATH`

C12 não gera PDF (C08) e não congela o snapshot (C10). Ligação API/GUI/persistência fica em `handoff.json`.

## Comandos

```text
python3 -m pytest tests/c12_evidence/ -q
# 13 passed, exit 0

python3 -c "from modules.evidence_bundle import build_evidence_bundle; ..."
# manifest sem self-hash; used=210 / excluded=10 / received=220; IDs iguais ao snapshot

python3 scripts/c12_reproduce/reproduce.py --bundle {bundle}
# duas execuções, ambas exit 0, point=110000.0 idêntico, versões compatíveis

# um byte alterado em data/used_sample.csv
python3 scripts/c12_reproduce/reproduce.py --bundle {bundle}
# exit 2, hash mismatch: data/used_sample.csv; point=null (não usa valor memorizado)
```

## Critérios

| ID | Resultado local | Prova |
|----|-----------------|--------|
| C12-A01 | pass | `tests/c12_evidence/test_a01_complete_package.py` — n=220, tabelas completas, IDs e 3 coeficientes |
| C12-A02 | pass | `test_a02_integrity_manifest.py` + CLI tamper exit 2 |
| C12-A03 | pass | `test_a03_reproduction.py` — ponto/IC a partir do disco; legado só-fórmula falha sem ecoar o ponto |
| C12-A04 | pass | `test_a04_csv_safety.py` — bruto vs viz; traversal rejeitado; `.py` extra não executa |
| C12-A05 | pass | `test_a05_completeness.py` — lacunas `faltante`; share copy não apaga o original; log sem dataset |

Status da campanha: **INTEGRATION_PENDING** (pares C01/C02/C08/C10/C11 não ligados no worker desta PR). Não é PASS_E2E.

## Revisão (autor)

- Snapshot é escrito antes do registro de artefatos; manifesto por último, sem self-hash.
- Foto/documento ausente permanece `faltante`; nenhum PNG/JPG é gerado para preencher buraco.
- Coeficientes não passam pela fórmula de 4 decimais de `ModelBuilder._get_formula`.
- Dependência de C10 para chamar `build_evidence_bundle` após `freeze_result_snapshot` e de C11 para persistir o pacote fora do snapshot.
