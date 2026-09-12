"""NBR 14653-2:2011 validation: assess_normative + legacy adapters.

Public MP/1 export: assess_normative(context) -> NormativeAssessment.

NBRValidator keeps the previous public methods as adapters. Item 4 no longer
approves Grau II/I from the extended measure interval alone.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .config_manager import config
from .results import ItemScore, ModelResult, ValidationResult
from . import normative_rules as rules


def assess_normative(context: Mapping[str, Any]) -> Dict[str, Any]:
    """MP/1 C03 entry point.

    context keys (all optional except that item 4 needs axes or
    extrapolation_details plus, when extrapolated, predict_original):

      n, k, intercept
      sample (mapping with used)
      axes or extrapolation_details
      subject_raw
      predict_original(subject_raw) -> original-unit point estimate
      pvalues, f_pvalue
      amplitude_pct
      value / central_estimate / mean_ci80 / prediction_interval / ci_lower, ci_upper
      estimand, adopted_estimator
      documentary / grau_item1 / grau_item3 / item1_provenance / item3_provenance
      statistical (r2, vif, automatic_selection, ...)
      target_degree
    """
    ctx = dict(context or {})
    issues: List[Dict[str, Any]] = []

    nk = rules.resolve_effective_n_k(ctx, X=ctx.get("X"), y=ctx.get("y"))
    issues.extend(nk["issues"])
    n, k, intercept = nk["n"], nk["k"], nk["intercept"]

    axes = _axes_from_context(ctx)
    subject_raw = ctx.get("subject_raw")
    predict_original = ctx.get("predict_original")

    item2 = rules.classify_item2_quantidade_dados(n, k)
    item4 = rules.classify_item4_extrapolacao(
        axes,
        subject_raw=subject_raw,
        predict_original=predict_original,
    )
    item5 = rules.classify_item5_significancia_regressores(
        ctx.get("pvalues") or {},
        automatic_selection=bool(
            (ctx.get("statistical") or {}).get("automatic_selection")
            or ctx.get("automatic_selection")
        ),
    )
    item6 = rules.classify_item6_significancia_global(ctx.get("f_pvalue"))

    doc = ctx.get("documentary") if isinstance(ctx.get("documentary"), Mapping) else {}
    item1_decl = _doc_grade(doc, ctx, 1, "grau_item1")
    item3_decl = _doc_grade(doc, ctx, 3, "grau_item3")
    item1_prov = _doc_provenance(doc, ctx, 1, "item1_provenance")
    item3_prov = _doc_provenance(doc, ctx, 3, "item3_provenance")

    item1 = rules.classify_documentary_item(
        1, item1_decl, item1_prov, description="Caracterização do imóvel avaliando"
    )
    item3 = rules.classify_documentary_item(
        3, item3_decl, item3_prov, description="Identificação dos dados de mercado"
    )

    items = [
        _item_payload(1, "Caracterização do imóvel avaliando", item1),
        _item_payload(2, "Quantidade mínima de dados de mercado", item2),
        _item_payload(3, "Identificação dos dados de mercado", item3),
        _item_payload(4, "Extrapolação", item4),
        _item_payload(5, "Nível de significância dos regressores (teste t)", item5),
        _item_payload(6, "Nível de significância do modelo global (teste F)", item6),
    ]

    scores = {it["item"]: it["grade"] for it in items}
    fund = rules.classify_fundamentacao(scores)

    precisao = rules.classify_precisao(ctx.get("amplitude_pct"))

    value_block = ctx.get("value") if isinstance(ctx.get("value"), Mapping) else {}
    mean_ci80 = ctx.get("mean_ci80") or value_block.get("mean_ci80")
    if mean_ci80 is None and ctx.get("ci_lower") is not None and ctx.get("ci_upper") is not None:
        mean_ci80 = {"lower": ctx.get("ci_lower"), "upper": ctx.get("ci_upper")}
    prediction_interval = ctx.get("prediction_interval") or value_block.get("prediction_interval")
    central = (
        ctx.get("central_estimate")
        if ctx.get("central_estimate") is not None
        else value_block.get("point")
    )
    estimand = ctx.get("estimand")
    target = ctx.get("target")
    if estimand is None and isinstance(target, Mapping):
        estimand = target.get("estimand")
    intervals = rules.interval_roles(
        central_estimate=central,
        mean_ci80=mean_ci80,
        prediction_interval=prediction_interval,
        estimand=estimand,
        adopted_estimator=ctx.get("adopted_estimator"),
        campo_arbitrio=float(getattr(config, "CAMPO_ARBITRIO", rules.CAMPO_ARBITRIO)),
    )

    for iss in item4.get("issues") or []:
        issues.append(iss)
    if item2.get("evidence_status") == rules.EVIDENCE_PENDING:
        issues.append(
            rules.make_issue(
                "item2_pending",
                item2.get("detail") or "item 2 pendente",
                affected_ids=["item2"],
            )
        )
    if item5.get("limitations"):
        for lim in item5["limitations"]:
            issues.append(
                rules.make_issue(
                    "inference_limitation",
                    lim,
                    severity="info",
                    affected_ids=["item5"],
                )
            )

    # MP-COM/C05: Anexo A.2 a) micronumerosidade and Anexo A.2 c)-i)/A.3.1
    # pressupostos. Neither awards points nor raises a grade; both can only
    # expose a violation or stay pending. Absence is never conformity.
    micro = rules.classify_micronumerosidade(
        n, k, ctx.get("category_counts") if isinstance(ctx.get("category_counts"), Mapping) else None
    )
    if micro["status"] == rules.MICRO_VIOLATED:
        for v in micro["violations"]:
            issues.append(
                rules.make_issue(
                    "micronumerosidade",
                    v["detail"],
                    severity="error",
                    affected_ids=["anexoA.2.micronumerosidade"],
                )
            )
    elif micro["status"] == rules.MICRO_PENDING:
        issues.append(
            rules.make_issue(
                "micronumerosidade_pending",
                micro["detail"],
                affected_ids=["anexoA.2.micronumerosidade"],
            )
        )

    diagnostics = ctx.get("diagnostics") if isinstance(ctx.get("diagnostics"), Mapping) else {}
    findings = ctx.get("professional_findings") if isinstance(ctx.get("professional_findings"), Mapping) else {}
    pressupostos: List[Dict[str, Any]] = []
    for spec in rules.PRESSUPOSTOS:
        pid = spec["id"]
        block = diagnostics.get(pid) if isinstance(diagnostics.get(pid), Mapping) else {}
        pressupostos.append(
            rules.evaluate_pressuposto(
                pid,
                p_value=block.get("p_value"),
                alpha=block.get("alpha"),
                ordering_declared=block.get("ordering_declared"),
                professional_finding=findings.get(pid),
            )
        )
    model_use_prohibited: List[Dict[str, Any]] = []
    for pr in pressupostos:
        if pr["status"] == rules.PRESSUPOSTO_VIOLATED:
            spec = rules.PRESSUPOSTOS_BY_ID.get(pr["id"]) or {}
            if spec.get("blocks_use_when_incoherent"):
                # Anexo A.2 g) is the only clause in this block that VEDA the
                # use of the model. It must not be reported with the same code
                # as an ordinary violated assumption, or nothing can act on it.
                model_use_prohibited.append({
                    "rule_id": pr["id"],
                    "clause": pr["clause"],
                    "prohibition": spec.get("prohibition"),
                    "detail": pr["detail"],
                })
                issues.append(
                    rules.make_issue(
                        "model_use_prohibited",
                        (
                            f"{pr['clause']}: {spec.get('prohibition')}. "
                            f"{pr['detail']}"
                        ),
                        severity="error",
                        affected_ids=[pr["id"]],
                    )
                )
                continue
            issues.append(
                rules.make_issue(
                    "pressuposto_violado",
                    pr["detail"],
                    severity="error",
                    affected_ids=[pr["id"]],
                )
            )
        elif pr["status"] in (rules.PRESSUPOSTO_PENDING, rules.PRESSUPOSTO_PROFESSIONAL):
            issues.append(
                rules.make_issue(
                    "pressuposto_pendente",
                    pr["detail"],
                    affected_ids=[pr["id"]],
                )
            )

    stat_warns = rules.statistical_warnings(
        ctx.get("statistical"),
        significance_aux=float(getattr(config, "SIGNIFICANCE_LEVEL_AUX", 0.10)),
        vif_convention=float(getattr(config, "MAX_VIF", 10.0)),
    )
    statistical = {
        "warnings": stat_warns,
        "vif_violation": any("VIF" in w for w in stat_warns),
        "n": n,
        "k": k,
        "intercept": intercept,
        "k_source": nk.get("k_source"),
        "automatic_selection": bool(
            (ctx.get("statistical") or {}).get("automatic_selection")
            or ctx.get("automatic_selection")
        ),
        "note": (
            "Diagnósticos estatísticos (R², VIF, normalidade, homocedasticidade) "
            "acompanham o grau e não são corte normativo da Tabela 1/2."
        ),
    }

    documentary = {
        "item1": {
            "grade": item1.get("grade"),
            "evidence_status": item1.get("evidence_status"),
            "provenance": item1.get("provenance"),
            "detail": item1.get("detail"),
        },
        "item3": {
            "grade": item3.get("grade"),
            "evidence_status": item3.get("evidence_status"),
            "provenance": item3.get("provenance"),
            "detail": item3.get("detail"),
        },
        "note": (
            "Pontuação documental declarada não se torna verificada por um selectbox. "
            "Proveniência é obrigatória para qualquer pretensão de evidência."
        ),
    }

    issues.append(
        rules.make_issue(
            "grau_nao_e_emissao",
            "O grau calculado (fundamentação/precisão) não autoriza emissão automática "
            "de laudo. issuance permanece a cargo do profissional (C10: draft / "
            "review_required / ready_for_professional_review).",
            severity="info",
        )
    )

    pending_calculated = [
        it
        for it in items
        if it["item"] in (2, 4, 5, 6)
        and it["evidence_status"] == rules.EVIDENCE_PENDING
    ]
    if pending_calculated:
        verification_status = (
            rules.VS_PENDING
            if len(pending_calculated) == 4
            else rules.VS_PARTIAL
        )
    else:
        verification_status = rules.VS_VERIFIED_RULES_LISTED

    rule_sources = [
        {
            "id": r["id"],
            "edition": r["edition"],
            "item": r.get("item"),
            "clause": r["clause"],
            "status": r["verification_status"],
            "destination": r.get("destination", "automatic"),
        }
        for r in rules.RULE_MATRIX
    ]
    rule_sources.extend(
        {
            "id": r["id"],
            "edition": rules.EDITION_PART2,
            "clause": r["clause"],
            "status": "unverified",
            "destination": r.get("destination"),
            "reason": r["reason"],
        }
        for r in rules.UNVERIFIED_RULES
    )

    fundamentacao = {
        "grade": fund["grade"],
        "points": fund["points"],
        "items": items,
        "detail": fund["detail"],
        "pending_items": fund.get("pending_items") or [],
    }
    precisao_out = {
        "status": precisao["status"],
        "grade": precisao["grade"],
        "amplitude_pct": precisao["amplitude_pct"],
        "detail": precisao["detail"],
    }

    assessment: Dict[str, Any] = {
        "schema_version": rules.CONTRACT_VERSION,
        "edition": rules.EDITION_PART2,
        "rule_sources": rule_sources,
        "verification_status": verification_status,
        "fundamentacao": fundamentacao,
        "precisao": precisao_out,
        "documentary": documentary,
        "statistical": statistical,
        "intervals": intervals,
        "issuance_note": (
            "ready_for_professional_review não é inferido do grau. "
            "C03 não emite laudo."
        ),
        "micronumerosidade": micro,
        "pressupostos": pressupostos,
        # Non-empty only when a clause that forbids using the model is
        # violated (Anexo A.2 g). Consumers must refuse release, not warn.
        "model_use_prohibited": model_use_prohibited,
        "source_documents": rules.SOURCE_DOCUMENTS,
        "cross_edition_notes": rules.CROSS_EDITION_NOTES,
        "rule_inventory": rules.inventory_audit(),
        "unverified_rules": [r["id"] for r in rules.UNVERIFIED_RULES],
        "issues": issues,
        "n": n,
        "k": k,
        "intercept": intercept,
    }
    return assessment


def _doc_grade(doc: Mapping[str, Any], ctx: Mapping[str, Any], item: int, legacy_key: str) -> Any:
    block = doc.get(f"item{item}") if isinstance(doc.get(f"item{item}"), Mapping) else None
    if block and block.get("grade") is not None:
        return block.get("grade")
    if ctx.get(legacy_key) is not None:
        return ctx.get(legacy_key)
    return None


def _doc_provenance(doc: Mapping[str, Any], ctx: Mapping[str, Any], item: int, legacy_key: str) -> Any:
    block = doc.get(f"item{item}") if isinstance(doc.get(f"item{item}"), Mapping) else None
    if block and block.get("provenance") is not None:
        return block.get("provenance")
    if ctx.get(legacy_key) is not None:
        return ctx.get(legacy_key)
    return None


def _item_payload(item: int, description: str, result: Mapping[str, Any]) -> Dict[str, Any]:
    grade = result.get("grade")
    points = result.get("points")
    if points is None and grade is not None:
        points = grade
    return {
        "item": item,
        "id": f"tabela1.item{item}",
        "description": description,
        "grade": grade,
        "points": points,
        "evidence_status": result.get("evidence_status"),
        "calculation": result.get("calculation"),
        "detail": result.get("detail"),
        "source": result.get("source"),
        "reasons": result.get("reasons") or result.get("limitations") or [],
        "provenance": result.get("provenance"),
        # Set only by classify_documentary_item (items 1 and 3). For the
        # calculated items it is None, which consumers must not read as False.
        "provenance_verified": result.get("provenance_verified"),
    }


def _axes_from_context(ctx: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if ctx.get("axes"):
        return [dict(a) for a in ctx["axes"]]
    details = ctx.get("extrapolation_details") or []
    axes: List[Dict[str, Any]] = []
    for item in details:
        axes.append(
            {
                "name": item.get("variable") or item.get("name"),
                "kind": item.get("kind") or rules.KIND_QUANTITATIVE,
                "avaliando_value": item.get("avaliando_value"),
                "sample_min": item.get("sample_min"),
                "sample_max": item.get("sample_max"),
                "sample_values": item.get("sample_values") or item.get("categories"),
                "unit": item.get("unit"),
            }
        )
    return axes


def _legacy_item4_grade_and_detail(
    extrapolation_details: Sequence[Mapping[str, Any]],
    *,
    predict_original: Optional[Callable] = None,
    subject_raw: Optional[Mapping[str, Any]] = None,
) -> Tuple[int, str, Dict[str, Any]]:
    """Adapter: ItemScore.grau_achieved is int; pending becomes 0 (not approval)."""
    axes = []
    for item in extrapolation_details or []:
        axes.append(
            {
                "name": item.get("variable") or item.get("name"),
                "kind": item.get("kind") or rules.KIND_QUANTITATIVE,
                "avaliando_value": item.get("avaliando_value"),
                "sample_min": item.get("sample_min"),
                "sample_max": item.get("sample_max"),
                "sample_values": item.get("sample_values") or item.get("categories"),
            }
        )
    result = rules.classify_item4_extrapolacao(
        axes, subject_raw=subject_raw, predict_original=predict_original
    )
    grade = result.get("grade")
    if grade is None:
        grade = 0
    return int(grade), str(result.get("detail") or ""), result


class NBRValidator:
    """
    Implements the official scoring algorithm of NBR 14653-2:2011 for
    regression models: Tabela 1 (grau de fundamentação, items 1-6),
    Tabela 2 (enquadramento) and Tabela 5 (grau de precisão), plus the
    complementary (non-tabled) assumptions of Anexo A.

    New assessments should call assess_normative(context). The methods
    below remain as adapters around modules.normative_rules.
    """

    @staticmethod
    def _classify_fundamentacao(item_scores: Dict[int, int]) -> Tuple[Optional[int], int]:
        result = rules.classify_fundamentacao(item_scores)
        return result["grade"], result["points"]

    @staticmethod
    def _classify_item2_quantidade_dados(n: int, k: int) -> int:
        result = rules.classify_item2_quantidade_dados(n, k)
        grade = result["grade"]
        return 0 if grade is None else int(grade)

    @staticmethod
    def _classify_item5_significancia_regressores(
        pvalues: Dict[str, float],
    ) -> Tuple[int, float]:
        result = rules.classify_item5_significancia_regressores(pvalues)
        grade = result["grade"]
        worst = result["worst_p"]
        if worst is None:
            worst = float("nan")
        return (0 if grade is None else int(grade)), worst

    @staticmethod
    def _classify_item6_significancia_global(f_pvalue: float) -> int:
        result = rules.classify_item6_significancia_global(f_pvalue)
        grade = result["grade"]
        return 0 if grade is None else int(grade)

    @staticmethod
    def _classify_item4_extrapolacao(
        extrapolation_details: List[Dict[str, Any]],
        predict_original: Optional[Callable] = None,
        subject_raw: Optional[Mapping[str, Any]] = None,
    ) -> Tuple[int, str]:
        grade, detail, _ = _legacy_item4_grade_and_detail(
            extrapolation_details,
            predict_original=predict_original,
            subject_raw=subject_raw,
        )
        return grade, detail

    @staticmethod
    def _classify_precisao(amplitude_pct: float) -> Tuple[Optional[int], str]:
        result = rules.classify_precisao(amplitude_pct)
        return result["grade"], result["detail"]

    @staticmethod
    def validate_model(
        model_result: ModelResult,
        X: pd.DataFrame,
        y: pd.Series,
        degree: int = 1,
        grau_item1: Optional[int] = None,
        grau_item3: Optional[int] = None,
        item1_provenance: Any = None,
        item3_provenance: Any = None,
        n: Optional[int] = None,
        k: Optional[int] = None,
        intercept: Optional[bool] = None,
    ) -> ValidationResult:
        """
        Validates a regression model against NBR 14653-2 Tabela 1 / Tabela 2.

        Item 4 (extrapolação) cannot be evaluated here (it depends on the
        avaliando's characteristics, not yet known) and is provisionally
        scored 0 (conservative). Call finalize_precision_and_extrapolation()
        afterwards to obtain the definitive grau_fundamentacao and the
        grau_precisao.

        n/k: if omitted, resolved without assuming intercept via shape[1]-1.

        MP-COM/C05: the documentary items 1 and 3 no longer default to Grau I.
        Undeclared documentary items are PENDING and score 0 points, exactly
        like assess_normative. A silent default of 1 point per undeclared
        documentary item was enough, combined with items 2/4/5/6 at Grau III,
        to reach 16 points and be enquadrado as Grau III without a single
        documentary declaration or any provenance — declaração ≠ verificação
        (Tabela 1 itens 1 e 3). Callers that really have a declared grade must
        now pass it explicitly, together with its provenance.
        """
        messages: List[str] = []
        warnings: List[str] = []
        details: Dict[str, Any] = {}

        metrics = model_result.model_metrics
        if not metrics:
            return ValidationResult(success=False, message="No model metrics available")

        nk = rules.resolve_effective_n_k(
            {"n": n, "k": k, "intercept": intercept}, X=X, y=y
        )
        n_eff, k_eff = nk["n"], nk["k"]
        warnings.extend(i["message"] for i in nk["issues"])

        item1 = rules.classify_documentary_item(
            1,
            grau_item1,
            item1_provenance,
            description="Caracterização do imóvel avaliando",
        )
        item1_grau = 0 if item1.get("grade") is None else int(item1["grade"])
        item1_detail = item1.get("detail") or ""
        if item1.get("grade") is None:
            warnings.append(
                "Item 1 (documental) não declarado: 0 ponto (pendente). "
                "Ausência de declaração não vale Grau I."
            )

        item2 = rules.classify_item2_quantidade_dados(n_eff, k_eff)
        item2_grau = 0 if item2["grade"] is None else int(item2["grade"])
        item2_detail = item2["detail"]

        item3 = rules.classify_documentary_item(
            3,
            grau_item3,
            item3_provenance,
            description="Identificação dos dados de mercado",
        )
        item3_grau = 0 if item3.get("grade") is None else int(item3["grade"])
        item3_detail = item3.get("detail") or ""
        if item3.get("grade") is None:
            warnings.append(
                "Item 3 (documental) não declarado: 0 ponto (pendente). "
                "Ausência de declaração não vale Grau I."
            )

        item4_grau = 0
        item4_detail = (
            "Não avaliado nesta etapa — requer características do imóvel avaliando e "
            "predict_original para a condição de valor (Tabela 1 item 4 (b)); "
            "assumido 0 pontos (conservador) até ser informado. Ausência ≠ aprovação."
        )

        item5 = rules.classify_item5_significancia_regressores(model_result.pvalues)
        item5_grau = 0 if item5["grade"] is None else int(item5["grade"])
        worst_p = item5["worst_p"]
        item5_detail = item5["detail"]

        item6 = rules.classify_item6_significancia_global(metrics.f_pvalue)
        item6_grau = 0 if item6["grade"] is None else int(item6["grade"])
        item6_detail = item6["detail"]

        item_scores = [
            ItemScore(item=1, description="Caracterização do imóvel avaliando", grau_achieved=item1_grau, detail=item1_detail),
            ItemScore(item=2, description="Quantidade mínima de dados de mercado", grau_achieved=item2_grau, detail=item2_detail),
            ItemScore(item=3, description="Identificação dos dados de mercado", grau_achieved=item3_grau, detail=item3_detail),
            ItemScore(item=4, description="Extrapolação", grau_achieved=item4_grau, detail=item4_detail),
            ItemScore(item=5, description="Nível de significância dos regressores (teste t)", grau_achieved=item5_grau, detail=item5_detail),
            ItemScore(item=6, description="Nível de significância do modelo global (teste F)", grau_achieved=item6_grau, detail=item6_detail),
        ]

        item_scores_dict = {isco.item: isco.grau_achieved for isco in item_scores}
        grau_fundamentacao, pontos = NBRValidator._classify_fundamentacao(item_scores_dict)

        warnings.append(
            "Grau de fundamentação provisório (limite inferior conservador): item 4 "
            "(extrapolação) ainda não avaliado nesta etapa e conta 0 pontos. O grau "
            "definitivo só é conhecido após finalize_precision_and_extrapolation()."
        )

        if grau_fundamentacao is None:
            messages.append(
                f"Grau de fundamentação não classificado nesta etapa (pontos={pontos}). "
                f"Pode melhorar após avaliação do item 4."
            )

        if metrics.normality_pvalue < config.SIGNIFICANCE_LEVEL_AUX:
            warnings.append(
                f"Resíduos possivelmente não normais (Shapiro-Wilk p={metrics.normality_pvalue:.4f} "
                f"< {config.SIGNIFICANCE_LEVEL_AUX:.0%}) — Anexo A.3.1."
            )

        if metrics.homoscedasticity_pvalue < config.SIGNIFICANCE_LEVEL_AUX:
            warnings.append(
                f"Possível heterocedasticidade (Breusch-Pagan p={metrics.homoscedasticity_pvalue:.4f} "
                f"< {config.SIGNIFICANCE_LEVEL_AUX:.0%}) — Anexo A.3.1."
            )

        warnings.append(
            f"R² ajustado = {metrics.r2_adjusted:.3f} (informativo — a norma não define piso "
            f"mínimo obrigatório de R²/R² ajustado, Anexo A.4)."
        )

        vif_violation = False
        for var, val in model_result.vif.items():
            if var != "const" and val > config.MAX_VIF:
                vif_violation = True
                warnings.append(
                    f"VIF de '{var}' = {val:.2f} > {config.MAX_VIF} (convenção de mercado, "
                    f"NÃO é limiar normativo — a NBR 14653-2 Anexo A.2.1.5.2 não define corte "
                    f"de VIF, apenas recomenda atenção a correlações > 0,80 na matriz de "
                    f"correlações). Não reprova o modelo."
                )

        is_valid = grau_fundamentacao is not None and grau_fundamentacao >= degree

        details = {
            "degree": degree,
            "n_samples": n_eff,
            "k_vars": k_eff,
            "intercept": nk.get("intercept"),
            "k_source": nk.get("k_source"),
            "r2": metrics.r2,
            "r2_adjusted": metrics.r2_adjusted,
            "max_p_value": worst_p if worst_p is not None and not (isinstance(worst_p, float) and np.isnan(worst_p)) else None,
            "f_pvalue": metrics.f_pvalue,
            "vif_violation": vif_violation,
        }

        return ValidationResult(
            success=True,
            is_valid=is_valid,
            messages=messages,
            warnings=warnings,
            details=details,
            item_scores=item_scores,
            grau_fundamentacao=grau_fundamentacao,
            grau_fundamentacao_pontos=pontos,
            grau_precisao=None,
            precisao_amplitude_pct=None,
            target_degree=degree,
        )

    @staticmethod
    def finalize_precision_and_extrapolation(
        validation_result: ValidationResult,
        amplitude_pct: float,
        extrapolation_details: List[Dict[str, Any]],
        degree: int,
        ci_lower: Optional[float] = None,
        ci_upper: Optional[float] = None,
        central_estimate: Optional[float] = None,
        predict_original: Optional[Callable] = None,
        subject_raw: Optional[Mapping[str, Any]] = None,
        estimand: Optional[str] = None,
        adopted_estimator: Optional[str] = None,
        prediction_interval: Optional[Mapping[str, Any]] = None,
    ) -> ValidationResult:
        """
        Completes the validation once the avaliando's data (for extrapolation,
        item 4) and the confidence-interval amplitude (grau de precisão,
        Tabela 5) are known.

        Item 4 uses Tabela 1 (a) measure AND (b) original-unit |Δvalue| when
        predict_original is provided. Measure-only admission is not a pass:
        without the callback, in-sample → Grau III; extrapolated → 0
        (pending in assess_normative; legacy int score cannot be null).

        ci_lower/ci_upper/central_estimate still populate
        valores_admissiveis_* for C04/C08 compatibility as the A.10.1.1
        central-tendency ∩ IC80 *candidate*. assess_normative distinguishes
        IC da média, PI, campo de arbítrio and admissibility use-conditions.
        """
        item4_grau, item4_detail, item4_full = _legacy_item4_grade_and_detail(
            extrapolation_details,
            predict_original=predict_original,
            subject_raw=subject_raw,
        )

        for isco in validation_result.item_scores:
            if isco.item == 4:
                isco.grau_achieved = item4_grau
                isco.detail = item4_detail
                break

        item_scores_dict = {isco.item: isco.grau_achieved for isco in validation_result.item_scores}
        grau_fundamentacao, pontos = NBRValidator._classify_fundamentacao(item_scores_dict)

        validation_result.grau_fundamentacao = grau_fundamentacao
        validation_result.grau_fundamentacao_pontos = pontos

        validation_result.warnings = [
            w
            for w in validation_result.warnings
            if "Grau de fundamentação provisório" not in w
        ]

        if item4_full.get("evidence_status") == rules.EVIDENCE_PENDING:
            validation_result.warnings.append(item4_detail)

        if grau_fundamentacao is None:
            validation_result.messages.append(
                f"Grau de fundamentação final não classificado (pontos={pontos})."
            )

        precisao = rules.classify_precisao(amplitude_pct)
        validation_result.grau_precisao = precisao["grade"]
        if precisao["status"] == rules.PRECISAO_ERROR:
            validation_result.precisao_amplitude_pct = None
            validation_result.warnings.append(precisao["detail"])
        else:
            validation_result.precisao_amplitude_pct = precisao["amplitude_pct"]
            if precisao["status"] == rules.PRECISAO_UNCLASSIFIED:
                validation_result.warnings.append(precisao["detail"])
            elif precisao["status"] == rules.PRECISAO_CLASSIFIED:
                validation_result.messages.append(precisao["detail"])
            elif precisao["status"] == rules.PRECISAO_NOT_COMPUTED:
                validation_result.warnings.append(precisao["detail"])

        mean_ci80 = None
        if ci_lower is not None and ci_upper is not None:
            mean_ci80 = {"lower": ci_lower, "upper": ci_upper}
        intervals = rules.interval_roles(
            central_estimate=central_estimate,
            mean_ci80=mean_ci80,
            prediction_interval=prediction_interval,
            estimand=estimand,
            adopted_estimator=adopted_estimator,
        )
        validation_result.details["interval_roles"] = intervals
        validation_result.details["precisao_status"] = precisao["status"]
        validation_result.details["item4"] = {
            "grade": item4_full.get("grade"),
            "evidence_status": item4_full.get("evidence_status"),
            "calculation": item4_full.get("calculation"),
            "detail": item4_full.get("detail"),
        }

        # Legacy valores_admissiveis: A.10.1.1 candidate using IC80 ∩ campo
        # when the three numbers are present. Not a claim of universal rule.
        if ci_lower is not None and ci_upper is not None and central_estimate is not None:
            campo_arbitrio_inf = central_estimate * (1 - config.CAMPO_ARBITRIO)
            campo_arbitrio_sup = central_estimate * (1 + config.CAMPO_ARBITRIO)
            validation_result.valores_admissiveis_inferior = max(ci_lower, campo_arbitrio_inf)
            validation_result.valores_admissiveis_superior = min(ci_upper, campo_arbitrio_sup)
            validation_result.details["campo_arbitrio_inferior"] = campo_arbitrio_inf
            validation_result.details["campo_arbitrio_superior"] = campo_arbitrio_sup
            validation_result.details["ic80_inferior"] = ci_lower
            validation_result.details["ic80_superior"] = ci_upper
            if estimand is None or adopted_estimator is None:
                validation_result.warnings.append(
                    "valores_admissiveis_* preenchidos como candidato A.10.1.1 "
                    "(IC de 80% da média ∩ campo de arbítrio) para compatibilidade; "
                    "estimand/adopted_estimator não declarados — não é regra universal "
                    "(nota 9: IC vs intervalo de predição). Ver assess_normative.intervals."
                )

        target_degree = (
            validation_result.target_degree
            if validation_result.target_degree is not None
            else degree
        )
        validation_result.is_valid = (
            grau_fundamentacao is not None and grau_fundamentacao >= target_degree
        )

        validation_result.details["amplitude_pct"] = (
            None if precisao["status"] == rules.PRECISAO_ERROR else precisao["amplitude_pct"]
        )
        validation_result.details["extrapolation_details"] = extrapolation_details
        validation_result.details["issuance_note"] = (
            "grau_fundamentacao/precisao não autoriza emissão automática de laudo"
        )

        return validation_result
