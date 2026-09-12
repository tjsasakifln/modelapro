# Registro de evidência C04

Data: 2026-09-11. Base imutável:
`8d66c7973c659174e06d7223c9a9a8181e8eeabf`. Branch:
`mp-com-20260912/c04-produto-distribuivel`. O SHA do candidato publicado e os
hashes pós-commit são registrados no comentário da PR, para não criar ciclo de
autorreferência neste documento.

## Ambiente observado

- Linux x86_64, kernel WSL2 `6.18.33.2-microsoft-standard-WSL2`.
- Python `3.12.3`.
- checkout de trabalho separado, derivado diretamente da base declarada.
- Windows x64/Inno Setup/assinatura de código: **não executados** neste host.

## Comandos e resultados preservados

| comando/ensaio | ambiente | exit code/resultado |
| --- | --- | --- |
| `pytest -q tests/comercial/c04 tests/c11_persistence tests/c15_packaging` | ambiente global inicial | falhou: 2 testes de `.xls` sem `xlrd`; essa ausência do ambiente não foi aceita como prova de pacote |
| mesma matriz após reconciliar o alvo remoto `2a8009b` | venv limpo Python 3.12 | exit `0`: 169 passaram, 1 ignorado por condição explícita, 5 avisos |
| `C15_INSTALL_SMOKE=1 ... test_wheel_install_smoke.py` | venv externo criado pelo teste, sem `PYTHONPATH`/checkout | exit `0`: 1 teste passou em 91,89 s; wheel instalado, recursos importados e API respondeu `/health` |
| harness operacional com navegador | Linux de referência | exit `1`; fila/cancelamento, backup/restore, disco e PDF passaram; corpus falhou por Chromium sem `libnspr4.so` e extensão de grau ausente na execução agregada |
| harness operacional sem navegador | Linux de referência | exit `1`; checks operacionais passaram; corpus técnico teve 27/28 testes e falhou na extensão de grau |
| `pip-audit` do ambiente `commercial-build.txt` | venv limpo, 98 distribuições | exit `0`, nenhuma vulnerabilidade conhecida reportada; isso não prova ausência universal nem alcançabilidade |
| build/instalação Windows x64 | não disponível | `NOT_RUN`, bloqueante para A02/A07/A08 |
| `flake8 --max-line-length=120 ...` nos caminhos C04 alterados | venv limpo | exit `0`, zero achados |

Os resultados vermelhos foram preservados em
`evidence/operations-linux-reference.json` e
`evidence/operations-linux-nonbrowser.json`; não foram rerodados até parecerem
verdes. `evidence/sbom-linux-build-env.json` e
`evidence/pip-audit-linux-build-env.json` inventariam o ambiente Linux que
reproduziu exatamente os 97 pins de `commercial-build.txt` mais o próprio
`modelapro`. O SBOM preserva 16 licenças como `NOASSERTION`; elas não foram
convertidas artificialmente em licença conhecida. Esses arquivos não são o
inventário do instalador Windows ainda inexistente.

## Hashes dos insumos e artefatos de evidência

| arquivo | SHA-256 |
| --- | --- |
| `constraints/linux-py3.txt` | `c8b2fc451afd5fdf02df8ff86a35c4bb662320656e1f7ce19df1a1cabc78eda6` |
| `constraints/commercial-build.txt` | `6542331c4c38a0cfc35935ff545fcab535243d9c9ac582fc254071f4e2aca478` |
| `evidence/sbom-linux-build-env.json` | `dda345f5e760862597fc4b05227c50e9d3e68cd043915f09918dbdea1678b7cc` |
| `evidence/pip-audit-linux-build-env.json` | `93fbf0171a9f251a7a710e12fd7373d141800fa1f97f520c43b43de267359bad` |
| `evidence/operations-linux-reference.json` | `fd598a98348dbc3953e7e2e281ed8a2f2f28831bbc8ace1e6301dcdda41636ce` |
| `evidence/operations-linux-nonbrowser.json` | `5259a716441d373db751c22ef797dc82736924fbc7d873c3ff246958cc28103f` |

## Limiar operacional prévio

`performance_budget.json` fixa antes do ensaio os limites de fila, tempo,
memória, espaço e integridade. O orçamento de busca não é reduzido pelo harness.
Falha de espaço deve recusar trabalho novo antes da execução; cancelamento deve
terminar em estado explícito; backup restaurado deve manter hash e metadados.

## Separação de identidade

- base: SHA acima;
- commits intermediários C04: `7e48c2aad751c264d8a4b58ee92a8b36d18653f1`
  e `085c0cb2ba587b836ef4ac2db2ef7c85d514e15a`;
- candidato/HEAD documental: publicado somente após commit e push;
- merge de teste/composição C06: ainda inexistente nesta frente;
- instalador comercial: ainda inexistente.

Logo, contagens de testes do checkout não qualificam um instalador futuro nem
resolvem os bloqueios externos da matriz de aceites.
