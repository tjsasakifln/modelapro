"""Cost order consumer: the same persisted job/document lifecycle, no fake sample."""
from __future__ import annotations

import hashlib
import json

from .forms import (
    _qualification_evidence_widgets,
    _vistoria_and_identity_widgets,
    build_request_spec,
)
from .professional import select_qualification_profile


def build_cost_order(*, bom, applicant, rights, inspection_date, inspection,
                     identity, evidence, minimum_grade, synthetic_test_only):
    """Serialize explicit inputs; the backend alone computes and qualifies cost."""
    profile = select_qualification_profile("abnt-14653-2-custo-reedicao")
    if profile.get("resolved") is not True:
        raise ValueError("Perfil de custo não resolvido no catálogo instalado.")
    spec = build_request_spec(
        target_col="", candidate_cols=[], roles={}, units={},
        target_unit=bom.get("currency"), reference_date=bom.get("reference_date"),
        inspection_date=inspection_date, applicant=applicant, rights=rights,
        purpose=profile["purpose"], value_basis=profile["value_basis"],
        asset_scope=profile["asset_scope"], qualification_profile=profile,
        minimum_fundamentacao_grade=minimum_grade,
        profile_evidence=evidence.get("profile_evidence"),
        professional_findings=evidence.get("professional_findings"),
        synthetic_test_only=synthetic_test_only,
    )
    spec.update(cost_bom=bom, inspection=inspection, professional_identity=identity)
    return spec


def cost_form():
    import streamlit as st

    profile = select_qualification_profile("abnt-14653-2-custo-reedicao")
    st.subheader("Encomenda por quantificação de custo")
    st.caption(f"{profile.get('label')} · versão {profile.get('version')}")
    st.caption("Custo não é valor de mercado nem limite de garantia. O cálculo não atesta aceite de seguradora.")
    if profile.get("block_reason"):
        st.warning(profile["block_reason"] + " O cálculo exploratório preserva esta pendência na emissão.")
    applicant = st.text_input("Solicitante do custo", key="cost_applicant")
    rights = st.text_input("Direitos avaliados no custo", key="cost_rights")
    synthetic = st.checkbox("Caso de custo SINTÉTICO DE TESTE — não é evidência externa", key="cost_synthetic")
    location = st.text_input("Localidade de referência do custo", key="cost_location")
    reference = st.date_input("Data-base do custo", value=None, key="cost_reference")
    inspection_date = st.date_input("Data da vistoria do custo", value=None, key="cost_inspection_date")
    currency = st.selectbox("Moeda do orçamento", ["", "BRL"], key="cost_currency")
    grade = st.selectbox("Grau mínimo solicitado no custo", [None, 1, 2, 3], key="cost_grade")
    date_text = reference.isoformat() if reference else None
    direct_mode = st.selectbox("Origem do custo direto", ["synthetic_budget", "cub_similar", "cub_adjusted"],
                              format_func=lambda x: {"synthetic_budget": "Orçamento sintético (não significa dado fictício)",
                                                     "cub_similar": "CUB — projeto semelhante",
                                                     "cub_adjusted": "CUB — projeto diferente com ajustes"}[x])
    source_ref = st.text_input("Fonte documental do custo direto", key="cost_source")
    direct_justification = st.text_area("Justificativa do orçamento / semelhança / ajustes", key="cost_direct_why")
    st.caption("Cada linha tem fonte, data, moeda e unidade próprias. Terreno e exclusões permanecem discriminados.")
    rows = st.data_editor(
        [{"item_id": "", "description": "", "category": "building_component", "quantity": None,
          "unit": "", "unit_cost": None, "currency": "", "reference_date": "", "source": ""}],
        num_rows="dynamic", key="cost_items", use_container_width=True,
        column_config={"category": st.column_config.SelectboxColumn(
            "Categoria", options=["building_component", "additional_expense", "land", "exclusion"]),
            "quantity": st.column_config.NumberColumn("Quantidade", min_value=0.0),
            "unit_cost": st.column_config.NumberColumn("Custo unitário", min_value=0.0)},
    )
    bdi_mode = st.selectbox("BDI — método", ["calculated", "justified", "arbitrated"], key="cost_bdi_mode")
    bdi_rate = st.number_input("BDI — taxa (fração: 0,10 = 10%)", value=None, min_value=0.0, key="cost_bdi_rate")
    bdi_why = st.text_area("BDI — justificativa", key="cost_bdi_why")
    bdi_source = st.text_input("BDI — fonte", key="cost_bdi_source")
    bdi_components = st.text_area("BDI calculado — componentes (objeto JSON conforme memória de cálculo)",
                                  value="{}", key="cost_bdi_components")
    bdi_formula = st.selectbox("BDI calculado — composição", ["additive", "compound"], key="cost_bdi_formula")
    st.caption("Componentes: nome → taxa em fração. A soma ou composição deve reproduzir a taxa BDI informada.")
    depreciation_mode = st.selectbox("Depreciação — método", ["recovery_cost", "new_asset", "technical_method", "arbitrated"],
                                     key="cost_dep_mode")
    depreciation_rate = st.number_input("Depreciação — taxa (fração)", value=None, min_value=0.0, max_value=1.0,
                                        key="cost_dep_rate")
    depreciation_method = st.text_input("Método técnico de depreciação", key="cost_dep_method")
    age = st.number_input("Idade (anos)", value=None, min_value=0.0, key="cost_age")
    useful_life = st.number_input("Vida útil (anos)", value=None, min_value=0.0, key="cost_life")
    condition = st.text_input("Estado de conservação", key="cost_condition")
    depreciation_why = st.text_area("Depreciação — justificativa / recuperação", key="cost_dep_why")
    depreciation_source = st.text_input("Depreciação — fonte", key="cost_dep_source")
    actual = _vistoria_and_identity_widgets(ns="cost", inspection_date=inspection_date.isoformat() if inspection_date else None)
    evidence = _qualification_evidence_widgets(ns="cost", profile=profile)
    source = {"reference": source_ref, "reference_date": date_text, "location": location}
    if synthetic:
        source["synthetic_test_only"] = True
    blocking = []
    spec = None
    try:
        components = json.loads(bdi_components)
        if not isinstance(components, dict):
            raise ValueError("Componentes de BDI devem ser um objeto JSON.")
        bom = {"schema_version": "MP-COST-BOM/1", "reference_location": location,
               "reference_date": date_text, "currency": currency,
               "direct_cost": {"mode": direct_mode, "source": source, "justification": direct_justification},
               "items": rows,
               "bdi": {"mode": bdi_mode, "rate": bdi_rate, "components": components, "formula": bdi_formula,
                       "justification": bdi_why, "source": bdi_source},
               "depreciation": {"mode": depreciation_mode, "rate": depreciation_rate,
                                "method": depreciation_method, "age": age, "useful_life": useful_life,
                                "condition": condition, "justification": depreciation_why, "source": depreciation_source}}
        if not applicant.strip() or not rights.strip() or not reference or not currency or not source_ref.strip():
            raise ValueError("Informe solicitante, direitos, data-base, moeda e fonte do custo.")
        spec = build_cost_order(bom=bom, applicant=applicant, rights=rights,
                                inspection_date=inspection_date.isoformat() if inspection_date else None,
                                inspection=actual["inspection"], identity=actual["identity"], evidence=evidence,
                                minimum_grade=grade, synthetic_test_only=synthetic)
        from modules.result_contract import validate_request_spec
        validate_request_spec(spec)
    except (ValueError, TypeError) as exc:
        blocking.append({"message": str(exc)})
    for item in blocking:
        st.info(item["message"])
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True, allow_nan=False).encode()).hexdigest() if spec else None
    return {"cost_mode": True, "request_spec": spec, "subject": None, "uploaded_file": None,
            "qualification_profile": profile, "dispatch": {"ok": not blocking, "blocking": blocking},
            "fingerprint": fingerprint, "execute": st.button("Calcular custo", disabled=bool(blocking))}
