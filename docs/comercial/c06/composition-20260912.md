# Retomada C06 — composição de 2026-09-12

Registro inicial, anterior às correções e à validação integrada. A PR #20 estava
OPEN, sem merge, em `74ce243b30ec37a15a014e4a457694a3fe42ffd8`.
Base remota e merge-base da #20: `6d54f902b85a5a37bfbf154d39f74cf854ff9b2b`.
Main observada: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`.

Os comentários atuais das PRs foram lidos antes da composição. As referências
abaixo foram conferidas por fetch e consulta remota, congeladas para esta coorte e
incorporadas por `merge --no-ff`, sem reescrever os produtores.

| Produtor | PR | HEAD congelado | Merge-base com a C06 inicial |
|---|---|---|---|
| C01 | #23 | `3910a20fa34f4b2b57e58dd2063cb7ec09c55b64` | `8d66c7973c659174e06d7223c9a9a8181e8eeabf` |
| C02 | #22 | `f0d8eaa4056e9197f90102d888707755c300b00b` | `2a8009bc7030e1c7d48ed444c4be3b588caa94ae` |
| C03 | #26 | `c9ccb43fbb2ba65a6f2082cdb8347134d45bd310` | `8d66c7973c659174e06d7223c9a9a8181e8eeabf` |
| C04 | #25 | `fbb9c9327e320ce385183d4988b731c4ef3e7996` | `2a8009bc7030e1c7d48ed444c4be3b588caa94ae` |
| C05 | #24 | `a877c14fca2f4ff175ee5419d25f914f044e40a4` | `8d66c7973c659174e06d7223c9a9a8181e8eeabf` |

Nenhum dos cinco HEADs era ancestral da C06 inicial. Todos são ancestrais do
commit de composição `8f93a7c2d9f21cb2dd8fe264c055b91d0c9c8753`. P01–P04 já
compostos permanecem na história; não foram reintegrados como módulos novos.

## Propriedade para o fechamento

Por autorização expressa desta retomada, C06 assume a propriedade dos callsites,
adaptadores, testes e arquivos de distribuição alterados nesta branch para fechar
as conexões entre as cinco entregas. Isso inclui backend, frontend, contrato de
resultado/qualificação, catálogo, documentos, segurança, licença, empacotamento e
CI. As restrições históricas de propriedade dos handoffs não impedem essas
correções transversais. Os produtores não recebem alterações nesta retomada.

Worktrees de qualificação, prova numérica e distribuição trabalham sobre esta
mesma coorte, com commits locais e incorporação serializada por C06. Somente o
checkout da branch da #20 publica; nenhuma outra integração ou PR será criada.

Este registro prova incorporação histórica, não prontidão integrada. Os estados
de produto serão derivados das execuções do candidato corrigido. Casos reais,
revisão profissional e aceitação de destinatários exigem atos e dados autorizados;
não serão substituídos pelos testes sintéticos nem impedem compor o software.
