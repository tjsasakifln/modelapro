# Testes que fixam defeitos — leia antes de consertar

Estes testes estão **verdes porque o defeito existe**. Eles ficam
**vermelhos quando o defeito for consertado**. Isso é intencional: o defeito
fica visível no registro da campanha em vez de virar um comentário que
ninguém lê.

Eles rodam dentro da suíte ampla (`wide-suite-linux` executa `pytest tests`).
Então, quando C01 ou C05 consertar o que eles fixam, **a suíte ampla obrigatória
fica vermelha por uma mudança correta** — e quem vir o CI vermelho não tem como
adivinhar que era esperado. Este documento existe para que tenha.

Capitais no docstring ajudam quem abre o arquivo. Não ajudam quem olha um run
vermelho. Por isso a lista está aqui, e não só lá.

## A lista

| Teste | Defeito fixado | Dono | O que fazer quando consertar |
|---|---|---|---|
| `tests/pro_workflow/p04/test_metamorphic_reference.py::test_exactly_singular_design_escapes_the_absolute_rank_threshold_once_rescaled` | O gate de posto é limiar **absoluto** (`min\|diag(R)\| < 1e-12`), então multiplicar as colunas por 1e4 levanta 2e-15 para 2e-11 e o mesmo design exatamente singular passa | C01 (núcleo numérico) | Inverter para asserção positiva: critério de posto **relativo** recusa o design em qualquer escala |
| `tests/pro_workflow/p04/test_metamorphic_reference.py::test_genuinely_near_collinear_design_at_unit_scale_is_accepted` | Designs com `cond_2(X)` até ~2.2e13 são aceitos sem aviso | C01 (núcleo numérico) | Inverter: colinearidade quase-exata é recusada ou sinalizada, com o limiar declarado |
| `tests/pro_workflow/p04/test_metamorphic_reference.py::test_duplicated_observation_buys_spurious_precision` | Uma propriedade repetida estreita o intervalo como se fosse informação nova | C01 (amostra) / C05 (regra de independência) | Inverter: duplicata do mesmo bem não conta como observação independente para largura de intervalo |

## Um quarto achado que não é testável aqui

`tests/fixtures/pro_workflow/ols_oracle.py` **não tem retransformação de alvo
logarítmico**: não há `exp`/`log`, nem estimador de smearing, nem correção de
meia-variância. Não existe teste a inverter — existe uma rota que não existe.
Se o produto passar a oferecer alvo log, a correção de retransformação precisa
ser implementada **e** referenciada, e este parágrafo vira um teste.

## Regra

Ao consertar um destes defeitos: **inverta o teste na mesma mudança**. Não o
apague, não o marque `xfail`, não o afrouxe. O contrato comum proíbe as três
coisas, e apagá-lo apaga também o registro de que o defeito existiu.

Cruzamento: `docs/comercial/c06/handoff_c01_grade_not_met.md` trata de um
defeito **diferente** (grau pedido destruindo o resultado), já implementado por
C01 em `1d40285`. Nenhum dos três testes acima pertence àquele handoff.
