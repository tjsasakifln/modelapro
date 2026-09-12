# Handoff C06 → C01 (com C05 no caminho): grau pedido destrói o resultado em vez de classificá-lo

Frente emissora: MP-COM-20260912/C06. Não editamos `modules/pro_workflow/`,
`modules/result_contract.py`, `modules/optimal_combination.py` nem
`backend/worker.py` — o proprietário implementa. Este documento é pedido de
alteração com payload mínimo, evidência e critério de aceite.

Descoberto ao trocar o job `p04-harness` de `--mode diagnose-base` para
`--mode accept-candidate` (gap R20-A). O modo diagnóstico escondia isto.

## Cláusula aplicável (contrato comum MP-COM/2, §3), citada

> Preservar `requested_minimum_grade` e `grade_requirement_status` =
> `not_requested`/`met`/`not_met`/`pending`/`error`.

> Cálculo tecnicamente válido sem grau atendido pode ser apresentado como
> análise não liberada, jamais como avaliação final aprovada.

Isto é, grau não atendido é um **rótulo do resultado**, não uma causa de morte
do job. O estado `not_met` precisa existir para poder ser observado.

## Repro mínimo

Mesmo corpus, mesma spec, **um único campo de diferença**:

```python
from tests.fixtures.pro_workflow import corpus
from tests.pro_workflow.p04.helpers import client, run_job

case = corpus.s02_ptbr_and_missing()
base = dict(mode="exact", budget=16, objective="aic", seed=17,
            y_transformations=["identity"])

for tag, sp in (("NOGRADE", dict(base)),
                ("GRADE", dict(base, minimum_fundamentacao_grade=2))):
    spec = corpus.pinned_identity_spec(
        import_options={"locale": "pt-BR", "delimiter": ";", "encoding": "utf-8"},
        search_policy=sp)
    out = run_job(client(), corpus.s02_csv_bytes(case), spec=spec,
                  subject=case["subject"], require_success=False)
    snap = out["snapshot"] or {}
    wc = (snap.get("provenance") or {}).get("workflow_context") or {}
    print(f"{tag}: state={out['status'].get('state')} "
          f"snapshot={'yes' if snap else 'NONE'} "
          f"point={(snap.get('value') or {}).get('point')} "
          f"grade_status={wc.get('grade_requirement_status')} "
          f"requested={wc.get('requested_minimum_grade')}")
```

Comando: `PYTHONPATH= python3 <script>` no worktree
`mp-pro-20260911/p04-referencia-consolidacao`, SHA `8d66c797`.

## Observado

```
NOGRADE: state=interrupted snapshot=yes  point=735000.0 grade_status=not_requested requested=None
GRADE:   state=failed      snapshot=NONE point=None     grade_status=None          requested=None
```

O cálculo é **tecnicamente válido**: um instante antes, a mesma amostra e o
mesmo modelo produziram `735000.0`. Pedir grau 2 não reclassificou esse
resultado — apagou-o. `not_met` é inobservável porque nenhum snapshot
sobrevive para carregá-lo.

Complemento pelo HTTP: `POST /jobs` → 202; estado final `failed`;
`GET /jobs/{id}/result` → **409 Conflict**; `result_available: false`.

Issues emitidas:

| code | severity | origin |
|---|---|---|
| `no_admissible_winner` | warning | `C05` |
| `NO_WINNER` | error | `c10.worker` |

## Qual camada derruba o snapshot

Duas camadas distintas, e só a segunda é o defeito:

1. `modules/optimal_combination.py:433` emite `no_admissible_winner` com
   severidade **warning**. Correto: nenhum candidato atendeu a admissibilidade
   com o enquadramento exigido. Um aviso não deveria matar o job — e, de fato,
   `_has_error_issues` é falso aqui.
2. `backend/worker.py:1220-1223` é quem derruba tudo:

```python
winner = _get(search_result, "winner")
if winner is None:
    raise CompositionError(
        "search_models returned no winner",
        search_issues + [make_issue("NO_WINNER", "search_models returned no winner", origin="c10.worker")],
    )
```

`winner is None` por **não atingir o grau pedido** é tratado do mesmo modo que
`winner is None` por domínio matemático inválido, singularidade ou dados
corrompidos. São situações diferentes e o contrato as separa: as últimas são
recusa legítima; a primeira é uma análise válida não liberada.

Portanto o pedido atravessa C05 (que já classifica corretamente, como warning)
e recai sobre C01 na fronteira `backend/worker.py` / `result_contract` /
`workflow_context`.

## Payload mínimo pedido

Quando o único motivo de não haver vencedor admissível for o grau mínimo
solicitado, e existir um modelo tecnicamente válido:

- produzir o snapshot normalmente, com `value.point` do modelo válido;
- `provenance.workflow_context.schema_version = "MP-PRO/1"`;
- `requested_minimum_grade = 2` (o valor canônico pedido);
- `grade_requirement_status = "not_met"`;
- estado de caso **não liberável** (análise, não avaliação final aprovada) —
  reusar o estado existente equivalente e mapeá-lo explicitamente, sem inserir
  um valor que o contrato rejeite;
- `GET /jobs/{id}/result` deve entregar esse snapshot, não 409.

Não é pedido: aprovar por ausência de grau, rebaixar o grau pedido, nem
converter `not_met` em `met`. Também não é pedido mudar o caso legítimo de
recusa (singularidade, domínio inválido, categoria sem suporte, dados
corrompidos), que deve continuar falhando.

## Critério de aceite que C06 vai reexecutar

Mesma spec com `minimum_fundamentacao_grade: 2` sobre `corpus.s02_ptbr_and_missing()`:

- snapshot presente;
- `value.point == 735000.0` (mesmo ponto do caso NOGRADE);
- `provenance.workflow_context.requested_minimum_grade == 2`;
- `provenance.workflow_context.grade_requirement_status == "not_met"`;
- estado do caso não liberável para emissão qualificada;
- `GET /jobs/{id}/result` != 409.

Teste que fecha: `tests/pro_workflow/p04/test_candidate_extensions.py::test_minimum_fundamentacao_grade_canonical_field`
com `P04_REQUIRE_EXTENSIONS=1`. Hoje vermelho — é o motivo de o job
`p04-harness` estar vermelho no candidato, e essa vermelhidão é o portão
funcionando, não uma regressão introduzida por C06.

## Status

`BLOCKED_ON_C01` para o aceite C06-A03 nesta propriedade. C06 não contorna,
não relaxa o assert e não volta para `diagnose-base`.
