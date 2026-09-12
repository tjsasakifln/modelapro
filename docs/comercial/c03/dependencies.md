# Dependências e limites externos

## C01 — contrato e composição

- Produzir `provenance.qualification_context` MP-QUAL/1 e preservar o bloco no snapshot congelado.
- Manter os estados novos em `case_release_status`; o `validation.issuance.status` MP/1 atual aceita
  apenas os valores antigos. A C03 não altera `modules/result_contract.py`.
- Incluir `result_fingerprint` não vazio. A C03 calcula separadamente
  `report_content_fingerprint` sobre snapshot, contexto, linhas e anexos por hash; ambos precisam
  constar no evento aprovador.

## C02 — fluxo profissional

A C03 aceita o shape publicado por C02: `profile`, evento com `fingerprint`, `professional_id`,
`decision`, `motive`, `version` e `stale`, com a extensão aditiva
`report_content_fingerprint`. Evento stale, fingerprint divergente, conteúdo alterado ou decisão
não aprovadora não libera laudo final. O valor `signed` nunca é decisão de revisão técnica.

## C04 — empacotamento e dependências globais

Proposta: adicionar `pyHanko==0.37.0` como dependência opcional/feature de assinatura e fixar suas
transitivas na constraint aplicável. A frente C03 testou a instalação em venv isolado; não alterou
`pyproject.toml` nem constraints. Também é necessário escolher/empacotar um validador PDF/A concreto
se algum perfil C05 exigir PDF/A.

O wheel local foi inspecionado e contém `modules.report_presenter`, `modules.report_export` e
`modules.digital_signatures`. C04 deve repetir a instalação/importação fora do checkout ao consolidar
as constraints e a dependência opcional.

## C05 — catálogo e regras

- Fornecer perfil resolvido completo e `rule_results` mínimos.
- Declarar quais requisitos de cadeia, revogação e carimbo do tempo se aplicam à assinatura.
- Fornecer fontes legítimas/versões para mapas de banco/seguradora. Sem isso o pacote permanece
  neutro e sem alegação formal de compatibilidade.

## C06 — composição

- Integrar `build_docx` e `build_submission_package` ao fluxo real e registrar estados dos novos
  artefatos no contrato que C01 permitir.
- Passar `report_docx`, revisões, assinatura e bytes assinados a `build_evidence_bundle`.
- Em `prepare_signature_request`, passar o mesmo `report_context`; em
  `record_external_signature`/`verify_signature_binding`, passar os bytes exatos do PDF não assinado.
  Para consumir o estado assinado, fornecer no contexto `unsigned_pdf_bytes`, `signed_pdf_bytes` e o
  registro `digital_signature` verificado.
- Para `signed_integrity_verified`, devolver o PDF assinado já vinculado; não chamar `render_report`
  para inserir selo posterior.
- Executar teste de merge com os HEADs estabilizados dos proprietários e os testes afetados.

## Evidência externa não disponível

Não há nesta entrega caso real autorizado, laudo assinado por profissional externo, certificado
ICP-Brasil, consulta de revogação, carimbo do tempo, execução do VALIDAR/ITI, veraPDF, manual bancário
vigente autorizado, submissão ou aceite institucional. Esses requisitos ficam
`BLOCKED_EXTERNAL_EVIDENCE`, sem conversão em PASS.
