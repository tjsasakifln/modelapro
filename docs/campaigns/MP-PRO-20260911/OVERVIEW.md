# MP-PRO-20260911 — lote de incremento profissional

Objetivo: avanço concreto rumo ao uso cotidiano do MODELA PRO. Não é
certificação normativa integral, prontidão absoluta, Windows PDF nem
piloto humano de mercado.

| ID | Papel | Branch |
| --- | --- | --- |
| P01 | núcleo, contratos, seleção, persistência, lote, dossiê | `mp-pro-20260911/p01-nucleo-reuso` |
| P02 | frontend / rotina de interface | `mp-pro-20260911/p02-rotina-interface` |
| P03 | relatório técnico / decision_support | `mp-pro-20260911/p03-relatorio-tecnico` |
| P04 | referências independentes, medição, CI, consolidação | `mp-pro-20260911/p04-referencia-consolidacao` |

`BASE_SHA=6d54f902b85a5a37bfbf154d39f74cf854ff9b2b`. Referência de
integração: PR #17 (`mp-20260911/integracao-final`). Nenhuma campanha
escreve em `main`, na branch da PR #17 ou na branch de outra campanha.

P04 descobre as PRs pelo prefixo `[MP-PRO-20260911/P0x]`. Incorpora
somente HEADs `SEALED` na própria branch. Sem selo o estado é
`LOCAL_READY_COMPOSITION_PENDING`.
