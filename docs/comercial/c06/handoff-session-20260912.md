# C06 — continuidade em nova sessão

## Topo vigente — 2026-09-13, B tecnicamente encerrada

**ENCERRAR técnico.** PR #20 HEAD **`263ec1dcbaa7850459453215faf1066da402cb43`**,
base `6d54f902b85a5a37bfbf154d39f74cf854ff9b2b`, draft, `auto_merge=null`.
`COMMERCIAL_RELEASE_READY=false`.

| | Resultado | Runs |
|---|---|---|
| A Origem/metadados | PASS | filtro pós-Analysis; METADATA físico só da fonte |
| B A3 operacional + B entre árvores | PASS | Windows A3 [34733840472](https://github.com/tjsasakifln/modelapro/actions/runs/34733840472)/1; A3→B [34734531128](https://github.com/tjsasakifln/modelapro/actions/runs/34734531128); B [34735590438](https://github.com/tjsasakifln/modelapro/actions/runs/34735590438)/1 |
| C C15 PR e push | PASS | [34735590433](https://github.com/tjsasakifln/modelapro/actions/runs/34735590433) / [34735588458](https://github.com/tjsasakifln/modelapro/actions/runs/34735588458); 1832/1832; 1 skip wheel-smoke |
| D Mercado/custo/documentos | PASS na suíte C15 desta SHA | assinatura TESTE; C05 autoridade |
| E Identidades | PASS | merge de teste `7b3b046` não é stale; checkout limpo |

- A3 `271b08ddf412ceb733d98c3c6281b145289f5b18`, instalador `73b768cc39eb19f811d4c8659aac8b6b70dc14aceb13063bb4129a11ef196ffc`
- B instalador `695709e264d166310610a24c3bc6bcf474868421f06be76f8b340d6da565c729`
- Obrigações A3 1.822 / B 1.832. UI/manual profissionais permanecem em B.
- A3 nunca substitui B. Sem merge/deploy/venda/assinatura real.

## Encerramento solicitado — 2026-09-13, 00:43 UTC (12/09, 21:43 BRT)

**Este é o checkpoint vigente.** O usuário pediu handoff para continuidade posterior
e encerramento. Agentes Windows e revisão foram interrompidos; nenhum novo ciclo,
push, merge remoto ou workflow foi iniciado no encerramento. A meta permanece
incompleta e não foi marcada como concluída. As seções seguintes são históricas,
mesmo quando dizem que uma reconstrução está em execução.

### Git e worktrees no encerramento

- Composição `/home/tjsasakifln/code/modela-pro-p04`, branch
  `mp-pro-20260911/p04-referencia-consolidacao`: HEAD técnico/documental antes
  deste handoff `55bdbb295ca599b981a1f2be69c524db5966e54b`, árvore
  `23c9d4d64e161761155031a1f366d60fe71c913c`, limpo. O commit deste handoff
  aparecerá imediatamente depois; consultar `git log -3` na retomada.
- A3 operacional `/home/tjsasakifln/code/modelapro-c06-operational-a3`, branch
  `c06-operational-a3-20260912`: HEAD **`a884e62eb431adf47f670611a3063e6e59252bc2`**,
  árvore **`3a9bc7fd5f1c490e11399359eb0d98973be36131`**, limpo e ancestral da
  composição. A3 tem 1.820 obrigações; B tem 1.830, com diferença real na UI
  profissional/manual. Não substituir B por A3.
- Agente Windows `/home/tjsasakifln/code/modelapro-c06-distribution`, HEAD
  **`24f56c08c90661f058b58d00b9e35c5ec5ef8a77`**, limpo na inspeção de encerramento.
  Todos os commits entregues estão integrados em A3 e B. Nenhum patch pendente
  foi encontrado nesse worktree.
- PR #20 consultada novamente: **open**, `merged=false`, `auto_merge=null`,
  HEAD remoto **`df6b7b786f91b7a545d4c925d954cbedb9fbdf17`**, base
  `6d54f902b85a5a37bfbf154d39f74cf854ff9b2b`. Nenhum push nesta etapa da sessão.
  O topo remoto ainda descreve A2; os novos commits/provas estão apenas locais.
- Preservar `/home/tjsasakifln/code/modela-pro` (trabalho C11 do usuário), sem
  limpeza, reset ou uso como checkout de implementação C06.

### Primeira tarefa da retomada: fechar coleta automática de metadados

A reconstrução real do archive A3 `a884e62` terminou em ~134,845 s, em
`/mnt/c/Users/tj_sa/AppData/Local/Temp/modelapro-c06-a3sourcebound.14EXoN`.
O archive tem 7.700.480 bytes, SHA-256
`6df261f778ab0b0e2cec764e6387272b250f06b19b6bf206db6e4319b41f2f80`.
A conferência física **reprovou antes do ciclo de uso**:

- Dados/templates/UI e módulos próprios vieram da fonte correta; o template
  `modules/templates/report.html` agora coincide com a fonte (SHA `1678a4e...`).
- `METADATA` gerado da fonte está correto, SHA-256
  `48ff020bef09548b27090b48214f9049b1bd0ab3387430beed7653d91ba1bab9`.
- Porém, `Analysis-00.toc` registra **sete arquivos dist-info antigos** coletados
  automaticamente do ambiente `modelapro-c06-fixedsim.mTYdlZ/install`:
  `direct_url.json`, `top_level.txt`, `REQUESTED`, `entry_points.txt`, `INSTALLER`,
  `WHEEL`, `RECORD`. O hook de metadados do PyInstaller os descobriu a partir das
  chamadas literais a `importlib.metadata.version("modelapro")`.
- Evidência original: `proof/source-origin-verification.json` (`FAILED`),
  `proof/pyinstaller.log`, `work/modelapro/Analysis-00.toc`. Hashes e resumo em
  [evidence-local-windows-a884e62.json](evidence-local-windows-a884e62.json).
  Não houve initial/upgrade/restore desta reconstrução. Não é prova hospedada
  nem instalador Inno; é preflight local onedir em Windows 11.

**Correção ainda não implementada:** após `Analysis` no spec, remover qualquer
entrada dist-info própria reintroduzida pelos hooks e reinserir somente o
`METADATA` da fonte já validado. Testar o spec com um Analysis que injeta esses
arquivos antigos. O agente chegou a propor também construir dinamicamente o
nome da distribuição para evitar descoberta do hook; avaliar se isso é necessário.
Preferir que a garantia esteja no filtro final central, preservando a consulta
normal de versão do runtime quando possível. Nenhuma dessas mudanças foi validada.
Não apagar arquivos manualmente do bundle para transformar esta falha em sucesso.

Os patches anteriores `9151565`, `5434b27`, `24f56c0` **já estão integrados**:
helper carregado por caminho explícito, dados próprios da fonte, hidden imports
por enumeração da fonte, `pathex` root+scripts e metadados mínimos gerados do
`pyproject.toml`. A revisão independente aprovou essas origens declaradas com
64/64 testes, mas ressalvou que só o freeze provaria a resolução física; a falha
automática acima é a nova pendência, não um sucesso desses testes estendido ao pacote.

### Sequência de continuidade e aceites restantes

1. Corrigir/testar a coleta final de metadados no worktree isolado Windows;
   revisar e integrar o commit imutável em A3 e B. Preservar ancestralidade por
   merge de A3 na composição; congelar inventários se houver novas obrigações.
2. Gerar novo archive de A3 limpa e reconstruir. Conferir todos os arquivos,
   origem real de dados/módulos, identidade e metadados. Executar `--check-pdf`,
   initial com perfil vazio, upgrade da mesma árvore, restore e encerramento de
   todos os filhos/portas antes de fallback. O runtime deve funcionar sem
   overrides externos `MODELA_API_TIMEOUT`, `MODELA_API_URL`, `MP_CODE_SHA`,
   `PYTHONPATH`; o launcher fornece suas configurações de produto.
3. Só após essa prova, publicar A3 por fast-forward na mesma #20. Reconsultar
   HEAD/base/estado antes do push. Exigir Windows hospedado SUCCESS operacional,
   explicitamente `OPERATIONAL_SAME_TREE_ONLY`; isso ainda não fecha migração.
4. Publicar B, que contém mudanças reais de UI/manual. O workflow Windows de PR
   seleciona automaticamente a última candidata bem-sucedida da mesma PR/branch.
   Conferir que escolheu a A3 correta; usar `workflow_dispatch` com
   `previous_run_id`/`previous_run_attempt=1` somente se essa seleção não ocorrer.
5. Exigir B Windows entre árvores e SHAs distintos, novo job/replay=false,
   preservação semântica após validar vínculos, documentos/save/reopen/backup/
   restore/uninstall/ACL/filhos e inventário completo. Diferenciar Windows 11
   local de `windows-latest` hospedado e Inno real.
6. Exigir C15 PR **e push** da candidata final: coleta exata, JUnit terminal,
   único skip permitido de wheel-smoke coberto pelo job próprio, identidades
   PR HEAD/base/merge testado/tree/run/attempt, checkout limpo e hashes dos bytes
   de todos os namespaces. Não rerodar apenas porque a observação expirou.
7. Atualizar matriz, delivery, evidências, handoff e topo da PR, preservando
   históricos e os dez estados. Sem main/#17 merge, auto-merge, deploy, venda,
   ato profissional, assinatura real ou transmissão institucional.

### Provas que não devem ser refeitas sem motivo

- C15 A2 PR **34721474693** e push **34721472670**: SUCCESS, cada um
  1.755 passed/1 skipped, 1.756 obrigações; 50 hashes em 7 namespaces por run
  conferidos, checkout limpo. Windows A2 **34721474609**: FAILURE. São históricos.
- Suíte ampla local `661fc82`: exit1, 1.822 passed/5 failed/1 skipped,
  1.828 obrigações em 1.672,96 s, checkout limpo, 36 arquivos conferidos.
  As cinco causas já foram corrigidas e verificadas em testes focados; ver
  [registro completo](evidence-local-wide-661fc82.json). Não repetir essa suíte
  intermediária só por falhas já resolvidas; falta o CI da candidata final.
- Navegador final de mercado+custo em `71d549a`: **2/2 PASS**, exit0,
  140,917 s, 12 arquivos conferidos, sem credenciais. Artefatos em
  `/tmp/c06-token-final-71d549a-evidence/`, JUnit
  `/tmp/c06-token-final-71d549a.xml`; ver
  [registro](evidence-local-browser-71d549a.json). Fluxos incluem criação,
  revisão, assinatura TESTE, exportação, save e reopen.
- Última coorte packaging+launcher: **64/64 PASS**, exit0, 8,87 s,
  `/tmp/c06-first-party-source-integrated2.{log,xml}`; revisão independente
  também 64/64 e spec 1/1. Um comando anterior terminou exit4 por caminho
  inexistente `test_launcher.py`, sem testes executados; foi corrigido para
  `test_launcher_command.py`, sem esconder falha de produto.
- Consumidores de criação/segurança/launcher: **99 PASS**; revisão independente
  de concorrência: 50/50 corridas com um criador com token e um replay sem token.
  O token foi preservado e `created=True` é autoritativo antes do cache. Não
  reintroduzir a heurística que transformava os dois concorrentes em replay.
- Documentos/arbitramento/UI/superfícies: 52 PASS; UI/gate 78 PASS; Windows+
  produtor 87 PASS (um worker real já coberto na coorte de 52); ver
  [evidência documental](evidence-local-documentary-20260912.json).
- A3 `96975eb` anterior: cálculo succeeded, geração recusou template antigo;
  2.811 arquivos/369.886.906 bytes conferidos; shutdown passou com dois filhos
  e portas fechadas. Preservado em [registro](evidence-local-windows-96975eb.json).
- Inventários exatos A3 1.820 e B 1.830 passaram após `5434b27`; `24f56c0`
  alterou testes existentes sem adicionar nodeids. Lint aprovado em `71d549a`;
  rodar lint final apenas na candidata pronta. Fronteiras externas PASS89/FAIL0.

### Ambiente e agentes para retomar

Venv travado: `/tmp/modelapro-c06-final-venv`; usar seu Python com
`PYTHONPATH=.:scripts` **e cwd do worktree correto** (editable aponta para a
composição). Navegador:
`LD_LIBRARY_PATH=/tmp/modelapro-c06-browser-libs/usr/lib/x86_64-linux-gnu`.
Não usar `python` genérico (ausente); usar `python3` ou Python do venv.

Agentes existentes: `windows` é dono do empacotamento; `numeric_review` é
revisor somente leitura; `professional_ui` concluiu os dois navegadores e está
ocioso; `document_conformance` concluiu os produtores e está ocioso. Reusar
somente quando houver trabalho independente útil. Root continua único publicador.
As verificações sintéticas e assinatura TESTE não substituem casos reais,
revisão profissional independente ou aceite institucional. Os dez estados de
[delivery.json](delivery.json) continuam pendentes conforme suas provas;
`COMMERCIAL_RELEASE_READY=false`.

---

## Atualização da retomada — 2026-09-13, 00:19 UTC

Esta atualização prevalece sobre as pendências históricas abaixo. O trabalho está
em execução; não é encerramento, aceite final nem liberação comercial.

- Composição limpa em `71d549a9b3e6ab0dc444a871533f778ed1f2a88a`; A3 limpa em
  `/home/tjsasakifln/code/modelapro-c06-operational-a3`,
  `96975ebb8e181e72e63e4729b89b0e1cfdf83928`, árvore
  `943e300b6492d5e40ac5465afba145f5a4346bc0`. A3 é ancestral da composição.
- Os patches de P02/cobertura e os produtores documentais, arbitramento,
  interface profissional e correções Windows já foram integrados. Não reaplicar
  os checkpoints históricos abaixo.
- Última candidata remota observada: A2 `df6b7b7`, C15 PR `34721474693` e push
  `34721472670` SUCCESS; Windows `34721474609` FAILURE. Os registros próprios
  preservam identidade, coleta e bytes; não aprovam os descendentes locais.
- Inventário A3: 1.820 obrigações; composição: 1.830. Navegador mercado+custo
  após a última correção passou 2/2 com 12 arquivos conferidos; lint e inventário
  passaram. Ver [matriz atual](integration-matrix.md),
  [prova do navegador](evidence-local-browser-71d549a.json) e
  [suíte ampla local e cinco correções](evidence-local-wide-661fc82.json).
- O preflight Windows da A3 em
  `/mnt/c/Users/tj_sa/AppData/Local/Temp/modelapro-c06-a3tokenfix.DXILG5`
  terminou `initial=FAILED`: cálculo concluído, mas geração documental recusou
  template antigo coletado do pacote instalado, distinto do checkout fonte.
  Os 2.811 arquivos (369.886.906 bytes) foram conferidos; encerramento dos filhos
  e portas passou sem fallback. Ver
  [evidência local da falha](evidence-local-windows-96975eb.json).
  Corrigir seleção de dados no spec, revisar a origem de imports e reconstruir.
  Esta prova local de onedir em Windows 11 não executa Inno Setup nem workflow
  hospedado. Exigir término de initial/upgrade da mesma árvore/restore.
- Após a prova local, publicar A3 na mesma #20, aguardar Windows hospedado
  operacional aprovado, e então publicar a composição B. Exigir atualização
  entre árvores distintas, novo job sem replay, artefatos vinculados e C15 PR/push
  final aprovado. Atualizar matriz, delivery e topo da #20 com os resultados reais.
- Permanecem os limites originais: sem merge, deploy, venda, assinatura real,
  submissão institucional ou aprovação profissional. Os dez estados continuam
  separados em [delivery.json](delivery.json); `COMMERCIAL_RELEASE_READY=false`.

### Correção de origem do pacote — checkpoint posterior

A3 atual limpa: `a884e62eb431adf47f670611a3063e6e59252bc2`, árvore
`3a9bc7fd5f1c490e11399359eb0d98973be36131`. A composição incorpora essa A3
por merge em `56ca08851cbea9de0b0ac5c2cda2dc4adc593449`.
Os patches `9151565`, `5434b27` e `24f56c0` vinculam dados, helper, módulos
próprios e metadados de runtime à fonte explícita. A revisão independente não
manteve achados materiais; [64 testes passaram na composição](evidence-local-packaging-source.json).
Isso não substitui o freeze real. Novo archive em
`/mnt/c/Users/tj_sa/AppData/Local/Temp/modelapro-c06-a3sourcebound.14EXoN`,
7.700.480 bytes, SHA-256
`6df261f778ab0b0e2cec764e6387272b250f06b19b6bf206db6e4319b41f2f80`.
Reconstrução autorizada após revisão; aguardar ciclo inicial/upgrade/restore e
conferência física. Nenhum novo push foi feito neste checkpoint.

## Checkpoint histórico original — preservado

Checkpoint observado em **2026-09-12, 20:30 UTC**. A sessão foi encerrada a pedido
do usuário após disponibilizar este handoff. A meta técnica permanece incompleta;
este documento não é aceite de produto nem liberação comercial.

## Retome aqui

1. Trabalhe em `/home/tjsasakifln/code/modela-pro-p04`, branch
   `mp-pro-20260911/p04-referencia-consolidacao`, na mesma
   [PR #20](https://github.com/tjsasakifln/modelapro/pull/20). Releia este arquivo,
   [composição e propriedade](composition-20260912.md),
   [matriz de aceites](integration-matrix.md) e os handoffs/aceites C01–C06 ao
   tocar seus contratos. Consulte HEADs, comentários e runs remotos novamente.
   Critério: registrar estado remoto/local e preservar avanços, sem reset.
2. Recolha os checkpoints isolados da seção seguinte. Integre somente as três
   correções P02 ainda ausentes; valide o patch de cobertura antes de commitá-lo.
   Critério: consumidores reais e testes correspondentes passam na composição,
   sem duplicar os commits já incorporados.
3. Investigue o Windows run **34716312452**, agora FAILURE. C15 **34716312436**
   ainda executava a suíte ampla, mas já tinha lint FAILURE, corrigido localmente.
   Critério: causas e artefatos de falha registrados; nenhuma execução antiga
   convertida em aprovação da candidata nova.
4. Conclua os pontos internos abaixo e publique uma coorte coerente na #20.
   Execute os aceites sobre seus artefatos, distinguindo PR HEAD de merge testado.
   Critério: matriz requisito→implementação→teste→run→artefato preenchida com
   identidade e bytes da candidata, incluindo Windows instalado.
5. Atualize o topo da #20 com HEAD/runs novos e os dez estados separados,
   preservando históricos. Critério: ausência externa precisamente registrada,
   sem handoff sem consumidor e sem declarar liberação comercial indevida.

## Git e publicação

O worktree de composição estava limpo antes da escrita deste handoff.
HEAD técnico local: `cff68a2aa164b2fb39cb035568d7979116799263`.
HEAD publicado da #20: `c60fbebd11816e358756a50ca8a09b74a815aa34`.
Na consulta de encerramento, PR **open**, `merged=false`, `auto_merge=null`.
Base: `mp-20260911/integracao-final`,
`6d54f902b85a5a37bfbf154d39f74cf854ff9b2b`; é também o merge-base observado.
Main observada anteriormente: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`.

Todos os cinco produtores estão na ancestralidade real do HEAD técnico:

| Frente | PR | HEAD incorporado |
|---|---|---|
| C01 | #23 | `3910a20fa34f4b2b57e58dd2063cb7ec09c55b64` |
| C02 | #22 | `f0d8eaa4056e9197f90102d888707755c300b00b` |
| C03 | #26 | `c9ccb43fbb2ba65a6f2082cdb8347134d45bd310` |
| C04 | #25 | `fbb9c9327e320ce385183d4988b731c4ef3e7996` |
| C05 | #24 | `a877c14fca2f4ff175ee5419d25f914f044e40a4` |

Não reintegrar P01–P04 como módulos novos. C06 assumiu os arquivos transversais
para fechamento; não alterar branches produtoras. Commits locais após o último
push, em ordem: `d0b8b36`, `999680d`, `c27b6e8`, `9c1c484`, `4f9b799`,
`1463e5f`, `cff68a2`. Consulte `git log c60fbeb..HEAD` para os objetos completos.
O handoff é local; não foi feito novo push para encerrá-lo.

**Preservar** `/home/tjsasakifln/code/modela-pro`: contém trabalho C11 do usuário,
fora desta composição. Não limpar nem usar como checkout de implementação C06.

## Checkpoints dos agentes — não perder nem reaplicar

### P02 / qualification

Worktree `/home/tjsasakifln/code/modelapro-c06-browser`, limpo, HEAD
`620a2e26cb9d2b721e83407e885f06bda1b63ee8`.
Ainda não integrados ao root: **`6a3136d`, `c0459ba`, `620a2e2`**, nessa ordem.
Único arquivo restante: `tests/pro_workflow/p02/test_a01_playwright.py`.
Já integrados: equivalentes de `2f63299`, `7eeaa2b`, `fd85289` e receipt
`2567834`. **Não reaplicar o squash `0e1726f`**, pois duplicaria essas mudanças.

O teste final real CSV+XLSX passou: **1 passed / 125,39 s**, cada formato com
novo job_id, estado terminal e download JSON do job exato, ponto 735000.
Receipt+C05: **153 passed / 18,60 s** na coorte de validação do agente.
Isso ainda requer confirmação após integração no HEAD final.
Bug de produto observado e **não corrigido**: banner de arquivo/resultado antigo
pode persistir embora o JSON baixado tenha o job_id corrente. Corrigir a origem
do estado da UI, sem retirar a verificação por identidade dos bytes.
Validação auxiliar em `/tmp/modelapro-c06-p02-verify.oI3MTo`, HEAD `5d6637d`,
contém `artifacts/` não versionado; não confundir com patch de produto.

### Cobertura externa / numeric

Worktree `/home/tjsasakifln/code/modelapro-c06-commercial-guards-fix`, HEAD
`cff68a2aa164b2fb39cb035568d7979116799263`, **sem commit novo**. Dirty apenas:

- `frontend/components/professional.py` (função `present_independent_validation_coverage`);
- `tests/comercial/test_c06_commercial_surfaces.py`;
- `tests/pro_workflow/p04/test_mutations_commercial.py`.

Patch de segurança em `/tmp/modelapro-c06-commercial-guards-fix.patch`, SHA-256
`5614538d1be9ccbb94b819baed9e98ac3eecae995aee34c487a9656b67dd267a`.
Use o worktree como fonte e confira o hash antes de depender da cópia temporária.

Defeito: `requested and statistical` promovia estatística in-sample a cobertura
externa. A correção exige o contrato real `validation.statistical.procedure`
(cobertura, métricas, partição/predições), não a intenção do request. O detector
agora usa `r2`/`r2_adjusted` realmente emitidos; SBOM parte da distribuição
`pypdf` instalada/versionada e altera somente a licença, em vez de inventar
pacote e metadados completos.
Red inicial: 2 failed / 1 passed. Primeira correção: 3 passed / 8 deselected;
coorte C02+superfícies+histórico: **51 passed / 80,73 s**. **Após esses resultados**
houve refinamento exigindo `n_reserved`/`n_covered` positivos, métricas, folds e
predições: passou apenas py_compile/diff-check, **ainda não foi testado**.
Próximo comando: `pytest -q tests/comercial/test_c06_commercial_surfaces.py -k
'test_03 or test_09'`. Inspecione se holdout real satisfaz o contrato; depois
execute a coorte de 51 e só então faça commit/integração. Acrescente o arquivo
novo de superfícies à coleta obrigatória do agregador quando estabilizado.

### Windows / distribution

Worktree `/home/tjsasakifln/code/modelapro-c06-distribution`; último commit
conhecido `a7a196c4ca083ddae91d5c03184cd42f80921fa0`, já integrado como `c60fbeb`.
Copie hashes de `git rev-parse`, nunca complete abreviações por memória.
Checkpoint final do agente: worktree limpo, nenhum commit pendente nem processo
em execução. Job Windows `103614079953`: instalação/preflight A, catálogo,
controller de navegador e ACL passaram; operação falhou e update/rollback não
rodaram. Obter `initial.json`, `initial-product.log`, `initial-installed-ui.json`
e log do job para a primeira causa exata; download tentou Azure Blob e encontrou
TLS handshake timeout. Preservar documentos eventualmente emitidos. Nenhum push.

## Execuções e evidência

| Run | Candidata | Estado observado no encerramento |
|---|---|---|
| [Windows 34716312452](https://github.com/tjsasakifln/modelapro/actions/runs/34716312452) | c60fbeb | FAILURE: falharam operação/cálculo/documentos/save/reopen/backup em A e uninstall. Construção e instalação inicial tinham passado. Causa desta nova falha ainda não diagnosticada neste handoff |
| [C15 PR 34716312436](https://github.com/tjsasakifln/modelapro/actions/runs/34716312436) | c60fbeb | Suíte ampla em execução; lint FAILURE (6 E122, corrigidos localmente em c27b6e8); P04, C15 Linux/Windows, C16, wheel/sdist e clean venv SUCCESS |
| [C15 PR 34714577751](https://github.com/tjsasakifln/modelapro/actions/runs/34714577751) | 6867f31 | FAILURE: 1678 passed, 2 failed, 1 skipped; expectativa de custo antiga e sincronização P02. Merge testado 9517073b5c6a660c829b55491de6787b5fdb2282, corretamente distinto do PR HEAD |
| [Windows 34714577745](https://github.com/tjsasakifln/modelapro/actions/runs/34714577745) | 6867f31 | FAILURE: executável não encontrado entre etapas; nenhum cálculo nessa execução. Correção de caminho/espera/preflight em c60fbeb |

Existe também C15 push `34716310335`; consultar separadamente, sem misturar
identidades/artefatos entre runs. A matriz e o topo remoto da PR ainda contêm
status antigos: este checkpoint os substitui para retomada, não altera históricos.

Provas locais relevantes, sem equivaler a aceite do artefato final:

- Navegadores reais mercado+custo, guardas habilitadas: **2 passed / 236,88 s**
  na coorte c60fbeb. Mercado percorre revisão/exportação/assinatura TESTE/importação;
  custo calcula 920 BRL, salva e reabre. Assinatura de custo também tem teste de serviço.
- BB: worker real, comprovante não verificado, duas gerações, dossiê/histórico,
  adulteração: **1 passed / 318,64 s**. Não é aceitação institucional.
- Receipt/C05/qualificação após `999680d`: **84 passed / 24,60 s**.
- Catálogo fonte/distribuição+C05: 553 passed local em coorte anterior; NIST
  e mutantes materiais estão documentados em [numeric_verification.md](numeric_verification.md).
- `scripts/comercial/aceite/verify_c06.py`: PASS 89 / FAIL 0; não é liberação.

Evidência preservada fora da retenção pytest:
`/tmp/modelapro-c06-document-inspection.nEGkZI/`, incluindo
`browser-evidence/c06-document-flow/` e `browser-evidence/c06-cost-flow/`,
inventários SHA/tamanho e documentos efetivos. Há inspeções raster de PDF de
mercado/custo; não são revisão profissional. O coletor
`tests/comercial/browser_evidence.py` usa allowlist e exclui chaves/credenciais.
No CI usa `C17_UI_EVIDENCE=artifacts/ui-e2e`. Temporários são apoio local, não
substituem artefatos publicados e identificados da candidata final.

## Contratos já compostos que precisam ser preservados

- C01 consome `resolve_profile` e contexto real C05; C05 é autoridade de liberação.
  Graus 0/None/erros/proveniência preservados; sem defaults atestadores, sem
  recomputação permissiva. Result fingerprint, conteúdo de laudo e bytes assinados
  têm papéis separados. Histórico permanece acessível.
- Catálogo via recursos do pacote `profiles`, seis perfis no wheel/sdist/bundle;
  diretório vazio e versão/hash desconhecido falham. Não empacotar normas integrais protegidas.
- Custo usa BOM/BDI/depreciação e contrato real, não CSV/regressão fictícia.
  Precisão de regressão aparece como não aplicável ao custo. Fixture UI 920 BRL e
  fixture de serviço 1420 BRL têm BOM diferentes.
- HTTP/WS/upload/export/backup/restore/primeiro uso têm guardas reais habilitadas;
  licença de comprador é distinta de assinatura e qualificação. Expiração preserva leitura/exportação.
- Revisão documental vincula resultado/conteúdo/bytes; assinatura pyHanko é
  verificada contra raízes do servidor. Documentos/dossiê são validados antes de
  gravar a nova geração; geração anterior fica em `document_history.zip`.
- Comprovante recebido é `received_declared_unverified`: consentimento false por
  padrão, bytes e registro imutável verificados, somente material autorizado entra
  no novo laudo. Ignora alegação de aceite em RequestSpec. Hash garante consistência,
  não autenticidade do remetente, nem ato institucional, nem proteção contra alguém
  capaz de reescrever todo o armazenamento e recalcular hashes.
- Agregador mantém pipefail, accept-candidate, extensões, coleta/conteúdo/JSON/JUnit,
  namespaces e identidade pr_head/base/tested/tree/event/run/attempt/package hashes.
  Skip de obrigação, vazio, timeout, código perdido e artefato trocado reprovam.

## Pendências internas e externas

Internas: concluir cobertura externa e P02/banner; corrigir novo fracasso Windows;
validar ciclo instalado completo; revisar lock Windows resolvido, SBOM/licenças
por versão e fechamento das DLLs; fixar inventário com comparação de regeneração;
provar atualização/rollback **entre árvores distintas**, após primeira candidata
realmente operacional. Import/wheel/.spec/.iss e ciclo da mesma árvore não bastam.
Reexecutar CI final, conferir representações reais/assinatura TESTE/anexos e
legibilidade, pacote/manual/inventário/matriz e topo da #20. NOASSERTION continua
fila de investigação, não licença incompatível demonstrada.

Externas: dez ou mais casos autorizados do protocolo, revisão profissional
independente real, atos/processo do destinatário por perfil, decisões do titular
sobre direitos/termos e identidade/âncora pública legítima de entitlement.
Detalhes: [real_case_matrix.md](real_case_matrix.md), dependências na
[matriz](integration-matrix.md), [fontes/processos por perfil](profile-process-verification-20260912.md).
Não pedir chave privada; não escolher licença aberta sem autorização. Ausência
dessas fontes/atos não impede terminar código e CI. Não reduzir oferta a uso assistido.

| Estado | Checkpoint honesto |
|---|---|
| INTEGRATION_COMPLETE | IN_PROGRESS: consumidores compostos, correções/aceite final pendentes |
| NUMERIC_VERIFICATION | Evidência local existente; confirmar artefato final |
| NORMATIVE_SCOPE_VERIFICATION | Implementação/fontes versionadas; confirmação integrada final pendente |
| DOCUMENT_AND_SIGNATURE_FLOW | Positivos/negativos reais com TESTE local; confirmação final pendente |
| WINDOWS_DISTRIBUTION_VERIFIED | NOT_VERIFIED; último run FAILURE |
| SECURITY_AND_THIRD_PARTY_REVIEW | IN_PROGRESS; revisão técnica local não substitui inventário final |
| REAL_CASE_VALIDATION | NOT_RUN externo |
| INDEPENDENT_PROFESSIONAL_REVIEW | NOT_RUN externo |
| INSTITUTION_ACCEPTANCE_BY_PROFILE | NOT_RUN externo |
| COMMERCIAL_RELEASE_READY | false |

## Ambiente e comandos úteis

Python de diagnóstico: `/tmp/modelapro-c06-validation.vpM1sp/bin/python`
(system-site-packages; não chamar de ambiente limpo de distribuição).
Browser Linux: `LD_LIBRARY_PATH=/tmp/modelapro-c06-browser-libs.Mqa0Kk/extracted/usr/lib/x86_64-linux-gnu`.
O Python do host sem pyHanko/asn1crypto não é evidência de defeito do lock final.
Lint equivalente ao CI (não usar limite default 79):

```bash
/tmp/modelapro-c06-tools/bin/flake8 --max-line-length=120 --extend-ignore=E203,W503 \
  setup.py modules/config_manager.py modules/logging_manager.py backend/monitor.py \
  backend/__init__.py modules/__init__.py frontend/__init__.py frontend/components/__init__.py \
  scripts/c15_local scripts/pro_workflow tests/c15_packaging tests/pro_workflow/p04 tests/fixtures/pro_workflow
```

Passou no HEAD técnico local. Para atualizar a PR, consultar o corpo atual via
REST: `gh pr edit` deste ambiente falhou por projectCards GraphQL depreciado.
Preservar `<!-- C06_CURRENT_START -->`/END e registros antigos como históricos.

## Autoridade na continuação

C06 é único publicador da composição; agentes isolados não fazem push.
São autorizados correções transversais, testes, commits e evidências na #20.
**Não fazer merge em main/#17, auto-merge, deploy, release/venda, submissão
institucional, assinatura real ou aprovação inventada.** Se a #20 mudar para
fechada/mesclada, registrar e escolher continuação segura dentro da autoridade,
sem reabrir/reverter automaticamente. O objetivo só termina quando as obrigações
internas estiverem verificadas e as fronteiras externas estiverem explicitadas.
