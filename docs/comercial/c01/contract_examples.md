# Exemplos produtor/consumidor (extensão aditiva MP-QUAL/1)

Schema raiz permanece `MP/1`. Não há segundo snapshot.

## RequestSpec (produtor C01, consumidor C02)

Campo opcional aditivo:

```json
{
  "schema_version": "MP/1",
  "qualification_profile": {
    "id": "market.urban.comparative",
    "version": "1",
    "source_set_sha256": null,
    "purpose": "professional_report",
    "value_basis": "market",
    "method": "comparative_regression",
    "asset_scope": "urban_residential",
    "recipient_id": "internal-review"
  },
  "cost_bom": null
}
```

C02 escolhe perfis conhecidos; não escreve regras. C01 valida estrutura e resolve. Perfil desconhecido não é 500: o cálculo pode seguir como análise.

## ResultSnapshot.provenance.qualification_context (produtor C01, consumidor C03)

```json
{
  "schema_version": "MP-QUAL/1",
  "profile": {"id": "market.urban.comparative", "version": "1"},
  "result_fingerprint": "hex-sha256",
  "calculation_status": "fitted",
  "grade_requirement_status": "not_met",
  "case_release_status": "analysis_only",
  "rule_results": [
    {
      "rule_id": "c01.numeric_fit",
      "source_id": "c01.engine",
      "edition_or_version": "MP-COM/2",
      "clause": "",
      "applicability": "applicable",
      "status": "passed",
      "observed": {"calculation_status": "fitted"},
      "criterion_ref": "c01.numeric_fit",
      "evidence_refs": ["model.diagnostics"],
      "explanation": "Numeric/technical fit of the comparative-regression engine."
    }
  ],
  "review_events": [],
  "institution_acceptance": null
}
```

C03 deste lote apresenta; não recalcula grau. `unverified` nunca é persistido como `passed`.

## Mapeamento de emissão

| case_release_status | validation.issuance.status (MP/1 existente) |
| --- | --- |
| analysis_only | draft |
| review_required | review_required |
| ready_for_professional_signoff | ready_for_professional_review |
| signed_integrity_verified | ready_for_professional_review + evento de assinatura no qualification_context |

Valores monetários permanecem em `value.*` com `basis` / `target.estimand` / `target.unit`.
