# C06 — handoff retomável

Campanha `MP-COM-20260912/C06` — validação independente, consolidação e
liberação comercial. Frente integradora e dona da prova final.

- BASE_SHA do contrato: `8d66c7973c659174e06d7223c9a9a8181e8eeabf`
- Destino de composição: PR **#20**, branch
  `mp-pro-20260911/p04-referencia-consolidacao` (base `mp-20260911/integracao-final`)
- Worktree de trabalho: `/home/tjsasakifln/code/modela-pro-p04`
- C06 é a **única** frente autorizada a publicar a composição nessa branch.

## Como retomar

```bash
cd /home/tjsasakifln/code/modela-pro-p04
git fetch origin mp-pro-20260911/p04-referencia-consolidacao
PYTHONPATH= python3 -m pytest tests/c15_packaging/test_ci_aggregator.py \
    tests/c15_packaging/test_workflow_triggers.py -q          # portão do aceite
PYTHONPATH= python3 scripts/pro_workflow/run.py \
    --mode accept-candidate --output /tmp/p04-accept          # candidato estrito
```

O segundo comando **hoje sai 1**. Ver o handoff de grau abaixo: isso é o
portão funcionando, não uma regressão.

## O que está feito e verificado

**C06-A01 — aceite realmente bloqueante: `IMPLEMENTED_VERIFIED`.**
`docs/comercial/c06/r20a_gate.md`. O gap R20-A eram três defeitos
independentes (pipe sem `pipefail`, candidato avaliado em `diagnose-base`,
agregador que só lia conclusões de job). Todos corrigidos, com matriz de
injeções obrigatórias e guardas estruturais que parseiam o YAML.

## O que está bloqueado, e em quem

**C06-A03, propriedade do grau — `BLOCKED_ON_C01`.**
`docs/comercial/c06/handoff_c01_grade_not_met.md`. Pedir
`minimum_fundamentacao_grade: 2` faz o job inteiro falhar sem snapshot, em
vez de rotular o resultado válido como `grade_requirement_status: not_met`.
Camada: `backend/worker.py:1220-1223`. C06 não edita esse arquivo.

**C06-A06 — composição: `WAITING_FOR_COMPONENTS`.**
C01, C02, C03 e C05 ainda estão em `8d66c797` com trabalho não commitado;
apenas C04 tem commit próprio. Nenhum HEAD estabilizado para incorporar.
Composição só depois de HEAD estabilizado conhecido, com ancestralidade
registrada, e o aceite reabre a cada mudança posterior.

**C06-A04 e C06-A05 — `BLOCKED_EXTERNAL_EVIDENCE`.**
Não há dado real autorizado, não há revisor externo independente, não há
autorização para submeter nada a nenhuma instituição. Protocolos preparados,
atos reais ausentes e nomeados. Simulação por agentes não substitui pessoa.

## Limites do ambiente local

`tests/c15_packaging/test_format_engines.py` falha localmente por `xlrd`
ausente no venv de desenvolvimento. É ambiental: o CI instala `.[dev]` com
`constraints/linux-py3.txt`. Não é regressão de C06 e não foi tocado.

## Regras que a retomada precisa preservar

- Não voltar `p04-harness` para `diagnose-base` para conseguir verde.
- Não relaxar tolerância depois de ver o número, não apagar teste, não
  aceitar qualquer estado, não rerodar até verde.
- Não escrever em arquivo de outro proprietário; pedir por handoff com
  payload mínimo, evidência e critério de aceite.
- SHA publicado **depois** do commit, em comentário/artefato, nunca dentro
  do próprio commit que ele descreve.
- `COMMERCIAL_RELEASE_READY` não se declara com requisito decisivo pendente.
  Sem merge, venda ou deploy automáticos.

---

## Onde a sessão parou (2026-09-12)

Limite de sessão interrompeu quatro agentes. O que ficou:

**Verificado e commitado:**
- R20-A fechado, com run vermelho real (34666595782) e a matriz de injeções
- Piso da suíte ampla como catraca: 700 → 800 (run be464a2 mediu 808, 0 falhas)
- NIST StRD com os `.dat` vendorizados, 11/11 sha256 conferidos por C06, e os
  44 pisos rederiváveis da regra escrita
- Metamórficos: tautologia substituída, morta por 7 de 8 mutantes
- Mutações comerciais: 21 detectores, veredito CONFIRMED
- Handoff de grau implementado por C01 e reexecutado por C06

**Correção de um erro meu:** uma revisão anterior deste handoff dizia que a
remediação de quatro documentos "não foi executada". Estava errado. Os agentes
morreram **depois** de escrever e **antes** de reportar, e eu li a ausência do
relatório como ausência do trabalho. Conferi arquivo por arquivo depois, e os
quatro estão corrigidos. Registro em
`defeitos_abertos_nos_documentos.md`, que também guarda a versão errada.

**Corrigido e conferido por mim, não só pelos agentes:**
- os 11 pisos novos do NIST reproduzem mecanicamente da regra escrita, e o de
  Filip é 15.270x mais largo que o erro observado (o oposto de ajustado)
- os 11 `.dat` vendorizados batem com os sha256 registrados
- o script institucional novo vai **vermelho** sob o mutante do verificador:
  57 citações substituídas por texto inventado -> `PASS=53 FAIL=31`, exit 1.
  O antigo dava `FAIL=0` sob a mesma mutação
- as duas alegações falsas que a própria remediação do `security_supply_chain`
  introduziu

**Ressalvas que seguem abertas:**
- `test_mutations_commercial.py`: o defeito 3 roda numa superfície que o
  produto nunca emite (`provenance.request_spec` é criado pelo teste). A frase
  falsa foi removida e a superfície rotulada, mas o detector segue sem
  superfície real
- oito dos dez defeitos comerciais não têm guarda do lado do produto
- **FIND-05** do inventário, o mais grave: `p02/test_a01_playwright.py`
  reporta verde quando o navegador não rodou. Arquivo de P02/C02 — handoff,
  não conserto meu

**Não executado, de escopo maior:**
- Composição C01-C05 na #20. Só C01 tem HEAD limpo (`1d40285`) e foi apenas
  **lido** em worktree descartável

## A regra que importa na retomada

Nada aqui autoriza declarar prontidão. Os três testes de
`testes_que_fixam_defeitos.md` ficam vermelhos quando alguém consertar o
defeito que eles fixam — isso é esperado, e a resposta é invertê-los na mesma
mudança, nunca apagá-los.
