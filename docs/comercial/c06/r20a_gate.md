# R20-A — o aceite que não bloqueava

Frente MP-COM-20260912/C06. BASE_SHA `8d66c7973c659174e06d7223c9a9a8181e8eeabf`.
Destino: PR #20, branch `mp-pro-20260911/p04-referencia-consolidacao`.

## O achado

O job `p04-harness` executava `run.py`, o runner registrava `exit_code=1` em
`artifacts/p04/run.json`, e o job terminava verde. O aceite lia badges, não
resultados.

Não era um defeito, eram **três**, independentes entre si. Corrigir só o
primeiro deixaria o portão igualmente cego.

### D1 — o status do runner morria no pipe

O shell padrão do GitHub Actions para `run:` em Linux é `bash -e {0}`.
`-e` não inclui `pipefail`. Em

```
python scripts/pro_workflow/run.py ... | tee artifacts/p04/console.log
```

o código de saída observado é o do `tee`, sempre 0. O `run.py` podia falhar
inteiro sem que ninguém visse. O job `c16-harness` tinha o mesmo pipe e o
mesmo defeito; `wide-suite-linux` escapava apenas porque alguém lembrou de
escrever `set -o pipefail` naquele passo específico.

Correção: `defaults.run.shell: bash --noprofile --norc -eo pipefail {0}` em
**todos** os jobs Linux, inclusive no agregador. Não é por passo — por passo
é exatamente o que já falhou. O job Windows mantém `shell: pwsh` explícito em
cada passo e não é afetado; há teste que trava isso.

### D2 — o candidato era diagnosticado, não aceito

O job rodava `--mode diagnose-base`. Esse modo existe para descrever a versão
antiga: ele remove `P04_REQUIRE_EXTENSIONS` e **não propaga** o retorno da
suíte de extensões para `rc_all`. Ou seja, mesmo com o pipe corrigido, a
suíte estrita podia falhar e o job continuaria verde.

Correção: `--mode accept-candidate`, mais um passo separado que relê o
`run.json` gravado e falha se `mode != accept-candidate` ou `exit_code != 0`.
Esse passo é redundante com o agregador de propósito: ele falha no próprio
job, perto do defeito.

### D3 — o agregador era estruturalmente incapaz de ver o R20-A

`aggregate_required.py` lia apenas `toJSON(needs)`, isto é, conclusões de job.
Nunca abria um arquivo. O sintoma literal do R20-A — job retorna zero,
artefato registra `exit_code: 1` — era **invisível por construção**.

Correção: o job `acceptance` agora baixa todos os artefatos
(`actions/download-artifact@v4`, `merge-multiple: true`) e o agregador os lê:

| Artefato | O que é exigido |
|---|---|
| `run.json` | `exit_code == 0`, `mode == accept-candidate`, `skip_xfail_count == 0`, `findings == []`, todo `runs[].returncode == 0`, todo `runs[].passed > 0`, a suíte `extensions` presente, `sha` compatível com o candidato |
| `wide.junit.xml` | parseável, zero `failure`/`error`, contagem de testcases ≥ piso fixado **antes** do ensaio (`--min-wide-tests 700`) |
| `c16.json` | zero `reprovados`, zero `violacoes_a04_skip_xfail`, `aprovados > 0`, baldes disjuntos, `sha` compatível |

Ausente, vazio, ilegível ou de outro SHA = vermelho. Como o job `acceptance`
é `if: always()`, um produtor cancelado não entrega artefato — e isso agora
reprova, que é justamente o ponto.

`if-no-files-found` passou a `error` nos três uploads que podiam sumir calados
(`c15-linux-evidence`, `dist`, além dos que já estavam corretos). O terceiro
(`dist`) foi encontrado pelo próprio teste estrutural, não por leitura.

### Armadilha tratada: qual SHA comparar

Em evento `pull_request`, `github.sha` é o **commit de merge**; os artefatos
foram produzidos a partir do **head**. Comparar o errado deixaria o portão
vermelho pelo motivo errado — e a pressão seguinte seria afrouxar o assert,
que o contrato proíbe. O workflow usa
`${{ github.event.pull_request.head.sha || github.sha }}`, com teste que trava
essa escolha.

## Prova

O caso discriminante do C06-A01 não é "os testes passam". É:

> agregador invocado com **todos** os `needs` em `success` **e** um `run.json`
> com `exit_code: 1` precisa sair diferente de zero.

`tests/c15_packaging/test_ci_aggregator.py::test_main_is_red_when_all_jobs_are_green_but_evidence_records_failure`

Matriz de injeções obrigatórias, todas vermelhas:

- `exit_code: 1` com jobs verdes (o sintoma literal do R20-A)
- chave `exit_code` ausente (status perdido)
- `mode: diagnose-base` no candidato
- `run.json` ausente / vazio / não-parseável
- artefato de outro SHA (stale)
- `runs: []` (suíte nunca executou)
- `runs[].passed == 0`
- suíte `extensions` ausente da lista de runs
- `returncode != 0` dentro de um run
- `skip_xfail_count > 0`, `findings != []`
- JUnit com `failure`, JUnit truncado, JUnit com zero testcases, JUnit ilegível
- `c16.json` com `reprovados`, com violação de classificação, com zero
  aprovados, com baldes não disjuntos, de outro SHA

Guardas estruturais em `tests/c15_packaging/test_workflow_triggers.py`: o YAML
é parseado e se exige pipefail em efeito para **todo** passo Linux que contém
pipe, `accept-candidate` no job P04, ausência de `diagnose-base`, o
`download-artifact` com `merge-multiple`, as quatro flags do agregador, o head
SHA em PR, `if-no-files-found: error` em todo upload, e `pwsh` intacto no
Windows.

## O que esta prova NÃO é

CI verde depois desta mudança prova apenas que o portão mais estrito **não
reprova por engano**. Não prova que ele morde. Quem prova que ele morde é a
matriz de injeções acima, executada localmente e no CI. As duas afirmações são
separadas e não devem ser lidas uma pela outra.

A demonstração ainda ausente: um run real de `workflow_dispatch` em branch
descartável com um defeito injetado, produzindo uma URL de run vermelho. É a
diferença entre "testado unitariamente" e "demonstrado". Registrado como
pendência, não como feito.

## O portão mordendo num run real

Run de push **34666595782**, SHA `a331606`
(<https://github.com/tjsasakifln/modelapro/actions/runs/34666595782>),
conclusão `failure`. O job `Required jobs aggregator` imprimiu:

```
aggregator: evidence artifacts disagree with the job results:
  - p04 run.json: exit_code is 1, required 0
  - p04 run.json: run extensions returncode 1, required 0
  - p04 run.json: run extensions reports 1 failed cases
  - p04 run.json: 2 failure findings recorded, e.g.
      ['tests.pro_workflow.p04.test_candidate_extensions::test_minimum_fundamentacao_grade_canonical_field',
       'P04-EXT-minimum_grade']
  - wide.junit.xml: 1 testcases, floor is 700 (suite truncated or not run)
  - wide.junit.xml: 1 failed/errored testcases, e.g. ['::tests.c15_packaging.test_workflow_triggers']
```

Três coisas a registrar sobre esse run.

**1. A leitura de artefato funcionou de ponta a ponta.** O agregador baixou os
artefatos, abriu `run.json` e reportou `exit_code is 1` — exatamente o sintoma
que antes ficava verde. Não é mais simulação de laboratório.

**2. A distinção de `findings` está correta na prática.** O run registrou
quatro entradas em `findings`; o agregador acusou **duas**, e são as duas com
sinal de falha (o `nodeid` do teste que falhou e o `present: false` do
`P04-EXT-minimum_grade`). Os registros de sucesso `P04-EXT-formula` e
`P04-EXT-alias_conflict`, ambos `present: true`, não foram contados. Era
exatamente o defeito que o portão tinha antes de ser corrigido.

**3. O piso de testcases pegou uma suíte truncada sem ter sido planejado para
isso.** `wide.junit.xml: 1 testcases, floor is 700` aconteceu porque a suíte
ampla morreu na coleta, não porque testes falharam. Um agregador que só
olhasse "há falhas no XML?" veria um XML quase limpo. O piso fixado antes do
ensaio é o que separou "suíte passou" de "suíte não rodou".

Causas, que são duas e independentes:

- A coleta quebrou por culpa de C06: o teste estrutural importava `yaml`, e
  PyYAML não é dependência declarada deste projeto. Corrigido em `815251f`
  com um leitor próprio, sem tocar em dependências (C04 é o proprietário).
- `p04 run.json: exit_code is 1` **não** é C06 e não foi corrigido: é o
  defeito de grau descrito em `handoff_c01_grade_not_met.md`, que pertence a
  C01. O job `p04-harness` continua vermelho enquanto esse handoff não for
  implementado, e deve continuar.

Este run é a demonstração que faltava na seção anterior. Ele não substitui a
matriz de injeções: a matriz prova que cada modo de falha é detectado
isoladamente; o run prova que o caminho completo — upload, download,
leitura, comparação — funciona no ambiente real.
