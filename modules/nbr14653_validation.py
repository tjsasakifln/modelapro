import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.stattools import durbin_watson
from statsmodels.stats.diagnostic import het_breuschpagan
from statsmodels.stats.outliers_influence import variance_inflation_factor
from typing import Dict, List, Any, Optional, Tuple
from .results import ValidationResult, ModelResult, ItemScore
from .config_manager import config


class NBRValidator:
    """
    Implements the official scoring algorithm of NBR 14653-2:2011 for
    regression models: Tabela 1 (grau de fundamentação, items 1-6),
    Tabela 2 (enquadramento) and Tabela 5 (grau de precisão), plus the
    complementary (non-tabled) assumptions of Anexo A.
    """

    # ------------------------------------------------------------------
    # Tabela 2 (9.2.1.6) - Enquadramento do grau de fundamentação
    # ------------------------------------------------------------------
    @staticmethod
    def _classify_fundamentacao(item_scores: Dict[int, int]) -> Tuple[Optional[int], int]:
        """
        Receives {1: grau_item1, ..., 6: grau_item6} (each 0-3) and applies
        Tabela 2 to determine the overall grau de fundamentação and the
        total points (sum of the 6 items).

        Grau III: pontos >= 16 AND items {2,4,5,6} each >= 3 AND items {1,3} each >= 2
        Grau II:  pontos >= 10 AND items {2,4,5,6} each >= 2 AND items {1,3} each >= 1
        Grau I:   pontos >= 6  AND all 6 items >= 1
        Senão: não classificado (None)
        """
        pontos = sum(item_scores.get(i, 0) for i in range(1, 7))

        obrigatorios = [item_scores.get(i, 0) for i in (2, 4, 5, 6)]
        complementares = [item_scores.get(i, 0) for i in (1, 3)]
        todos = [item_scores.get(i, 0) for i in range(1, 7)]

        # Grau III
        if pontos >= 16 and all(v >= 3 for v in obrigatorios) and all(v >= 2 for v in complementares):
            return 3, pontos

        # Grau II
        if pontos >= 10 and all(v >= 2 for v in obrigatorios) and all(v >= 1 for v in complementares):
            return 2, pontos

        # Grau I
        if pontos >= 6 and all(v >= 1 for v in todos):
            return 1, pontos

        return None, pontos

    # ------------------------------------------------------------------
    # Item-level classifiers (Tabela 1)
    # ------------------------------------------------------------------
    @staticmethod
    def _classify_item2_quantidade_dados(n: int, k: int) -> int:
        """Item 2: quantidade mínima de dados de mercado. III=6(k+1); II=4(k+1); I=3(k+1)."""
        if n >= 6 * (k + 1):
            return 3
        if n >= 4 * (k + 1):
            return 2
        if n >= 3 * (k + 1):
            return 1
        return 0

    @staticmethod
    def _classify_item5_significancia_regressores(pvalues: Dict[str, float]) -> Tuple[int, float]:
        """Item 5: pior (maior) p-valor entre os regressores (exceto const).
        III<=10%; II<=20%; I<=30%."""
        regressor_pvals = [p for var, p in pvalues.items() if var != 'const']
        if not regressor_pvals:
            return 0, float('nan')
        worst_p = max(regressor_pvals)
        if worst_p <= 0.10:
            return 3, worst_p
        if worst_p <= 0.20:
            return 2, worst_p
        if worst_p <= 0.30:
            return 1, worst_p
        return 0, worst_p

    @staticmethod
    def _classify_item6_significancia_global(f_pvalue: float) -> int:
        """Item 6: teste F de Snedecor (significância global). III<=1%; II<=2%; I<=5%."""
        if f_pvalue <= 0.01:
            return 3
        if f_pvalue <= 0.02:
            return 2
        if f_pvalue <= 0.05:
            return 1
        return 0

    @staticmethod
    def _classify_item4_extrapolacao(extrapolation_details: List[Dict[str, Any]]) -> Tuple[int, str]:
        """
        Item 4: Extrapolação.
        III = nenhuma variável fora do intervalo amostral [min, max].
        II  = admitida para no máximo 1 variável, dentro do intervalo estendido
              [0.5*min, 2*max] mas fora de [min, max].
        I   = mesma regra do intervalo estendido, sem limite de 1 variável.
        Fora do intervalo estendido em qualquer variável: item 4 = 0 (mesmo p/ grau I).
        """
        if not extrapolation_details:
            return 0, "Nenhuma variável do avaliando informada para checagem de extrapolação."

        extrapolated_vars = []  # variables outside [min,max] but inside extended interval
        out_of_bounds_vars = []  # variables outside the extended interval entirely

        for item in extrapolation_details:
            var = item.get("variable")
            val = item.get("avaliando_value")
            vmin = item.get("sample_min")
            vmax = item.get("sample_max")

            if val is None or vmin is None or vmax is None:
                continue

            ext_min = 0.5 * vmin
            ext_max = 2.0 * vmax

            if vmin <= val <= vmax:
                continue  # within sample interval, no extrapolation
            elif ext_min <= val <= ext_max:
                extrapolated_vars.append(var)
            else:
                out_of_bounds_vars.append(var)

        if out_of_bounds_vars:
            detail = (
                f"Item 4 reprovado: variável(is) {out_of_bounds_vars} fora do intervalo "
                f"estendido [0.5*min, 2*max]."
            )
            return 0, detail

        if not extrapolated_vars:
            return 3, "Nenhuma extrapolação: todas as variáveis dentro do intervalo amostral [min, max]."

        if len(extrapolated_vars) == 1:
            detail = (
                f"Extrapolação admitida (Grau II): variável '{extrapolated_vars[0]}' fora de "
                f"[min, max] mas dentro do intervalo estendido [0.5*min, 2*max]."
            )
            return 2, detail

        detail = (
            f"Extrapolação admitida apenas em Grau I: variáveis {extrapolated_vars} fora de "
            f"[min, max] mas dentro do intervalo estendido [0.5*min, 2*max]."
        )
        return 1, detail

    @staticmethod
    def _classify_precisao(amplitude_pct: float) -> Tuple[Optional[int], str]:
        """Tabela 5 (9.2.3): amplitude do IC de 80% em torno da estimativa pontual.
        III<=30%; II<=40%; I<=50%; senão não classificável."""
        if amplitude_pct <= 30:
            return 3, f"Amplitude {amplitude_pct:.2f}% <= 30% (Grau III)."
        if amplitude_pct <= 40:
            return 2, f"Amplitude {amplitude_pct:.2f}% <= 40% (Grau II)."
        if amplitude_pct <= 50:
            return 1, f"Amplitude {amplitude_pct:.2f}% <= 50% (Grau I)."
        return None, (
            f"Amplitude {amplitude_pct:.2f}% > 50%: não classificável quanto à precisão. "
            f"Requer justificativa no laudo (item 9.2.3 / Anexo A)."
        )

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------
    @staticmethod
    def validate_model(
        model_result: ModelResult,
        X: pd.DataFrame,
        y: pd.Series,
        degree: int = 1,
        grau_item1: int = 1,
        grau_item3: int = 1,
    ) -> ValidationResult:
        """
        Validates a regression model against NBR 14653-2 Tabela 1 / Tabela 2.

        Item 4 (extrapolação) cannot be evaluated here (it depends on the
        avaliando's characteristics, not yet known) and is provisionally
        scored 0 (conservative). Call finalize_precision_and_extrapolation()
        afterwards to obtain the definitive grau_fundamentacao and the
        grau_precisao.
        """
        messages: List[str] = []
        warnings: List[str] = []
        details: Dict[str, Any] = {}
        is_valid = True

        metrics = model_result.model_metrics
        if not metrics:
            return ValidationResult(success=False, message="No model metrics available")

        n = len(y)
        k = X.shape[1] - 1  # number of independent variables, excluding constant

        # --- Item 1: Caracterização do imóvel avaliando (não calculável aqui) ---
        item1_grau = grau_item1
        item1_detail = (
            "Grau informado externamente (documentação/laudo), não calculável a partir da "
            "planilha de dados."
        )

        # --- Item 2: Quantidade mínima de dados de mercado ---
        item2_grau = NBRValidator._classify_item2_quantidade_dados(n, k)
        item2_detail = (
            f"n={n}, k={k}. Mínimos: I=3(k+1)={3*(k+1)}, II=4(k+1)={4*(k+1)}, "
            f"III=6(k+1)={6*(k+1)}."
        )

        # --- Item 3: Identificação dos dados de mercado (não calculável aqui) ---
        item3_grau = grau_item3
        item3_detail = (
            "Grau informado externamente (documentação/laudo), não calculável a partir da "
            "planilha de dados."
        )

        # --- Item 4: Extrapolação (ainda não avaliável nesta etapa) ---
        item4_grau = 0
        item4_detail = (
            "Não avaliado nesta etapa — requer características do imóvel avaliando; "
            "assumido 0 pontos (conservador) até ser informado."
        )

        # --- Item 5: Nível de significância dos regressores (teste t) ---
        item5_grau, worst_p = NBRValidator._classify_item5_significancia_regressores(
            model_result.pvalues
        )
        item5_detail = f"Pior p-valor entre regressores: {worst_p:.4f}." if not np.isnan(worst_p) else "Sem regressores."

        # --- Item 6: Nível de significância do modelo global (teste F) ---
        item6_grau = NBRValidator._classify_item6_significancia_global(metrics.f_pvalue)
        item6_detail = f"F-prob (p-valor do teste F): {metrics.f_pvalue:.4f}."

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

        # --- Anexo A.3.1: demais testes estatísticos (não citados na Tabela 1) ---
        # Limiar de rejeição de até 10% (SIGNIFICANCE_LEVEL_AUX), não 5%.
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

        # --- R² ajustado: informativo apenas (Anexo A.4), nunca reprova o modelo ---
        warnings.append(
            f"R² ajustado = {metrics.r2_adjusted:.3f} (informativo — a norma não define piso "
            f"mínimo obrigatório de R²/R² ajustado, Anexo A.4)."
        )

        # --- Multicolinearidade (VIF) - Anexo A.2.1.5.2 pede atenção à matriz de
        # correlações (destaque para |corr| > 0,80), mas NÃO define nenhum limiar
        # numérico de VIF. VIF > 10 é convenção de mercado, não critério normativo
        # da Tabela 1/2 — por isso é apenas um aviso informativo e NUNCA reprova
        # is_valid.
        vif_violation = False
        for var, val in model_result.vif.items():
            if var != 'const' and val > config.MAX_VIF:
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
            "n_samples": n,
            "k_vars": k,
            "r2": metrics.r2,
            "r2_adjusted": metrics.r2_adjusted,
            "max_p_value": worst_p if not np.isnan(worst_p) else None,
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
    ) -> ValidationResult:
        """
        Completes the validation once the avaliando's data (for extrapolation,
        item 4) and the confidence-interval amplitude (grau de precisão,
        Tabela 5) are known. Recomputes grau_fundamentacao/pontos and
        grau_precisao, and updates is_valid accordingly.

        ci_lower/ci_upper/central_estimate (optional): the 80% confidence
        interval bounds and point estimate used to derive amplitude_pct.
        When all three are provided, also computes the Anexo A.10.1.1
        "valores admissíveis": the intersection of the 80% CI with the
        campo de arbítrio (±CAMPO_ARBITRIO, NBR 14653-1 3.8 / NBR 14653-2
        8.2.1.5.1) around the point estimate. Whichever interval is
        narrower on a given side wins (intersection, not union):
        inferior = max(ci_lower, central*(1-CAMPO_ARBITRIO))
        superior = min(ci_upper, central*(1+CAMPO_ARBITRIO))
        """
        # --- Item 4: Extrapolação ---
        item4_grau, item4_detail = NBRValidator._classify_item4_extrapolacao(extrapolation_details)

        for isco in validation_result.item_scores:
            if isco.item == 4:
                isco.grau_achieved = item4_grau
                isco.detail = item4_detail
                break

        item_scores_dict = {isco.item: isco.grau_achieved for isco in validation_result.item_scores}
        grau_fundamentacao, pontos = NBRValidator._classify_fundamentacao(item_scores_dict)

        validation_result.grau_fundamentacao = grau_fundamentacao
        validation_result.grau_fundamentacao_pontos = pontos

        # Remove the "provisional" warning now that item 4 is final, keep other warnings.
        validation_result.warnings = [
            w for w in validation_result.warnings
            if "Grau de fundamentação provisório" not in w
        ]

        if grau_fundamentacao is None:
            validation_result.messages.append(
                f"Grau de fundamentação final não classificado (pontos={pontos})."
            )

        # --- Tabela 5: Grau de precisão ---
        grau_precisao, precisao_msg = NBRValidator._classify_precisao(amplitude_pct)
        validation_result.grau_precisao = grau_precisao
        validation_result.precisao_amplitude_pct = amplitude_pct
        if grau_precisao is None:
            validation_result.warnings.append(precisao_msg)
        else:
            validation_result.messages.append(precisao_msg)

        # --- Anexo A.10.1.1: "valores admissíveis" = interseção entre o IC de
        # 80% e o campo de arbítrio (±CAMPO_ARBITRIO) em torno da estimativa
        # pontual central. Só calculável quando os três valores (IC + ponto)
        # são conhecidos, ou seja, quando o grau de precisão pôde ser apurado.
        if ci_lower is not None and ci_upper is not None and central_estimate is not None:
            campo_arbitrio_inf = central_estimate * (1 - config.CAMPO_ARBITRIO)
            campo_arbitrio_sup = central_estimate * (1 + config.CAMPO_ARBITRIO)
            validation_result.valores_admissiveis_inferior = max(ci_lower, campo_arbitrio_inf)
            validation_result.valores_admissiveis_superior = min(ci_upper, campo_arbitrio_sup)
            validation_result.details["campo_arbitrio_inferior"] = campo_arbitrio_inf
            validation_result.details["campo_arbitrio_superior"] = campo_arbitrio_sup
            validation_result.details["ic80_inferior"] = ci_lower
            validation_result.details["ic80_superior"] = ci_upper

        # --- Recompute is_valid. VIF/multicolinearidade NÃO é mais um gate:
        # Anexo A.2.1.5.2 não define limiar normativo de VIF (ver
        # validate_model), então is_valid depende apenas do grau de
        # fundamentação atingido frente ao grau-alvo.
        target_degree = validation_result.target_degree if validation_result.target_degree is not None else degree
        validation_result.is_valid = (
            grau_fundamentacao is not None and grau_fundamentacao >= target_degree
        )

        validation_result.details["amplitude_pct"] = amplitude_pct
        validation_result.details["extrapolation_details"] = extrapolation_details

        return validation_result
