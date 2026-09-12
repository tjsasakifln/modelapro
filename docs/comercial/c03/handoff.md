# Handoff retomável C03

- Branch: `mp-com-20260912/c03-laudos-evidencias`
- Base confirmada: `8d66c7973c659174e06d7223c9a9a8181e8eeabf`
- Alvo incremental: `mp-pro-20260911/p04-referencia-consolidacao`
- PR base observada: #20 aberta; alvo remoto observado em
  `74ce243b30ec37a15a014e4a457694a3fe42ffd8` antes do commit, sem alteração concorrente nos arquivos
  de propriedade C03.
- HEAD da C03: publicar após o commit/push; não gravar SHA autorreferente aqui.
- Procedência reaproveitada: C08/P03 para renderer e verifier, C12/P01 para dossiê/reprodução, C13/P03
  para ações de conclusão. Nada foi reiniciado ou apagado.

## Entregue

- Gate único de estado documental a partir de MP-QUAL/1, com final somente após regras, amostra
  efetiva, conteúdo e revisão vinculada aos dois fingerprints.
- PDF profissional condicional e DOCX determinístico do mesmo snapshot/view.
- Mapeamento de anexos autorizados, amostra integral e hashes no documento.
- Dossiê ampliado com qualificação, identificadores, equivalência de representações, revisões,
  assinatura e políticas de valor reproduzíveis.
- Assinatura externa vinculada aos bytes PDF antes/depois, snapshot estável, conteúdo, fingerprint e
  revisão, com verificação pyHanko opcional.
- Pacote institucional neutro valida o PDF, DOCX e dossiê antes de montar manifesto e mapa de
  requisitos, sem submissão externa.
- Detectores específicos de adulteração.

## Payload mínimo para proprietários

1. C01: preservar/validar o exemplo `producer_example_qualification_context.json`, decidir os novos
   tipos de artefato e manter `validation.issuance` compatível. O evento de revisão precisa receber o
   `report_content_fingerprint` calculado depois que o contexto documental estiver congelado.
2. C04: avaliar a proposta de `reuse.json` para pyHanko 0.37.0 e um validador PDF/A.
3. C05: substituir as fontes sintéticas pelos perfis/regras legítimos e declarar política de
   assinatura/formato.
4. C06: incorporar o HEAD estabilizado e aplicar os callsites descritos em `dependencies.md`.

## Retomada

Rodar a suíte C03, as regressões C08/C12/C13/P03 e então o conjunto amplo. Conferir `git diff --check`,
manifestos JSON e um teste de merge contra o alvo remoto atualizado. Os comandos e resultados ficam em
`evidence.md`.
