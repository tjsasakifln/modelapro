# Contrato mínimo MP/1 e extensões MP-PRO/1

Documento de leitura para o lote. A fonte normativa do runtime continua
sendo `modules/result_contract.py` no `BASE_SHA`.

## Preservar

- RequestSpec / ResultSnapshot MP/1.
- HTTP: `/preview`, `/jobs`, `/jobs/{id}`, `/jobs/{id}/result`,
  `/jobs/{id}/artifacts/{name}`, `/projects`, `/projects/{id}`,
  `/projects/{id}/revisions`, `/projects/{id}/batch`.
- JSON estrito: sem NaN/inf, sem zero no lugar de ausência.
- `value.point`, `mean_ci80`, `prediction_interval`,
  `arbitration_interval`, `admissible_interval`.
- Grau efetivo vem de `validation.fundamentacao`, nunca do pedido.

## Extensões P01 (opcionais em snapshots antigos)

- Entrada canônica: `search_policy.minimum_fundamentacao_grade` (null ou 1..3).
  Aliases históricos normalizados na fronteira; conflito → erro estruturado.
- `provenance.workflow_context` com `schema_version='MP-PRO/1'`.
- `model.formula` quando derivável.
- `report_context` com séries alinhadas à amostra usada.

Consumidores tratam extensão ausente como estado explícito, sem quebrar a base.
