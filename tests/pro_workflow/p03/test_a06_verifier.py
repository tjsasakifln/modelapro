"""P03-A06: verifier flags mutated value/unit/grau/annex line/equation, not the original."""

from __future__ import annotations

from modules.report_presenter.verifier import verify_report_consistency
from modules.results_generator import render_report
from tests.c08_report.fixtures import known_context, known_snapshot
from tests.c08_report.pdf_text import extract_pdf_text
from tests.pro_workflow.p03.fixtures import snapshot_without_formula


def test_p03_a06_verifier_flags_each_mutation_only():
    snapshot = snapshot_without_formula()
    context = known_context()
    pdf = render_report(snapshot, context)
    text = extract_pdf_text(pdf)
    clean = verify_report_consistency(pdf, snapshot, context, extracted_text=text)
    assert clean["ok"] is True
    assert clean["findings"] == []

    value_text = text.replace("MP1_POINT=350000", "MP1_POINT=999999")
    value_findings = verify_report_consistency(pdf, snapshot, context, extracted_text=value_text)
    assert any(f["code"] == "MUTATED_VALUE" for f in value_findings["findings"])

    unit_text = text.replace("MP1_TARGET_UNIT=BRL", "MP1_TARGET_UNIT=XYZ")
    unit_findings = verify_report_consistency(pdf, snapshot, context, extracted_text=unit_text)
    assert any(f["code"] == "MUTATED_UNIT" for f in unit_findings["findings"])

    grau_text = text.replace("MP1_FUNDAMENTACAO_GRADE=2", "MP1_FUNDAMENTACAO_GRADE=1")
    grau_snap = dict(snapshot)
    grau_html = verify_report_consistency(pdf, snapshot, context, extracted_text=grau_text)
    assert any(f["code"] == "MUTATED_GRAU" for f in grau_html["findings"])

    omitted_text = text.replace("used-0001", "omitido-0001").replace("used-0030", "omitido-0030")
    omitted = verify_report_consistency(pdf, snapshot, context, extracted_text=omitted_text)
    assert any(f["code"] == "OMITTED_ANNEX_LINE" for f in omitted["findings"])

    eq_text = text
    for token in ("1234.56789012345", "1234.567890", "area"):
        eq_text = eq_text.replace(token, "MUTATED_EQ")
    incoherent = verify_report_consistency(pdf, snapshot, context, extracted_text=eq_text)
    assert any(f["code"] == "INCOHERENT_EQUATION" for f in incoherent["findings"])

    codes = {
        "value": {f["code"] for f in value_findings["findings"]},
        "unit": {f["code"] for f in unit_findings["findings"]},
        "grau": {f["code"] for f in grau_html["findings"]},
        "omitted": {f["code"] for f in omitted["findings"]},
        "equation": {f["code"] for f in incoherent["findings"]},
    }
    assert "MUTATED_VALUE" in codes["value"]
    assert "MUTATED_UNIT" in codes["unit"]
    assert "MUTATED_GRAU" in codes["grau"]
    assert "OMITTED_ANNEX_LINE" in codes["omitted"]
    assert "INCOHERENT_EQUATION" in codes["equation"]
