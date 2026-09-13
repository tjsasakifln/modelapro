# C06 — continuidade em nova sessão

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
