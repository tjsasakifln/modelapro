# Defeitos abertos nos documentos de C06

Cada entregável de C06 passou por verificação adversarial com mutantes. Os
defeitos abaixo foram **provados**, e **não** foram corrigidos: a remediação
foi interrompida por limite de sessão.

Os documentos ficam publicados porque a análise de fundo foi conferida contra
fontes primárias e se sustenta. Mas nenhum deles deve ser lido como verificado
enquanto os itens abaixo estiverem abertos. Cada arquivo afetado carrega um
cabeçalho apontando para cá.

## `test_inventory.md` / `test_inventory.json` — remediação NÃO executada

1. **FIND-04 é falso no próprio SHA que o documento fixa.** Afirma que
   `verify_artifacts()` nunca executa no CI porque o job `acceptance` passaria
   só `--required-jobs` e `--results-json`. Em `65cb121` o job passa
   `--artifacts-dir evidence --expected-sha --min-wide-tests --p04-mode
   accept-candidate`. O documento descreve o commit **pai** (`8d66c79`) e
   estampa o resultado com o SHA do filho. Causa: `65cb121` entrou 01:58:30Z,
   a medição é de 02:01:23Z, e o agente recoletou os testes contra o HEAD novo
   mas nunca releu o workflow.
2. **Mesma causa, segunda alegação falsa.** Diz que `p04-harness` roda
   `--mode diagnose-base`, na tabela da seção 5, em OPT-02, em FIND-04 e
   textualmente no JSON. Em `65cb121` roda `accept-candidate`.
3. **Cascata.** "The gate checks job conclusions only" e "no CI path can turn a
   missing extension into a red build" são ambas falsas no SHA fixado.
4. **FIND-03 e FIND-08 estão RESOLVIDOS** (commit `be464a2`) e o documento
   ainda os lista como abertos.
5. **Cerca de doze node ids citados coletam ZERO** — são testes dentro de
   classes, escritos com dois segmentos. Um inventário cujas citações não rodam
   é o contrário de trilha auditável.
6. Citações de linha erradas (`aggregate_required.py:135-136` não é a checagem
   de extensões), um nome de teste inexistente
   (`test_skip_xfail_and_findings_are_caught`), e o remédio proposto em FIND-06
   não funciona: a contagem é dominada por arquivos **não rastreados**, então
   citar o SHA não a torna reproduzível.

FIND-04 **não** é lixo: é uma redescoberta independente do R20-A original, por
um agente que não sabia do conserto. Deve ser reenquadrado como
"redescoberto, já corrigido em `65cb121`", não apagado.

## `institution_profiles.md` / `real_case_matrix.md` — remediação NÃO executada

1. **O script de verificação não verifica o entregável.** Ele faz grep nos dois
   textos-fonte por strings **redigitadas à mão dentro do próprio script**; não
   lê as citações do documento. Prova: substituindo todos os 45 blocos citados
   por "TEXTO TOTALMENTE INVENTADO QUE NAO EXISTE EM FONTE NENHUMA", o script
   seguiu imprimindo `PASS=21 FAIL=0`, exit 0.
2. **A alegação metodológica central é logicamente falsa.** §1.1 diz que
   contagem igual a 1 demonstra ausência de redação empilhada superada. Não
   demonstra: uma gêmea revogada é uma string **diferente**, e também ocorre uma
   vez. Contraprova: o art. 6 caput vigente tem `grep -c` = 1, e a gêmea
   revogada também.
3. **O erro que o método deveria evitar aconteceu.** A ementa citada como
   "verbatim" é a **revogada** pré-2025. A vigente desde 1º/7/2025 — catorze
   meses antes da data do próprio documento — diz "operação de crédito
   imobiliário", e o documento nunca a cita, dentro de uma seção intitulada
   "Texto efetivamente consultado".
4. **A evidência não é durável.** Os dois textos-fonte e o script viviam só na
   scratchpad da sessão, fora do worktree. O documento diz ao revisor que a
   conferência "é reproduzível por qualquer revisor", e nada no repo permite
   reexecutá-la. *(Parcialmente endereçado: `docs/comercial/c06/sources/` e
   `scripts/comercial/` foram criados antes da interrupção — o conteúdo não foi
   verificado por C06.)*
5. **Cobertura menor que a alegada.** §1.1 diz "cada passagem transcrita foi
   conferida"; o script checa 7 strings do BCB e 4 da SUSEP de ~19 passagens
   citadas, duas delas fragmentos truncados que conferem prefixo.
6. **R2 exagera a seleção adversarial.** Afirma que RC-03, RC-06 e RC-09 são
   casos em que se espera **não** atingimento do critério. Mas os critérios
   congelados dessas linhas são comportamentais (o produto **declara**
   insuficiência amostral, **sinaliza** inadequação do método, **não funde** as
   populações) — e os autores esperam que o produto faça isso, logo o esperado é
   **atingimento**. Como congelada, a matriz tem **zero** linhas cujo critério
   se espera falhar. A garantia anti-cherry-picking é mais fraca que o
   declarado.
7. O gate de `NOT_RUN` é `-ge 12` contra matriz de 10 linhas (10 linhas + 2
   menções em prosa): acoplado a prosa incidental, e não verifica que **cada**
   linha carrega `NOT_RUN`.

As conclusões de fundo foram conferidas independentemente e estão **corretas**:
valor de avaliação como base operativa, e ausência de qualquer programa formal
de homologação de *software*. O defeito é o aparato de verificação, não a
substância.

## `reuse.json` / `security_supply_chain.md` — remediação executada, dois defeitos NOVOS

A remediação corrigiu os seis defeitos provados (a evidência de licença de
`wheel` e `setuptools` citava arquivos como inexistentes quando existem em
`dist-info/licenses/`; a contagem de transitivas era ~80 e é 67) e sobreviveu a
sete mutantes. Mas introduziu:

1. **Alegação falsa nova**: o cabeçalho reestampado diz "Nothing cited in this
   document moved between the two" (`a331606` → `be464a2`), o que `git diff`
   contradiz.
2. **Âncoras de linha da §4 não resolvem** no commit que o cabeçalho nomeia: a
   §4 diz "385 lines" e o workflow tem 400 em `be464a2`.

## O que isto significa para os aceites

`C06-A05` e `C06-A07` seguem `IMPLEMENTED_PARTIAL` / `BLOCKED_EXTERNAL_EVIDENCE`
e **não** sobem por causa destes documentos. O item A do inventário não está
concluído. Nada aqui muda `COMMERCIAL_RELEASE_READY`, que continua **não**.
