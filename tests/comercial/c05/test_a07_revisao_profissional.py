"""C05-A07 — controle profissional e revisão independente (MP-QUAL/1).

Todos os valores ESPERADOS aqui são derivados à mão, das cláusulas da
ABNT NBR 14653-2:2011 e do contrato MP-QUAL/1:

  * Tabela 1 item 2: n >= 6(k+1) para o Grau III. Com k = 3, 6(3+1) = 24,
    portanto n = 24 é exatamente o mínimo do Grau III.
  * Tabela 1 item 4: sem extrapolação (todos os eixos quantitativos dentro
    de [min, max] amostral) => Grau III.
  * Tabela 1 item 5: pior p = 0,09 <= 10% => Grau III.
  * Tabela 1 item 6: p = 0,001 <= 1% => Grau III.
  * 9.2.1.6 b) + Tabela 2: seis itens no Grau III = 6 x 3 = 18 pontos,
    18 >= 16 e itens 2,4,5,6 no Grau III com 1 e 3 no mínimo no Grau II
    => fundamentação Grau III.
  * Tabela 5: amplitude 22,00% <= 30% => precisão Grau III; 45,00% > 40% e
    <= 50% => precisão Grau I (mudança material de grau de precisão).
  * Anexo A.2 a): n = 24 >= 3(3+1) = 12 e, para n <= 30, n_i >= 3; as
    contagens informadas (6 e 5) atendem.
  * Anexo A.2 c)–e): p > alpha (teto de 10% do Anexo A.3.1) não rejeita H0;
    A.2.1.4 exige pré-ordenamento declarado.
  * Anexo A.2 f)–i) e A.8: juízo profissional, exige registro COM
    justificativa (A.2.1.6 condiciona o ato à justificativa apresentada).

O objeto sob teste é o fluxo de liberação: assinatura e registro de autoria
comprovam autoria/integridade e NÃO validam conteúdo técnico.
"""

import pytest

from modules.nbr14653_validation import assess_normative
from modules.qualification_profile import (
    CASE_ANALYSIS_ONLY,
    CASE_READY_FOR_SIGNOFF,
    CASE_REVIEW_REQUIRED,
    CASE_SIGNED_INTEGRITY_VERIFIED,
    assess_qualification,
    result_fingerprint,
)

PROFILE_ID = "abnt-14653-2-regressao-mercado"
REPORT_FINGERPRINT = "a" * 64


def _profile(**over):
    prof = {"id": PROFILE_ID}
    prof.update(over)
    return prof


def _professional_finding(clause):
    return {
        "satisfied": True,
        "justification": f"exame de {clause} registrado e justificado no laudo",
    }


def _normative(**over):
    """Um caso tecnicamente íntegro: Grau III de fundamentação e de precisão."""
    ctx = {
        "n": 24,          # exatamente 6(k+1) com k = 3 -> Tabela 1 item 2 Grau III
        "k": 3,
        "intercept": True,
        "axes": [
            {"name": "area", "kind": "quantitative",
             "avaliando_value": 100.0, "sample_min": 80.0, "sample_max": 150.0},
            {"name": "frente", "kind": "quantitative",
             "avaliando_value": 12.0, "sample_min": 10.0, "sample_max": 20.0},
            {"name": "idade", "kind": "quantitative",
             "avaliando_value": 5.0, "sample_min": 1.0, "sample_max": 30.0},
        ],
        "pvalues": {"area": 0.01, "frente": 0.05, "idade": 0.09},
        "f_pvalue": 0.001,
        "amplitude_pct": 22.0,
        "grau_item1": 3,
        "item1_provenance": {"source": "matricula-12345.pdf"},
        "grau_item3": 3,
        "item3_provenance": {"source": "planilha-dados-mercado.csv"},
        "category_counts": {"esquina": 6, "frente_para_avenida": 5},
        "diagnostics": {
            "anexoA.2.c.homocedasticidade": {"p_value": 0.55},
            "anexoA.2.d.normalidade": {"p_value": 0.62},
            "anexoA.2.e.autocorrelacao": {"p_value": 0.48, "ordering_declared": True},
        },
        "professional_findings": {
            "anexoA.2.f.variaveis_relevantes": _professional_finding("A.2 f)"),
            "anexoA.2.g.multicolinearidade": _professional_finding("A.2 g)"),
            "anexoA.2.h.residuos_vs_independentes": _professional_finding("A.2 h)"),
            "anexoA.2.i.pontos_influenciantes": _professional_finding("A.2 i)"),
            "anexoA.8.agrupamentos": _professional_finding("A.8"),
        },
        "central_estimate": 500000.0,
        "mean_ci80": {"lower": 445000.0, "upper": 555000.0},
        "estimand": "valor_de_mercado",
        "adopted_estimator": "media",
    }
    ctx.update(over)
    return assess_normative(ctx)


def _profile_evidence():
    return {
        "9.2.1.1.a": "laudo-modalidade-completa.pdf",
        "9.2.1.1.b": "analise-do-modelo-e-elasticidades.pdf",
        "9.2.1.1.c": "enderecos-e-fontes-dos-dados.csv",
        "9.2.1.1.d": "estimativa-de-tendencia-central-adotada",
        "parte1.6.3.vistoria": "vistoria-2026-09-01-fotos.zip",
        "8.2.1.5.2.campo_suficiente": "nota-tecnica-campo-de-arbitrio.pdf",
        "10.1.laudo_completo": "laudo-completo-v3.pdf",
    }


def _context(assessment=None, **over):
    ctx = {
        "normative_assessment": assessment if assessment is not None else _normative(),
        "requested_minimum_grade": 3,
        "targets_grau_iii": True,
        "profile_evidence": _profile_evidence(),
        "report_content_fingerprint": REPORT_FINGERPRINT,
    }
    ctx.update(over)
    return ctx


def _review(fingerprint, **over):
    ev = {
        "professional_id": "CREA-SP 123456",
        "motive": "revisão técnica independente do modelo e da amostra",
        "version": "v3",
        "fingerprint": fingerprint,
    }
    ev.update(over)
    return ev


def _signature(fingerprint, **over):
    signature = {
        "integrity_verified": True,
        "result_fingerprint": fingerprint,
        "report_content_fingerprint": REPORT_FINGERPRINT,
        "unsigned_pdf_sha256": "b" * 64,
        "signed_pdf_sha256": "c" * 64,
    }
    signature.update(over)
    return signature


def _blocker_codes(block):
    return [b["code"] for b in block["release_blockers"]]


def _first_pass_fingerprint(ctx=None, profile=None):
    block = assess_qualification(ctx or _context(), profile or _profile())
    return block["result_fingerprint"]


# --------------------------------------------------------------------------
# O caso base é tecnicamente íntegro: os graus são os calculados à mão.
# --------------------------------------------------------------------------


def test_caso_base_atinge_grau_iii_de_fundamentacao_e_de_precisao():
    assessment = _normative()
    # 6 itens no Grau III = 18 pontos >= 16 (Tabela 2), itens 2,4,5,6 no III.
    assert assessment["fundamentacao"]["points"] == 18
    assert assessment["fundamentacao"]["grade"] == 3
    # Tabela 5: 22,00% <= 30%.
    assert assessment["precisao"]["grade"] == 3

    block = assess_qualification(_context(assessment), _profile())
    assert block["calculation_status"] == "ok"
    assert block["achieved_fundamentacao_grade"] == 3
    assert block["grade_requirement_status"] == "met"


# --------------------------------------------------------------------------
# Sem ato humano evidenciado não há liberação: pendência não é aprovação.
# --------------------------------------------------------------------------


def test_sem_evidencia_profissional_nao_fica_pronto_para_assinatura():
    assessment = _normative(professional_findings={})
    ctx = {"normative_assessment": assessment, "requested_minimum_grade": 3}
    block = assess_qualification(ctx, _profile())

    assert block["case_release_status"] == CASE_REVIEW_REQUIRED
    assert block["case_release_status"] != CASE_READY_FOR_SIGNOFF
    pending = set(block["pending_manual_rules"])
    # Requisitos do perfil que exigem ato humano evidenciado.
    assert {"parte1.6.3.vistoria", "8.2.1.5.2.campo_suficiente",
            "10.1.laudo_completo"} <= pending
    # Pressupostos do Anexo A.2 f)-i) e A.8: juízo profissional sem registro.
    assert {"anexoA.2.f.variaveis_relevantes", "anexoA.2.g.multicolinearidade",
            "anexoA.2.h.residuos_vs_independentes",
            "anexoA.2.i.pontos_influenciantes", "anexoA.8.agrupamentos"} <= pending


def test_caso_bom_sem_revisao_registrada_para_em_review_required():
    block = assess_qualification(_context(), _profile())
    assert block["release_blockers"] == []
    assert block["pending_manual_rules"] == []
    # Nada bloqueia tecnicamente, mas falta o ato de revisão.
    assert block["case_release_status"] == CASE_REVIEW_REQUIRED
    assert block["case_release_status"] != CASE_READY_FOR_SIGNOFF


# --------------------------------------------------------------------------
# Um checkbox não é uma revisão: cada omissão invalida o evento.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("omitted", ["professional_id", "motive", "version"])
def test_revisao_sem_campo_obrigatorio_nao_conta_como_revisao(omitted):
    fingerprint = _first_pass_fingerprint()
    event = _review(fingerprint)
    del event[omitted]

    block = assess_qualification(_context(review_events=[event]), _profile())

    assert block["case_release_status"] == CASE_REVIEW_REQUIRED
    assert block["case_release_status"] != CASE_READY_FOR_SIGNOFF
    # O evento não é "obsoleto" (o fingerprint bate); ele simplesmente não é
    # uma revisão válida. E o histórico é preservado tal como recebido.
    assert block["stale_review_events"] == []
    assert block["review_events"] == [event]


def test_revisao_sem_fingerprint_algum_nao_conta_como_revisao():
    fingerprint = _first_pass_fingerprint()
    event = _review(fingerprint)
    del event["fingerprint"]

    block = assess_qualification(_context(review_events=[event]), _profile())

    assert block["case_release_status"] == CASE_REVIEW_REQUIRED
    assert block["stale_review_events"] == []


def test_valid_true_sozinho_nao_lava_evento_incompleto_e_valid_false_e_respeitado():
    fingerprint = _first_pass_fingerprint()
    merely_flagged = {"valid": True, "fingerprint": fingerprint}
    explicitly_invalid = _review(fingerprint, valid=False)

    block = assess_qualification(
        _context(review_events=[merely_flagged, explicitly_invalid]), _profile()
    )

    assert block["case_release_status"] == CASE_REVIEW_REQUIRED
    assert block["review_events"] == [merely_flagged, explicitly_invalid]
    assert block["stale_review_events"] == []


def test_revisao_sobre_outro_fingerprint_nao_conta_e_fica_registrada_como_obsoleta():
    event = _review("0" * 64)
    block = assess_qualification(_context(review_events=[event]), _profile())

    assert block["case_release_status"] == CASE_REVIEW_REQUIRED
    assert block["stale_review_events"] == [event]
    assert "review_invalidated_by_material_change" in _blocker_codes(block)


# --------------------------------------------------------------------------
# Protocolo de duas passadas.
# --------------------------------------------------------------------------


def test_protocolo_de_duas_passadas_chega_a_assinado_com_integridade_verificada():
    ctx = _context()
    first = assess_qualification(ctx, _profile())
    fingerprint = first["result_fingerprint"]
    assert isinstance(fingerprint, str) and len(fingerprint) == 64
    assert first["case_release_status"] == CASE_REVIEW_REQUIRED

    review = _review(fingerprint)
    second = assess_qualification(_context(review_events=[review]), _profile())
    assert second["case_release_status"] == CASE_READY_FOR_SIGNOFF
    # Registrar uma revisão não é mudança material: o fingerprint não muda.
    assert second["result_fingerprint"] == fingerprint

    third = assess_qualification(
        _context(review_events=[review], signature=_signature(fingerprint)),
        _profile(),
    )
    assert third["case_release_status"] == CASE_SIGNED_INTEGRITY_VERIFIED
    assert third["result_fingerprint"] == fingerprint
    assert third["release_blockers"] == []


def test_assinatura_sem_revisao_valida_nao_produz_assinado():
    fingerprint = _first_pass_fingerprint()
    block = assess_qualification(
        _context(signature=_signature(fingerprint)),
        _profile(),
    )
    assert block["case_release_status"] == CASE_REVIEW_REQUIRED
    assert block["case_release_status"] != CASE_SIGNED_INTEGRITY_VERIFIED


def test_assinatura_sem_integridade_verificada_nao_produz_assinado():
    fingerprint = _first_pass_fingerprint()
    block = assess_qualification(
        _context(review_events=[_review(fingerprint)],
                 signature=_signature(fingerprint, integrity_verified=False)),
        _profile(),
    )
    assert block["case_release_status"] == CASE_READY_FOR_SIGNOFF
    assert block["case_release_status"] != CASE_SIGNED_INTEGRITY_VERIFIED


def test_assinatura_sobre_outro_fingerprint_nunca_e_aceita_como_assinada():
    fingerprint = _first_pass_fingerprint()
    block = assess_qualification(
        _context(review_events=[_review(fingerprint)],
                 signature=_signature("f" * 64)),
        _profile(),
    )
    assert block["case_release_status"] == CASE_REVIEW_REQUIRED
    assert block["case_release_status"] != CASE_SIGNED_INTEGRITY_VERIFIED
    assert "signature_stale" in _blocker_codes(block)


# --------------------------------------------------------------------------
# Mudança material invalida as decisões dependentes sem apagar o histórico.
# --------------------------------------------------------------------------


def _signed_baseline():
    fingerprint = _first_pass_fingerprint()
    review = _review(fingerprint)
    signature = _signature(fingerprint)
    signed = assess_qualification(
        _context(review_events=[review], signature=signature), _profile()
    )
    assert signed["case_release_status"] == CASE_SIGNED_INTEGRITY_VERIFIED
    return fingerprint, review, signature


def test_mudanca_de_amplitude_da_precisao_invalida_revisao_e_assinatura():
    fingerprint, review, signature = _signed_baseline()

    # Tabela 5: 22,00% era Grau III; 45,00% > 40% e <= 50% é Grau I.
    changed = _normative(amplitude_pct=45.0)
    assert changed["precisao"]["grade"] == 1

    block = assess_qualification(
        _context(changed, review_events=[review], signature=signature), _profile()
    )
    assert block["result_fingerprint"] != fingerprint
    assert block["case_release_status"] != CASE_SIGNED_INTEGRITY_VERIFIED
    assert block["case_release_status"] == CASE_REVIEW_REQUIRED
    # Histórico preservado, não apagado.
    assert block["stale_review_events"] == [review]
    assert block["review_events"] == [review]
    assert _blocker_codes(block) == ["review_invalidated_by_material_change"]
    stale = [b for b in block["release_blockers"]
             if b["code"] == "review_invalidated_by_material_change"][0]
    assert stale["stale_fingerprints"] == [fingerprint]


def test_mudanca_de_n_invalida_revisao_mesmo_sem_mudar_o_grau():
    fingerprint, review, signature = _signed_baseline()

    # n = 30 continua >= 6(k+1) = 24 e minimum_ni(30) segue 3: o grau não muda,
    # mas a amostra mudou, portanto a decisão dependente cai.
    changed = _normative(n=30)
    assert changed["fundamentacao"]["grade"] == 3

    block = assess_qualification(
        _context(changed, review_events=[review], signature=signature), _profile()
    )
    assert block["result_fingerprint"] != fingerprint
    assert block["case_release_status"] != CASE_SIGNED_INTEGRITY_VERIFIED
    assert block["stale_review_events"] == [review]
    assert "review_invalidated_by_material_change" in _blocker_codes(block)


def test_mudanca_de_k_invalida_revisao():
    fingerprint, review, signature = _signed_baseline()

    # k = 2 com n = 24: 24 >= 6(2+1) = 18, segue Grau III no item 2.
    changed = _normative(k=2, pvalues={"area": 0.01, "frente": 0.05})
    assert changed["fundamentacao"]["grade"] == 3

    block = assess_qualification(
        _context(changed, review_events=[review], signature=signature), _profile()
    )
    assert block["result_fingerprint"] != fingerprint
    assert block["case_release_status"] != CASE_SIGNED_INTEGRITY_VERIFIED
    assert block["stale_review_events"] == [review]
    assert "review_invalidated_by_material_change" in _blocker_codes(block)


def test_mudanca_de_proveniencia_documental_invalida_revisao():
    fingerprint, review, signature = _signed_baseline()

    # Mesmo grau documental declarado, outro documento de origem.
    changed = _normative(item1_provenance={"source": "matricula-99999-retificada.pdf"})
    assert changed["fundamentacao"]["grade"] == 3

    block = assess_qualification(
        _context(changed, review_events=[review], signature=signature), _profile()
    )
    assert block["result_fingerprint"] != fingerprint
    assert block["case_release_status"] != CASE_SIGNED_INTEGRITY_VERIFIED
    assert block["stale_review_events"] == [review]
    assert "review_invalidated_by_material_change" in _blocker_codes(block)


def test_nova_revisao_sobre_o_novo_fingerprint_restaura_o_fluxo():
    _signed_baseline()
    changed = _normative(amplitude_pct=45.0)
    new_fingerprint = assess_qualification(
        _context(changed), _profile()
    )["result_fingerprint"]

    block = assess_qualification(
        _context(changed,
                 review_events=[_review(new_fingerprint)],
                 signature=_signature(new_fingerprint)),
        _profile(),
    )
    assert block["case_release_status"] == CASE_SIGNED_INTEGRITY_VERIFIED


# --------------------------------------------------------------------------
# Assinatura não valida conteúdo técnico.
# --------------------------------------------------------------------------


def test_assinatura_valida_nao_libera_caso_com_regra_decisiva_reprovada():
    # Tabela 1 item 6: p = 0,20 > 5% reprova até o Grau I -> item 6 grau 0,
    # e sem o item 6 a fundamentação não é classificada (Tabela 2).
    failed = _normative(f_pvalue=0.2)
    assert failed["fundamentacao"]["grade"] is None

    ctx = _context(failed)
    fingerprint = assess_qualification(ctx, _profile())["result_fingerprint"]

    block = assess_qualification(
        _context(failed,
                 review_events=[_review(fingerprint)],
                 signature=_signature(fingerprint)),
        _profile(),
    )
    assert block["case_release_status"] == CASE_ANALYSIS_ONLY
    assert block["case_release_status"] != CASE_SIGNED_INTEGRITY_VERIFIED
    assert block["case_release_status"] != CASE_READY_FOR_SIGNOFF
    decisive = [b for b in block["release_blockers"]
                if b["code"] == "decisive_rule_not_satisfied"]
    assert [b["rule_id"] for b in decisive] == ["tabela1.item6"]
    assert "grade_pending" in _blocker_codes(block)


def test_perfil_desconhecido_com_assinatura_valida_segue_analysis_only():
    ctx = _context()
    unknown = _profile(id="perfil-que-nao-existe")
    fingerprint = assess_qualification(ctx, unknown)["result_fingerprint"]
    block = assess_qualification(
        _context(review_events=[_review(fingerprint)],
                 signature=_signature(fingerprint)),
        unknown,
    )
    assert block["case_release_status"] == CASE_ANALYSIS_ONLY


# --------------------------------------------------------------------------
# Estabilidade e sensibilidade do result_fingerprint.
# --------------------------------------------------------------------------


def test_fingerprint_e_estavel_para_entrada_identica():
    first = assess_qualification(_context(), _profile())["result_fingerprint"]
    second = assess_qualification(_context(), _profile())["result_fingerprint"]
    assert first == second


def test_fingerprint_muda_com_a_versao_do_perfil_e_com_o_source_set_sha256():
    base = {
        "profile_id": PROFILE_ID,
        "profile_version": "1.0.0",
        "source_set_sha256": "a" * 64,
        "rule_results": [{"rule_id": "tabela1.item2", "status": "passed", "observed": 3}],
        "grade": 3,
    }
    other_version = dict(base, profile_version="2.0.0")
    other_sources = dict(base, source_set_sha256="b" * 64)

    assert result_fingerprint(base) == result_fingerprint(dict(base))
    assert result_fingerprint(other_version) != result_fingerprint(base)
    assert result_fingerprint(other_sources) != result_fingerprint(base)
    assert result_fingerprint(other_version) != result_fingerprint(other_sources)


def test_versao_de_perfil_inexistente_nao_resolve_e_muda_o_fingerprint():
    resolved = assess_qualification(_context(), _profile())
    mismatched = assess_qualification(_context(), _profile(version="9.9.9"))

    assert mismatched["result_fingerprint"] != resolved["result_fingerprint"]
    assert mismatched["profile"]["resolved"] is False
    assert "profile_unknown" in _blocker_codes(mismatched)
    assert mismatched["case_release_status"] == CASE_ANALYSIS_ONLY
