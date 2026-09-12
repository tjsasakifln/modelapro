# C02 — tabela dos oito aceites

Estados do PRODUTO, não contagem de arquivos. Labels permitidos:
`IMPLEMENTED_VERIFIED` | `IMPLEMENTED_PARTIAL` | `WAITING_FOR_COMPONENTS` | `BLOCKED_EXTERNAL_EVIDENCE`.

Não se declara `COMMERCIAL_RELEASE_READY` nem homologação bancos/seguradoras.

| ID | Aceite | Estado | Evidência | Limitação |
| --- | --- | --- | --- | --- |
| C02-A01 | Encomenda e perfil reais | IMPLEMENTED_VERIFIED | `tests/comercial/c02/test_a01_a02_encomenda_evidence.py`; `build_request_spec` emite finalidade, bem, direitos, data-base, unidade, solicitante, destinatário, base de valor e `qualification_profile` versionado. Perfis banco/seguradora conhecidos são `not_homologated` e não ganham selo «aceito pelo banco». | Catálogo C05 / `source_set_sha256` normativo: WAITING_FOR_COMPONENTS. |
| C02-A02 | Evidências e atos humanos rastreados | IMPLEMENTED_VERIFIED | Mesmo arquivo de teste: vistoria com procedência; vazio ≠ inspeção atestada; terceiro = informação recebida; ART/RRT com formato válido ≠ autenticação do conselho; defaults não fabricam atestado. | Autenticação real de conselho/ART é BLOCKED_EXTERNAL_EVIDENCE (ato do conselho). |
| C02-A03 | Controle da amostra e do modelo | IMPLEMENTED_VERIFIED | `test_a03_a04_sample_states.py`: consome prévia canônica, exclusão justificada, mapa dummy→característica original, cobertura de validação independente sem treino como externo, preservação de mapeamento só com fingerprint compatível. | Parser/cálculo continuam na API; UI não recalcula grau. |
| C02-A04 | Estados apto/inapto/pendente | IMPLEMENTED_VERIFIED | `present_aptidao` distingue pending/met/not_met/not_requested/error; análise válida não liberada permanece acessível com motivo e ação; caso sem suporte não ganha valor/verde; percurso met + `ready_for_professional_review` pode preparar laudo. | Classificação normativa de grau continua WAITING_FOR_COMPONENTS (C01 `workflow_context` / C05). |
| C02-A05 | Emissão e revisão inválida após mudança | IMPLEMENTED_VERIFIED | `test_a05_a06_review_recipients.py` + `apply_invalidation(..., "profile"|"sample"|"document")`: eventos ligados ao fingerprint; mudança material marca revisão/assinatura stale sem apagar histórico; consentimento antigo não reutilizável; valor adotado recusado até C05 admitir. | Assinatura criptográfica do PDF é da C03. |
| C02-A06 | Projetos e destinatários | IMPLEMENTED_PARTIAL | Cliente HTTP real contra stub das rotas `/preview` `/jobs` `/projects` `/revisions` `/batch` artifacts; HTTP 200 local ≠ `institution_acceptance`; pacote de destinatário sem portal simulado; seguro mostra base de custo e não esconde descompasso. | GET `/projects/{id}/revisions` 405 na BASE_SHA (handoff P01). Aceite institucional real: BLOCKED_EXTERNAL_EVIDENCE. |
| C02-A07 | Rotina robusta e privacidade | IMPLEMENTED_VERIFIED | Tokens de sessão distintos por arquivo/projeto; duplo POST bloqueado; diagnóstico redige CPF/e-mail/telefone; aviso de backup; demonstração sintético marcada. | Medição de horas de avaliador em piloto real: BLOCKED_EXTERNAL_EVIDENCE (piloto humano NOT_RUN). |
| C02-A08 | Percurso completo em navegador | IMPLEMENTED_PARTIAL | AppTest duas vezes em `frontend/app.py` com headings encomenda/amostra/vistoria/modelagem/emissão; path estático no fonte; Playwright: ver log de disponibilidade. | Sem traces fabricados se Chromium/Playwright ausentes. |

## Declarações que este lote NÃO faz

- Não `COMMERCIAL_RELEASE_READY`.
- Não homologação CAIXA/banco/seguradora/SUSEP/ABNT/IBAPE/NIST/ITI.
- Não Grau III para qualquer amostra.
- Não conversão de preço de mercado em custo de reconstrução por coeficiente.
