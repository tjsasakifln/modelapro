# C06 — matriz da composição, não dos componentes isolados

Retomada em trabalho em 2026-09-12. Última candidata publicada A2:
`df6b7b786f91b7a545d4c925d954cbedb9fbdf17`, com C15 aprovado e Windows reprovado. Os commits posteriores da mesma PR
precisam de execução própria antes de serem aprovados. Os oito aceites de cada
produtor permanecem nos arquivos originais como histórico do componente; esta
matriz identifica seus consumidores na composição. Não declara conclusão pelo
número de testes.

A primeira candidata da retomada terminou reprovada: C15 PR **34719940149** e
push **34719939405** tiveram, cada um, **1.734 passed, 1 failed, 1 skipped**.
Falhou o navegador documental; ambos também registraram
`tracked_source_dirty_after=true`, que o agregador recusou. Os arquivos baixados
tiveram todos os hashes comparados à identidade de cada namespace, preservada
em [evidence-run-34719940149.json](evidence-run-34719940149.json) e
[evidence-run-34719939405.json](evidence-run-34719939405.json).
PR testou merge `9d5ff9d3f523cd1fedd4b9d98b36d5a4fe0cd60b`; push testou o HEAD;
árvore comum `5126d87be0d6f86a9ee1efcf84506195974aaee1`.

Windows **34719940134** também terminou FAILURE. Instalação/preflight/ACL e
desinstalação passaram; operação A falhou antes do cálculo. O instalador real
reproduziu um modal Streamlit com conflito entre developmentMode e server.port.
A correção fixa developmentMode=false e registra exceções do processo filho em
stderr, mas ainda exige nova prova instalada. Não existe A operacional aprovada
para a transição entre árvores distintas. As referências E1/E2 abaixo preservam
o histórico anterior; não aprovam os commits locais posteriores.

A2: C15 PR **34721474693** e push **34721472670** terminaram SUCCESS,
cada um com **1.755 passed, 0 failed, 1 skipped**. A coleta corresponde aos
1.756 nodeids congelados; o skip do smoke isolado é coberto pelo job próprio.
Foram baixados e comparados os hashes de **50 arquivos em sete namespaces por
run**, todos com checkout limpo antes/depois e sem alterações rastreadas.
A PR testou merge `e4b82bed6c3e0ad5987ccc92d16e1bcef9b4588a`, o push testou
seu HEAD, ambos na árvore `d15c8f7356323952a8e391650cceb75137c169c8`.
Identidades: [PR A2](evidence-run-34721474693.json) e
[push A2](evidence-run-34721472670.json). A alteração histórica de A1 não foi
reproduzida na sondagem local e não reapareceu em A2; sua causa não está
estabelecida. A aprovação de A2 não se estende aos commits posteriores.

Windows A2 **34721474609** terminou FAILURE antes de `/health`. A reprodução
local confirmou problemas adicionais do pacote windowed: configuração do logger
com stderr ausente, assets e módulos dinâmicos Streamlit omitidos e cliente HTTP
usado pela interface ausente das dependências runtime. Correções locais passam
por reconstrução e verificação integral antes de nova publicação. Ainda não há
A operacional aprovada para o ciclo entre árvores distintas.
O [registro dos bytes Windows A2](evidence-windows-run-34721474609.json)
preserva 56 entradas baixadas conferidas, incluindo o instalador, além dos
36 arquivos de licença nativa e fontconfig. As 2.266 entradas do índice não
baixadas individualmente não são declaradas verificadas. O audit de 115
distribuições não reportou vulnerabilidades conhecidas; o pacote próprio
`modelapro` não está no PyPI e fica fora dessa consulta de advisories.

## Execução → artefato

| Referência | Execução e evidência exigida | Situação registrada |
|---|---|---|
| E1 | [C15 PR 34716312436](https://github.com/tjsasakifln/modelapro/actions/runs/34716312436): JUnit, collection.json, status, identity.json e inventário de bytes por namespace | FAILURE confirmado na retomada: 1703 passed, 1 failed (P02 sincronização), 1 skipped; lint também falhou. Correções posteriores exigem nova execução. Histórico 34714577751 falhou em 2 testes (1678 passed, 1 skipped): expectativa antiga de custo e sincronização do navegador P02; agregador recusou corretamente. Merge testado 9517073b5c6a660c829b55491de6787b5fdb2282 foi distinguido do PR HEAD 6867f31, sem erro de stale SHA |
| E2 | [Windows 34716312452](https://github.com/tjsasakifln/modelapro/actions/runs/34716312452): lock resolvido no Windows, fechamento de DLLs, hashes, manifesto de falha | FAILURE confirmado na retomada: instalação/preflight passaram; /health não abriu em 120 s na operação A. Update/rollback não executados; uninstall também reprovou. Diagnóstico/correção em curso. Histórico 34714577745 construiu/instalou, mas o verificador não encontrou o executável na etapa seguinte; nenhum cálculo foi executado. Caminho recomposto e espera do processo corrigidos; não é Windows verificado |
| E3 | Serviço C03 e rotas reais: `pytest tests/comercial/test_c06_document_flow.py tests/comercial/test_c06_security_routes.py` | 28 passed local; ambiente diagnóstico com pacotes de sistema, não substitui E1/E2 |
| E4 | Catálogo C05 e distribuição: `pytest tests/comercial/c05 tests/comercial/c06/test_catalog_distribution.py` | 553 passed local após fontes versionadas; wheel ampliado precisa nova execução candidata |
| E5 | NIST e qualificação integrada + coleção: `pytest` respectivos arquivos | 122 passed local, incluindo Decimal independente e mutantes materiais; orçamento em numeric_verification.md |
| E6 | `test_c06_cost_flow.py`, `test_c06_document_flow.py`, `test_c06_recipient_return.py` e `test_c06_recipient_document.py` sobre 6867f31 | 27 passed local, incluindo assinatura TESTE real de custo/mercado e importação de comprovante não verificado; C15 precisa confirmar ambiente candidato |
| E7 | `test_c06_browser_document_flow.py`: Streamlit + uvicorn + Chromium, guardas habilitadas | 1 passed local; upload integral, cálculo, revisão, exportação PDF, assinatura TESTE/importação, dossiê e histórico. Incluído na coleta obrigatória E1 |
| E8 | Navegador mercado + custo juntos, incluindo coletor de artefatos reais sem chaves privadas | 2 passed local em 236,88 s sobre a coorte c60fbeb; custo 920,00 BRL salvo/reaberto; PDF/DOCX/dossiê/assinatura TESTE por namespace |
| E9 | Retorno BB real worker → registro não verificado → duas gerações documentais → dossiê/histórico → adulteração | 1 passed em 318,64 s; não é aceite institucional. Integridade dos metadados do registro em endurecimento adicional |

O artefato histórico de E1 foi baixado e aberto nesta retomada: PR HEAD
`c60fbeb`, merge testado `151d63b648d0aab08afce8eb79a21d266477fbfb`, árvore
`f8cfc683daf029b93493c9771119f8d81c9f45b3`. Dez arquivos do navegador mercado
e dois do custo conferiram seus hashes/tamanhos. As capas PDF foram rasterizadas
e inspecionadas (mercado 21 páginas; custo 10 páginas, minuta com pendências).
Identidades/bytes: [evidence-run-34716312436.json](evidence-run-34716312436.json).
Isso preserva evidência da candidata reprovada; não aprova a árvore posterior.

Cada identidade deve distinguir pr_head_sha, base_sha, tested_commit_sha, tree_sha,
pais, evento, run_id, tentativa, checkout limpo e hashes dos pacotes. Um número de
run nesta tabela não aprova seu conteúdo: o agregador lê e verifica os arquivos.
Build/testes falhos continuam a produzir evidência; artefatos não se sobrepõem.

## Requisito → implementação → teste → execução → artefato

| Aceites abrangidos | Consumidor/implementação na composição | Testes executáveis / evidência | Execução |
|---|---|---|---|
| C01-A01 | data_loader → preparação → worker; IDs e amostra efetiva | comercial/c01/test_a01_ingest.py; ledger e feature_schema no frozen_project/dossiê | E1 |
| C01-A02, A05; C06-A02 | regressão, seleção, escala e intervalos; orçamento prévio + oráculo Decimal | c01/test_a02_a05_fit_selection.py; p04/test_nist_strd.py; numeric_verification.md | E1/E5 |
| C01-A03, A07; C05-A03, A04, A07; C06-A03 | resolver real C05 + assess_qualification com contexto; C05 mantém decisão/bloqueios/história; revalidação preserva graus/proveniência | test_c06_qualification_integration.py, c05; snapshot/normative_assessment/document_state | E1/E3/E4 |
| C01-A04 | estado congelado, lote e reprodução independente do processo | c01/test_a04_a07_parity.py e testes P04/C03 de reprodução; frozen_project/evidence_bundle | E1/E3 |
| C01-A06; C05-A06 | BOM de custo e Tabelas 6/7 com fonte, BDI e depreciação; mesmo /jobs, sem regressão fictícia | test_c06_cost_consumer.py, test_c06_cost_flow.py, test_c06_browser_cost_flow.py; MP-COST/1, dossiê/reprodução e assinatura TESTE | E6/E8; confirmação candidata em E1 |
| C01-A08; C02-A01, A02, A03 | UI encomenda/perfil → API → cálculo; evidência documental sem defaults atestadores | c01/test_a08*, c02/test_a01_a02*, c02/test_a03*; request_spec/response persistidos | E1; novo formulário requer nova execução |
| C02-A04, A07 | snapshot único em tela, projeto, revisão, lote e recuperação; valor/política sem cópia aprovadora | c02, c17, p04; projetos/revisões + comparação com snapshot | E1 |
| C02-A05; C03-A01, A06 | /documents/review → exportação dos bytes PDF → importação/verificação pyHanko com trust roots do servidor | test_c06_document_flow.py; assinatura TESTE, assinatura antiga e PDF adulterado | E3/E6/E7; confirmação candidata em E1 |
| C02-A06; C03-A07; C06-A05 | pacote de submissão local, mapa de requisitos/saída C05; nenhum envio externo | submission.zip, output_manifest; negativos de campos sem bytes e perfil desconhecido | E3; ato institucional NOT_RUN |
| C02-A08 | Streamlit real + navegador lançado, autenticação HTTP/WS habilitada | c02/test_playwright_path.py e test_c06_browser_document_flow.py; falha/NOT_RUN bloqueante se navegador não inicia | E1/E7 |
| C03-A02, A05 | presenter único → PDF/DOCX; comparação substantiva de valores/intervalos/política/perfil | test_c06_document_flow.py e c03; report.pdf/report.docx | E3/E1 |
| C03-A03, A04 | anexos integrais autorizados, registro hash, dossiê/reprodução; completude separada de integridade | upload de bytes, adulteração, inventário de representações; evidence_bundle.zip | E3 |
| C03-A08; C06-A07 | verificadores de saída e guardas ligados às rotas, não campo inventado pelo teste | c03/p04 mutation tests + test_c06_security_routes.py | E1/E3 |
| C04-A01, A07; C06-A07 | locks/SBOM/licenças por versão e binário; âncora de comprador no artefato | inventário Python/native, notices/manifest/hash; NOASSERTION permanece investigação | E2; revisão final pendente |
| C04-A02; C06-A06 | wheel/sdist/catalog/manual + bundle/instalador Windows | wheel fora do checkout; Windows install/launch/calc/docs/save/reopen/restore/update/rollback | E1/E2; Windows NOT_VERIFIED |
| C04-A03, A06 | middleware e bootstrap real: Origin/Bearer/CSRF/path/workspace/limites; credencial atômica e privada | test_c06_security_routes.py, test_c06_runtime_bootstrap.py; guardas habilitadas no positivo | E1/E3; ACL Windows pendente |
| C04-A04, A08 | backup/hash/restauração sob exclusão de admissão; fila/cancelamento/recuperação | testes C04 e rotas, barreira concorrente; ciclo Windows entre árvores distintas | E1/E2 |
| C04-A05 | licença comprador separada; expiração bloqueia novo cálculo, preserva leitura/exportação | importação com âncora fixada; negativo de chave fornecida pelo cliente; fluxo legítimo | E1/E3; termos/titular externos |
| C05-A01, A02 | fontes autorizadas parafraseadas, catálogo versionado dentro do pacote; ausência não produz catálogo vazio | c05/test_a01*, inventário regras, catalog_distribution; comparação fonte=wheel | E1/E4 |
| C05-A05, A08 | requisitos por perfil e limitações explícitas, sem selo de banco ou universalidade | c05/output_conformance + profile-process-verification-20260912.md | E4; atualidade/aplicabilidade por encomenda |
| C06-A01 | accept-candidate, pipefail, extensões e agregação fail-closed com coleta obrigatória; inventário exato regenerado/comparado antes da suíte e conferido contra execução/JUnit | c15_packaging/test_ci_aggregator.py, test_evidence_identity.py, test_collection_evidence.py, test_test_inventory.py; mandatory-test-nodeids.json e inventory-check.log | E1 |
| C06-A04 | protocolo congelado de dez ou mais casos autorizados + parecer independente | real_case_matrix.md; nenhum resultado ou identidade fictícia | NOT_RUN externo |
| C06-A08 | dez estados separados, pacote identificado e aprovação sustentada por prova | esta matriz, estados na #20 e evidência candidata | COMMERCIAL_RELEASE_READY=false |

## Dependências externas exatas (não são desculpa para código faltante)

- Titular: autoridade/direitos sobre contribuições e materiais efetivamente distribuídos;
  termos do comprador, privacidade/suporte e identidade/chave pública legítima de
  emissão de entitlement. Não escolher licença aberta; não solicitar chave privada.
- Dados: para cada RC-01…RC-10 do protocolo, autorização de uso/armazenamento,
  amostra integral com fontes/datas/unidades, identificação do bem/encomenda e
  trabalho de referência. Dez é parâmetro do protocolo, não norma universal.
- Revisão: profissional independente identificado, competência/conselho e escopo
  aplicáveis, declaração de independência e parecer real sobre os casos/resultados.
- Normas/perfis: confirmação verificável da edição aplicável quando se pretender
  alegar vigência; instruções/ordem/contrato do destinatário concreto. SUSEP/BCB
  não substituem as condições de uma seguradora ou banco. Processo consultado e
  fontes exatas constam de profile-process-verification-20260912.md.
- Assinatura real: certificado e política do profissional/destinatário, cadeia e
  mecanismos de revogação/carimbo exigidos. PDF/A só quando exigido e validado por
  validador efetivo. Certificado TESTE não é ICP-Brasil nem parecer.
- Submissão/aceite: autorização específica e ato real do destinatário. Esta retomada
  prepara/verifica o pacote local; não transmite, protocola ou inventa homologação.

## Impedimentos internos ainda abertos nesta redação

Os 26 gaps de capacidade identificados na retomada têm produtores e verificadores
integrados: [output-gap-closure.md](output-gap-closure.md). A coorte local de
interface, superfícies comerciais, documentos e arbitramento passou 52 testes;
as representações reais e os hashes estão no registro local vinculado. Isso
não estende o SUCCESS de A2 aos commits posteriores.

O navegador real confirmou o formulário composto: mercado e custo passaram
juntos, **2 passed, 0 failed, 0 skipped**, em 175,91 s. As incompatibilidades
encontradas na lista canônica de variáveis e nas coordenadas pt-BR além da prévia
foram corrigidas. O seletor do teste de custo agora confere o rótulo visível
efetivamente selecionado. Os 12 arquivos emitidos tiveram hashes e tamanhos
conferidos em [evidence-local-browser-20260912.json](evidence-local-browser-20260912.json).

A repetição após a correção do token de criação e da corrida de idempotência
passou **2 testes / 140,917 s** no HEAD `71d549a`; os 12 arquivos foram novamente
conferidos em [evidence-local-browser-71d549a.json](evidence-local-browser-71d549a.json).
Lint e inventário exato de **1.830 obrigações** passaram nesse HEAD. Os consumidores
de criação/segurança/launcher passaram 99 testes; a revisão independente confirmou
50 corridas com um criador portador de token e um reaproveitamento sem token.
A suíte ampla local anterior encerrou com **1.822 passed, 5 failed, 1 skipped**,
checkout limpo; as cinco causas e correções estão preservadas em
[evidence-local-wide-661fc82.json](evidence-local-wide-661fc82.json). As correções
passaram nos consumidores focados, mas a suíte ampla final continua pendente.

Permanecem obrigatórios a suíte ampla/agregador da candidata final, a confirmação
das representações e guardas nos seus artefatos, o Windows instalado operacional
e a atualização/restauração entre árvores distintas. A3 é a candidata operacional
intermediária; um ciclo da mesma árvore deve dizer `OPERATIONAL_SAME_TREE_ONLY`.
O ciclo distinto exige identidade de origem incorporada no executável, cálculo
novo e conferência dos arquivos instalados. Esses itens continuam sendo trabalho
C06, sem substituir os atos externos definidos acima.
