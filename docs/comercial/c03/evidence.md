# Evidência de execução C03

Ambiente observado: Linux x86_64, Python 3.12.3. Base e PR foram verificadas por Git/GitHub antes das
alterações. Nenhum dado de cliente, chave privada ou certificado persistiu no repositório.

## Comandos de aceite

```text
pytest -q tests/comercial/c03
pytest -q tests/c08_report tests/c12_evidence tests/c13_decisions tests/pro_workflow/p01/test_a05_dossier.py tests/pro_workflow/p03 tests/test_results_generator.py
python3 -m py_compile modules/results_generator.py modules/evidence_bundle.py modules/provenance.py modules/decision_support.py modules/report_presenter/*.py modules/report_export/*.py modules/digital_signatures/*.py
git diff --check
```

Resultados no worktree candidato, após a última alteração funcional:

```text
tests/comercial/c03: 19 passed, 1 warning, 90.90 s, exit_code 0
regressões C08/C12/C13/P01-A05/P03/results_generator: 75 passed, 4 warnings, 217.93 s, exit_code 0
py_compile + ruff seletivo + JSON parse + git diff --check: exit_code 0
```

Os avisos são depreciações de FastAPI/Starlette e do fallback FontTools do WeasyPrint quando
HarfBuzz-Subset não está instalado; o PDF foi gerado e inspecionado.

A suíte ampla da primeira execução de CI revelou que um dossiê legado P01 com intervalos de arbítrio,
mas sem política explícita, era classificado como falha numérica total. A compatibilidade foi corrigida:
o ponto e os intervalos estatísticos dentro do escopo prometido continuam `ok`, enquanto a política não
reproduzível fica `partial`. Quando uma `value_policy` é fornecida, qualquer divergência de arbítrio ou
admissibilidade continua reprovando a reprodução.

## Inspeção visual e conteúdo integral

Uma fixture sintética com 210 linhas usadas e 12 excluídas gerou PDF de 29 páginas e 151.996 bytes.
O PDF foi rasterizado por `pypdfium2`; início, página 15 da planilha em paisagem e página 29 foram
inspecionados sem corte de tabela ou página terminal vazia. `pypdf` confirmou as 29 páginas e o teste
automatizado conferiu todos os IDs, o hash das linhas e a imagem autorizada.

## Assinatura real do caminho suportado

Em venv isolado sob `/tmp`, a frente instalou `pyHanko==0.37.0`, gerou uma chave/certificado
self-signed temporários exclusivamente em `TemporaryDirectory`, assinou incrementalmente um PDF
sintético já versionado e verificou com o próprio certificado como trust root local. Resultado:

```text
record_status valid
signature_count 1
incremental_base_verified True
binding_ok True após mudar apenas case_release_status para signed_integrity_verified
signed_document_state_final True (pyHanko reexecutado sobre os bytes fornecidos)
exit_code 0
```

O teste comprova a integração criptográfica e a preservação de bytes no caminho suportado. O
certificado temporário não comprova identidade real, ICP-Brasil, revogação ou carimbo do tempo. A chave
e o certificado foram destruídos com o diretório temporário e nunca foram logados.

## Empacotamento local

`python3 -m pip wheel . --no-deps` gerou o wheel candidato; ele foi instalado com `--no-deps` em venv
temporário, fora do checkout. Os imports de `modules.report_presenter.qualification`,
`modules.report_export` e `modules.digital_signatures` passaram, e a listagem do wheel confirmou os
novos módulos. Exit code 0. Isso prova inclusão no wheel local; C04 continua responsável pelas
constraints e pelo instalador comercial composto.

## Dependência e vulnerabilidades

O wheel `pyhanko-0.37.0-py3-none-any.whl` foi obtido do PyPI com SHA-256
`79046d8057edec5fcc61aa66dc1041262f5248eec473c33a89905a0a661eed05`. A tag `v0.37.0`
resolveu para `51c270ecb438022359a9675329f86e5b24b415b1`. A licença MIT desse tag teve SHA-256
`7b02fde677d4376be46068078822079bf3f511f2303ef144e529c09ea833828c`.

O primeiro `pip-audit` identificou vulnerabilidades apenas no `pip==24.0` criado pelo venv, não nas
dependências de runtime avaliadas. Após atualizar a ferramenta do venv para `pip==26.2`, a auditoria
de 47 distribuições retornou `No known vulnerabilities found`, exit code 0. Isso é uma observação
datada da execução, não garantia futura.
