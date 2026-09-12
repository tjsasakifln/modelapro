# Registro de verificação adversarial de C06

**Este arquivo já disse o contrário. A correção está registrada, não apagada.**

Uma revisão anterior deste documento afirmava que a remediação de quatro
entregáveis "não foi executada" e estampava os quatro arquivos como não
verificados. Isso estava **errado**. Os agentes de remediação morreram por
limite de sessão **depois** de escrever os arquivos e **antes** de reportar, e
eu li a ausência do relatório como ausência do trabalho. Conferi arquivo por
arquivo depois.

O erro era meu, e é do tipo que este documento existe para pegar: concluir
sobre um artefato a partir de um relatório em vez de abrir o artefato.

## O que a verificação adversarial encontrou, e o que aconteceu depois

Seis entregáveis, cada um verificado por um agente instruído a refutá-lo, com
mutantes empíricos. Quatro voltaram `WEAK` com defeitos **provados**.

### `test_metamorphic_reference.py` — corrigido e reverificado

Defeito provado: **tautologia**. A asserção era
`arithmetic/geometric == exp(sigma2/2)`, com o próprio teste definindo
`geometric = exp(point)` e `arithmetic = exp(point + sigma2/2)` — a identidade
`exp(a+b)/exp(a) == exp(b)`, verdadeira para qualquer `a` e qualquer `b`. Um
mutante com `sigma2 = 100*sse/df` deixava o teste verde.

Mais: os testes de quase-singularidade usavam `b = x*(1+delta)`, que é múltiplo
escalar **exato** — posto deficiente exato, não quase-singularidade — e a
propriedade titulada é **falsa** do oracle (designs com `cond` até 2.2e13 são
aceitos).

Corrigido. A reverificação: morto por 7 de 8 mutantes numéricos, inclusive os
4 que deixavam a versão antiga verde. Veredito `CONFIRMED`.

### `test_nist_strd.py` / `PROVENANCE.md` — corrigido, conferido por mim

Defeitos provados: a alegação "Every single failure was on `B0`" era **falsa**
(medi eu mesmo: 6 datasets, 13 falhas, 7 fora do `B0`), e onze asserções de
Filip eram **inertes** (`sd_rel_floor >= 1.0` reduzia o teste a
`isfinite() and >= 0`, e a previsão "no reproducible significant digit" era
empiricamente falsa — o oracle reproduz a 8.5-10.1 dígitos).

Corrigido. Conferi os dois pontos de risco eu mesmo:
- os 11 pisos novos **reproduzem mecanicamente** da regra escrita, e o de Filip
  é 15.270× mais largo que o erro observado — o oposto de número ajustado;
- os `.dat` foram vendorizados e os 11 sha256 batem (11/11), então os hashes
  deixaram de ser circulares.

### `institution_profiles.md` / `real_case_matrix.md` — corrigido, conferido por mim

Defeito provado mais grave: **o script de verificação não verificava o
entregável**. Fazia grep nos textos-fonte por strings redigitadas dentro do
próprio script, sem ler as citações do documento. Substituindo todos os blocos
citados por texto inventado, ele seguia imprimindo `PASS=21 FAIL=0`.

Também: a alegação metodológica de §1.1 era logicamente falsa (contagem 1 não
demonstra ausência de redação empilhada — a gêmea revogada é outra string e
também ocorre uma vez), e a ementa citada como *verbatim* era a **revogada**
pré-2025 — exatamente a armadilha que o documento dizia ter evitado.

Corrigido. Apliquei o mutante do verificador ao script novo
(`scripts/comercial/aceite/verify_c06.py`, 459 linhas, que extrai as citações
**do documento**): 57 passagens substituídas por texto inventado →
`PASS=53 FAIL=31`, exit 1. O script antigo dava `FAIL=0` sob a mesma mutação.
A ementa vigente agora é citada, com as duas redações empilhadas explicadas.

### `reuse.json` / `security_supply_chain.md` — corrigido, e dois defeitos novos que a própria correção criou

Os seis defeitos provados foram corrigidos (a evidência de licença de `wheel` e
`setuptools` citava arquivos como inexistentes quando existem em
`dist-info/licenses/`; as transitivas eram 67, não "~80"). Mas a correção
introduziu dois novos, pegos pela reverificação:

1. "Nothing cited in this document moved between the two" — falso: dois
   arquivos citados moveram (`c15-ci.yml`, `aggregate_required.py`).
2. As âncoras de linha da §4 não resolviam no commit nomeado (dizia 385 linhas;
   o workflow tem 409).

Ambos corrigidos por mim.

### `test_inventory.md` / `.json` — corrigido

Defeito provado: **FIND-04 era falso no próprio SHA que o documento fixava**.
Afirmava que o agregador nunca lia artefatos no CI — descrevendo o commit
**pai** e estampando o resultado com o SHA do filho. Causa: `65cb121` entrou
01:58:30Z, a medição é de 02:01:23Z, e o agente recoletou os testes contra o
HEAD novo sem reler o workflow.

Corrigido, e bem: FIND-04 está marcado `RESOLVED in 65cb121` com a explicação
do erro, **preservado em vez de apagado**, e reenquadrado como redescoberta
independente do R20-A por um agente que não sabia do conserto. FIND-03 e
FIND-08 também `RESOLVED`. O remédio quebrado de FIND-06 (citar o SHA junto da
contagem) foi substituído por um que funciona.

## Dois vermelhos reais no CI, nenhum deles conserto por tolerância

O run **34667826006** (`c9ab4dc`) foi o primeiro a rodar as duas checagens
novas. Três coisas saíram vermelhas, e classificá-las importa mais que
consertá-las rápido.

### 1. `test_nist_strd::test_certified_residual_standard_deviation_and_r_squared[Pontius]` — ABERTO, e não vou afrouxar

```
Pontius residual sd: certified=0.000205177424076185
                      observed=0.00020517742407622438
rel_err=1.919e-13 (12.72 correct digits)
pre-registered floor=1.845e-13 (kappa_eq=1.845e+01)
```

Passa na minha máquina, falha no runner do CI. Excede o piso por fator **1.04**.

Subir o piso para 2e-13 faria o teste passar e seria exatamente o que o
contrato proíbe: ajustar tolerância depois de ver o número. Não fiz, e não
deve ser feito.

**Diagnóstico corrigido — medi, e minha primeira explicação estava errada.**

Eu escrevi que o defeito era na **regra**: que `proj_rel_floor` usa
`A = kappa_eq` para uma quantidade que vem de `sse/(n-p)`, soma de quadrados,
e que a correção seria derivar o fator de amplificação certo. Medi a hipótese
antes de mandar alguém derivá-la, e ela **não se sustenta**:

| | piso atual | aqui | regra candidata `A = k + k²ρ` | piso novo |
|---|---|---|---|---|
| Pontius | 1.845e-13 | **8.19e-15** | 1.85e+01 | **1.848e-13** |

A regra candidata move o piso de Pontius em **0,2 %**. O CI observou
**1.919e-13**. Corrigir a regra não fecharia a distância nem de longe.

O número que importa é outro: **aqui o erro é 8.19e-15, no runner do CI é
1.919e-13 — 23× maior, para o mesmo código determinístico e os mesmos bytes de
entrada.** O piso tem 22× de margem na minha máquina e é estourado na deles.

Então o problema não é a tolerância nem a regra: é **variância de plataforma**.
Ordem de redução diferente no BLAS/LAPACK, build de `numpy` diferente, SIMD
diferente. Uma tolerância derivada só do condicionamento não modela isso, e
nenhuma das duas regras modela.

O que precisa ser decidido (e **não** decidi, porque decidir sem medir nas duas
plataformas seria o mesmo erro de novo):

- medir o erro nas duas plataformas para os onze conjuntos, não só Pontius, e
  ver se a dispersão é sistemática ou só neste;
- se for sistemática, a tolerância precisa de um termo de plataforma
  **declarado** — e declarado antes de olhar o resultado, não ajustado a ele;
- registrar a versão e o build de `numpy`/BLAS junto do resultado, que hoje não
  são registrados e por isso o run não é reproduzível entre máquinas.

Enquanto isso o teste fica **vermelho**, e o piso fica onde está. Não subi, e o
`git diff` de `datasets.py` prova que nenhum literal se moveu.

Registro também a forma do meu erro: eu produzi uma explicação plausível,
escrevi que o conserto era "derivar o fator de amplificação correto", e só
depois medi. A medição derrubou a explicação em uma linha. A explicação errada
tinha custo real — mandava a próxima pessoa fazer análise numérica que
provadamente não ajuda.

### 2. `p02/test_a01_playwright::test_a01_playwright_real_path_or_record_unavailability` — HANDOFF a C02

```
AssertionError: subject area field missing; body=Trabalho ... 1. Preparação da amostra ...
```

O navegador **rodou** e a tela carregou; o campo de área do avaliando não foi
encontrado. É o mesmo arquivo do **FIND-05** do inventário — o teste que antes
reportava verde quando o fluxo não rodava. Agora falha de verdade, o que é uma
melhora no sinal e uma piora no estado.

C02 tem quatro commits e trabalho não commitado mexendo no frontend, o que é a
explicação provável. Arquivo de P02/C02: **não é conserto meu**, é pedido com
evidência. Registrado aqui porque bloqueia a suíte ampla obrigatória e quem
vir o vermelho precisa saber de quem é.

### 3. `install-smoke.junit.xml: artifact absent` — era meu, plumbing, consertado

Não era defeito de produto. Eu havia trocado `pip install -e ".[dev]"` por
`pip install pytest` no passo do smoke, com o raciocínio de que o job
"clean venv" não deveria instalar o produto em editable. O raciocínio era bom e
o efeito foi quebrar: `tests/conftest.py` importa `matplotlib` no topo, então o
pytest nem carrega o conftest — exit 4, nenhum junit escrito, e o upload com
`if-no-files-found: error` derruba o job. O agregador então reportou o artefato
ausente, corretamente.

Restaurado, com o motivo escrito no próprio passo. A garantia de venv limpo
vive no venv que o próprio teste constrói em `$HOME`, que esse install não
toca.

Vale registrar a forma do erro: uma limpeza que parecia obviamente correta
quebrou um gate, e o gate pegou. Foi a checagem nova de artefato — adicionada
duas horas antes — que tornou a quebra visível em vez de silenciosa.

## Ressalvas que seguem abertas

Estas **não** foram corrigidas — a remediação delas nunca foi lançada:

- **`test_mutations_commercial.py`, defeito 3 roda numa superfície que o
  produto nunca emite.** `provenance.request_spec` é criado pelo próprio teste
  (`snap.setdefault("provenance", {})["request_spec"] = spec`), e o S01 real
  traz `evaluation_policy.method == 'none'` — o estado mutado. *(Parcialmente
  endereçado: a frase falsa "injected into a copy of a real snapshot" foi
  removida e a superfície está rotulada como `TEST-AUTHORED`; o detector segue
  sem superfície real.)*
- **Oito dos dez defeitos comerciais não têm guarda do lado do produto.** Os
  detectores são de teste, escritos no mesmo arquivo que as mutações — provam
  que o validador funciona, não que o produto resiste. Divulgado no docstring
  do módulo, por defeito.
- **FIND-01, FIND-02, FIND-05, FIND-06, FIND-07** do inventário seguem `OPEN`.
  O mais grave para o aceite é **FIND-05**:
  `tests/pro_workflow/p02/test_a01_playwright.py` **reporta verde quando o
  fluxo de navegador não rodou** — escreve um log `BLOCKED` e retorna. Por não
  ser skip nem xfail, é invisível ao relatório de skips e ao agregador. É
  arquivo de P02/C02: handoff, não conserto meu.

## O que isto não muda

Nenhum aceite sobe por causa destas correções. `COMMERCIAL_RELEASE_READY`
continua **não**. A verificação adversarial por agentes **não é** revisão
técnica independente e não conta como `INDEPENDENT_TECHNICAL_REVIEW`.
