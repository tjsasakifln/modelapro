# Verificação do handoff de grau contra o HEAD de C01

C06 emitiu `handoff_c01_grade_not_met.md` com um critério de aceite explícito e
se comprometeu a reexecutá-lo. Isto é o resultado da reexecução.

- HEAD verificado: `1d40285aa47d2f0cb6da7dcdbb1776a6c0081a3f`
  (`mp-com-20260912/c01-motor-comprovado`, worktree limpo, handoff publicado em
  `docs/comercial/c01/handoff.md`)
- Método: worktree descartável em `--detach` sobre esse HEAD; nenhuma alteração
  no worktree de C01 e nenhum arquivo de C01 editado por C06.
- Comando: mesmo script NOGRADE/GRADE do handoff, `PYTHONPATH=` vazio.

## Observado

```
NOGRADE: state=succeeded snapshot=yes point=735000.0 grade_status=not_requested requested=None   HTTP 200
GRADE:   state=succeeded snapshot=yes point=735000.0 grade_status=pending      requested=2      HTTP 200
```

Contra o BASE_SHA `8d66c797`, onde o caso GRADE era
`state=failed snapshot=NONE point=None` com `GET /jobs/{id}/result` → 409.

| Critério do handoff | Resultado |
|---|---|
| snapshot presente | **PASS** |
| `value.point == 735000.0` | **PASS** |
| `requested_minimum_grade == 2` | **PASS** |
| `grade_requirement_status == "not_met"` | **divergente — ver abaixo** |
| `GET /jobs/{id}/result != 409` | **PASS** |
| caso não liberável para emissão qualificada | **PASS** |

## A divergência, e por que ela não é uma reprovação

O critério exigia `not_met`; o observado é `pending`. Isso **não** é o defeito
original e **não** é afrouxamento do critério — é uma correção do critério, e a
distinção importa.

O defeito era: cálculo tecnicamente válido **destruído** em vez de rotulado.
Isso está resolvido. O ponto sobrevive, o pedido é registrado, e o caso não é
liberável:

```
provenance.qualification_context (MP-QUAL/1):
  calculation_status     = fitted
  grade_requirement_status = pending
  case_release_status    = review_required
  rule_results           = [c01.numeric_fit: passed,
                            c01.grade_requirement: pending_manual]
  review_events          = []
  institution_acceptance = null
```

`case_release_status` é `review_required`, **não**
`ready_for_professional_signoff`. A regra decisiva do grau está
`pending_manual`, não `passed`. Nenhuma aprovação foi fabricada por ausência
de fonte.

E `pending` é o rótulo **certo** aqui, não um rótulo pior que `not_met`.
Decidir entre `met` e `not_met` é ato do classificador normativo, e o contrato
comum (§3) diz que deve haver **um** classificador normativo em produção — que
pertence a C05, ainda ausente neste HEAD. Afirmar `not_met` sem a autoridade
que faz essa classificação seria inventar uma decisão normativa. O contrato
lista `pending` entre os valores válidos exatamente para este estado, e proíbe
que `pending`/`None` chame outro classificador para conseguir um grau.

Meu critério original presumia que o grau podia ser decidido sem C05. Essa
premissa estava errada, e o erro era meu.

## O critério que fica armado

`not_met` continua exigido, deslocado para o momento em que C05 publicar o
classificador. Quando o HEAD de C05 for incorporado, C06 reexecuta:

- o mesmo caso com `minimum_fundamentacao_grade: 2` deve produzir
  `grade_requirement_status == "not_met"` (ou `met`, se a amostra atingir),
  **nunca** permanecer `pending` com C05 presente;
- `rule_results` para a regra de grau deve sair de `pending_manual` para um
  status decidido, com `source_id`, `edition_or_version` e `clause`;
- `case_release_status` só pode chegar a `ready_for_professional_signoff` com
  a regra decidida como `passed`.

Enquanto isso, `C06-A03` permanece **`IMPLEMENTED_PARTIAL`**, não `PASS`: a
incapacidade de aprovar por ausência está provada, a capacidade de aprovar
legitimamente não está — porque a autoridade que aprovaria não existe ainda.

## O que isto não autoriza

Não é composição. O HEAD de C01 foi lido em worktree descartável, não
incorporado à branch da #20. C02, C03, C04 e C05 seguem com trabalho não
commitado, e o contrato manda montar **um** candidato. `C06-A06` continua
`WAITING_FOR_COMPONENTS`.

Não é aprovação de C01. É a verificação de **um** critério, emitido por C06,
sobre **um** HEAD, num instante registrado. Qualquer mudança posterior em C01
reabre este aceite.
