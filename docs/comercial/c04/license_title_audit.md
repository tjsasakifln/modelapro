# Auditoria de titularidade e licença

Data de corte: 2026-09-11. Esta auditoria técnica não é parecer jurídico.

## Código do repositório

- Não existe arquivo `LICENSE`, `COPYING` ou declaração equivalente no
  `BASE_SHA`. Isso não impede o titular legítimo de distribuir sua própria
  obra, nem obriga a adotar licença aberta; apenas não documenta, no candidato,
  quem pode autorizar a oferta e quais termos serão concedidos ao comprador.
- `git shortlog -sne 8d66c797` identifica um único nome/e-mail de contribuinte
  no histórico alcançável, mas isso não prova titularidade exclusiva, vínculo
  contratual, cessão de direitos, autorização sobre materiais importados ou
  direito sobre marcas.
- A metadata `authors = [{name = "CONFENGE"}]` é descrição de pacote, não cadeia
  documental de titularidade.

Decisão: `BLOCKED_EXTERNAL_EVIDENCE` para a composição, até que a autoridade do
titular e os termos comerciais do comprador sejam registrados. Publicar o
código sob licença aberta não é requisito. C04 não presume falta de direito do
titular e não altera licença ou autoria unilateralmente.

## Ativos no checkout

| ativo | entra no wheel/instalador planejado | prova de direito | decisão |
| --- | --- | --- | --- |
| `modules/templates/report.html` | sim | código do histórico; depende da decisão de autoridade/termos acima | decisão do titular pendente para a oferta |
| `frontend/assets/styles.css` | sim | código do histórico; depende da decisão de autoridade/termos acima | decisão do titular pendente para a oferta |
| três PDFs na raiz | não | origem/licença não demonstrada | exclusão obrigatória do artefato; decisão do titular pendente |
| PDFs de evidência P03 | não | evidência interna; redistribuição comercial não autorizada | exclusão obrigatória |
| arquivos de fonte tipográfica | nenhuma fonte própria é adicionada; dependências como Matplotlib podem levar fontes no congelamento | SBOM registra caminho/hash/tamanho por distribuição e o manifesto registra os bytes finais | revisar licença/notice de cada fonte realmente presente; não presumir ausência antes do build |
| bibliotecas nativas de tipografia/PDF | sim, somente o fechamento transitivo realmente carregado | versão, pacote MSYS2, metadata de licença, licença retida e SHA-256 no `native-runtime.json` | cada `NOASSERTION` ou licença sem arquivo retido permanece na fila de revisão |
| dados de teste | apenas corpus explicitamente sintético quando necessário | marcações `SYNTHETIC` no repositório | não incluir por padrão no produto |

Os manifests de empacotamento devem falhar se PDFs protegidos, dados/testes ou
arquivos de fonte não inventariados forem incluídos. Bibliotecas nativas e a
configuração Fontconfig necessárias ao PDF são permitidas somente com
inventário por versão/arquivo e licenças retidas no artefato.

## Dependências

O lock identifica versões, mas o direito de distribuir depende dos wheels e
bibliotecas nativas efetivamente empacotados. `THIRD_PARTY_NOTICES.md`,
`third_party/reuse_manifest.json`, `docs/comercial/c04/reuse.json` e a SBOM do
artefato registram a decisão técnica. A varredura automática é apoio: licença
ambígua/ausente, notice obrigatório não coletado ou vulnerabilidade crítica
alcançável continua bloqueante até decisão específica.

## Evidência externa exata necessária

1. Registro da autoridade do titular para oferecer a versão, dos termos do
   comprador e dos direitos sobre marca/contribuições. Isso não exige uma
   licença aberta nem presume que o titular esteja proibido de distribuir.
2. Confirmação de que os três PDFs da raiz são excluídos do produto ou prova de
   licença para cada um; exclusão do pacote não resolve a publicação no
   repositório público.
3. Revisão dos termos/minutas e da cadeia de licenças do instalador final.
4. Certificado de assinatura de código legítimo e consentimento de uso, se a
   oferta exigir instalador assinado.
