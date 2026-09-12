# C02 — dependências e limitações

## Consumo (somente leitura)

| Componente | Dono | Uso C02 |
| --- | --- | --- |
| `RequestSpec` / `ResultSnapshot` MP/1 | C01 (`modules/result_contract.py`) | Extensão aditiva `qualification_profile`. Não renomeia schema raiz. |
| `provenance.workflow_context` MP-PRO/1 | P01 | Grau pedido vs atingido; C02 não reclassifica. |
| `provenance.qualification_context` MP-QUAL/1 | C01 | Consumido quando presente; ausência = WAITING_FOR_COMPONENTS. |
| `assess_qualification` / catálogo | C05 | Não escrito por C02. Catálogo UI-known é escolha de ids, não regra. |
| `/preview` `/jobs` `/projects` `/revisions` `/batch` artifacts | C10/C11/P01 | Cliente HTTP real. Sem portal institucional. |
| Laudo/PDF/assinatura | C03 (lote comercial) | C02 exporta para assinador externo e importa arquivo original. |
| Dependências globais / SBOM | C04 | Nenhuma dependência nova neste incremento. |

## Handoffs pedidos (payload mínimo)

1. **C01** — aceitar e persistir `RequestSpec.qualification_profile` (campos do exemplo em `producer_example_request_spec.json`) e emitir `provenance.qualification_context` (`consumer_example_qualification_context.json`). Teste consumidor: `tests/comercial/c02/test_a01_a02_encomenda_evidence.py`.
2. **C05** — publicar catálogo versionado com `source_set_sha256` e `assess_qualification`; admitir ou recusar valor adotado distinto. Sem isso, perfis banco/seguradora permanecem `not_homologated` e a rota de custo não é oferecida como convertida de mercado.
3. **C03** — reproduzir no laudo o checklist/fingerprint e o pacote assinado importado; não recalcular grau na apresentação.
4. **C06 / P04** — seletor Playwright `text=1. Preparação da amostra` ainda encontra o alias visível na etapa de amostra; headings profissionais estão no percurso. Atualizar e2e para `Encomenda e perfil` / `Amostra e evidências` quando incorporar este HEAD.

## Mapeamento de estados (não emitir valores ilegais)

| Campanha (apresentação) | MP/1 `issuance.status` |
| --- | --- |
| analysis_only | draft |
| review_required | review_required |
| ready_for_professional_signoff | ready_for_professional_review |
| signed_integrity_verified | evento local; issuance permanece ready_for_professional_review |

Submissão/aceitação institucional são eventos separados. HTTP 200 local não é `institution_acceptance`.

## Limitações objetivas

- C01/C05 ainda não publicaram nesta BASE_SHA (`8d66c7973c659174e06d7223c9a9a8181e8eeabf`).
- Sem ato autorizado de banco/seguradora: objetivo institucional incompleto.
- Sem piloto humano: ganhos de rotina não são horas poupadas.
- GET `/projects/{id}/revisions` = 405 na BASE_SHA.
