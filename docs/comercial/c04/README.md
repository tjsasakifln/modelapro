# MP-COM-20260912-V2/C04 — produto distribuível

Base: `8d66c7973c659174e06d7223c9a9a8181e8eeabf`
Branch: `mp-com-20260912/c04-produto-distribuivel`
Contrato preservado: `RequestSpec` / `ResultSnapshot` MP/1 e
`workflow_context` MP-PRO/1.

## Oferta inicial permitida pelo recorte C04

| dimensão | recorte anunciado |
| --- | --- |
| método | comparativo direto de dados de mercado com regressão |
| bem | imóvel urbano dentro do domínio amostral e das categorias suportadas |
| base de valor | valor de mercado, com estimando/unidade/data explicitados no resultado |
| usuário | profissional habilitado, identificado e responsável pela revisão |
| destinatário | uso profissional genérico; perfil institucional somente quando C05/C01/C02/C03/C06 comprovarem a regra e a aceitação aplicáveis |
| operação | estação local de um usuário; Windows x64 é o produto-alvo e Linux é referência separada |

O software preserva análise exploratória quando a emissão qualificada é
bloqueada. Grau, integridade de assinatura, qualificação do software, revisão
profissional e aceitação do destinatário são decisões distintas.

Não está nesta oferta: custo de reconstrução/reposição, SaaS compartilhado,
aprovação automática por banco/seguradora/ABNT/IBAPE/NIST/ITI, Grau III para
qualquer amostra ou operação em rede. Um perfil securitário que necessite custo
permanece bloqueado até a rota validada das demais frentes existir e ser composta.

## Estado desta frente

O código desta branch prepara componentes de instalação, proteção local,
backup, licença offline, privacidade, SBOM e manutenção. O estado por aceite
está em `acceptance.md`; ele não deve ser inferido pelo número de arquivos ou
testes. Em especial, a ausência de uma licença do repositório, de decisão sobre
os PDFs da raiz, de instalador Windows realmente executado e de integração das
proteções nas rotas impede declarar `COMMERCIAL_RELEASE_READY`.

## Documentos de operação

- `operations_manual.md`: instalação, dados, backup, atualização e recuperação.
- `threat_model.md`: ativos, fronteiras, ameaças e controles.
- `privacy.md`: tratamento local, retenção e diagnóstico.
- `support_and_maintenance.md`: versões, vulnerabilidades e suporte.
- `commercial_terms_draft.md`: minuta não aceita nem assinada.
- `license_title_audit.md`: titularidade e pendências de redistribuição.
- `handoff.json`: conexões mínimas que pertencem a C01/C02/C03/C05/C06.
