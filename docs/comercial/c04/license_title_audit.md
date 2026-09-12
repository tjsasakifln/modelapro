# Auditoria de titularidade e licença

Data de corte: 2026-09-11. Esta auditoria técnica não é parecer jurídico.

## Código do repositório

- Não existe arquivo `LICENSE`, `COPYING` ou declaração equivalente no
  `BASE_SHA`. Repositório público não concede, por si só, direito de
  redistribuição.
- `git shortlog -sne 8d66c797` identifica um único nome/e-mail de contribuinte
  no histórico alcançável, mas isso não prova titularidade exclusiva, vínculo
  contratual, cessão de direitos, autorização sobre materiais importados ou
  direito sobre marcas.
- A metadata `authors = [{name = "CONFENGE"}]` é descrição de pacote, não cadeia
  documental de titularidade.

Decisão: `BLOCKED_EXTERNAL_EVIDENCE`. O titular deve escolher e publicar os
termos aplicáveis ao código/artefato e confirmar direitos sobre contribuições e
marca. C04 não altera licença ou autoria unilateralmente.

## Ativos no checkout

| ativo | entra no wheel/instalador planejado | prova de direito | decisão |
| --- | --- | --- | --- |
| `modules/templates/report.html` | sim | código do histórico; depende da decisão global acima | bloqueado com o código |
| `frontend/assets/styles.css` | sim | código do histórico; depende da decisão global acima | bloqueado com o código |
| três PDFs na raiz | não | origem/licença não demonstrada | exclusão obrigatória do artefato; decisão do titular pendente |
| PDFs de evidência P03 | não | evidência interna; redistribuição comercial não autorizada | exclusão obrigatória |
| fontes tipográficas | não há arquivo rastreado; não incluir | n/a | proibido acrescentar nesta campanha |
| dados de teste | apenas corpus explicitamente sintético quando necessário | marcações `SYNTHETIC` no repositório | não incluir por padrão no produto |

Os manifests de empacotamento devem falhar se PDFs/fontes/testes forem incluídos.

## Dependências

O lock identifica versões, mas o direito de distribuir depende dos wheels e
bibliotecas nativas efetivamente empacotados. `THIRD_PARTY_NOTICES.md`,
`third_party/reuse_manifest.json`, `docs/comercial/c04/reuse.json` e a SBOM do
artefato registram a decisão técnica. A varredura automática é apoio: licença
ambígua/ausente, notice obrigatório não coletado ou vulnerabilidade crítica
alcançável continua bloqueante até decisão específica.

## Evidência externa exata necessária

1. Declaração do titular sobre licença comercial do código, marca e
   contribuições, com versão/escopo.
2. Confirmação de que os três PDFs da raiz são excluídos do produto ou prova de
   licença para cada um; exclusão do pacote não resolve a publicação no
   repositório público.
3. Revisão dos termos/minutas e da cadeia de licenças do instalador final.
4. Certificado de assinatura de código legítimo e consentimento de uso, se a
   oferta exigir instalador assinado.
