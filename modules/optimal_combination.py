import pandas as pd
import itertools
from typing import List, Dict, Optional, Tuple
from .results import OptimalCombinationResult, ModelResult
from .model_builder import ModelBuilder
from .transformations import Transformer
from .logging_manager import logger
from .config_manager import config


class OptimalCombinationFinder:
    """
    Finds the NBR 14653-2 optimal (variable set x transformation) combination
    for a regression model.

    Search space
    ------------
    For each ORIGINAL independent variable ("variável-base") there is a set
    of mutually exclusive options: {não incluir, linear, ln, sqrt, inverse,
    sqr, inv_sqr, inv_sqrt}, restricted to the transformations that are
    mathematically valid for that variable's domain (ln/sqrt/inv_sqrt need
    strictly positive values; inverse/inv_sqr need non-zero values — same
    domain checks as modules.transformations.Transformer). A candidate model
    is one choice of exactly one option per base variable (the "não incluir"
    option simply leaves that variable out). Because at most one option per
    base variable can ever be chosen, two transformations of the SAME base
    variable can never appear together — no post-hoc conflict filter needed.

    This is a genuine exhaustive search over the transformation x inclusion
    space (Cartesian product), not a correlation-based sample, for the
    common case (see MAX_EXHAUSTIVE_CANDIDATES below).

    Model-size ceiling
    -------------------
    Instead of an arbitrary fixed cap, the max number of variables per
    candidate model is derived from the normative minimum-sample rule
    (Tabela 1, item 2: n >= 3(k+1), the loosest requirement, valid even for
    Grau I): max_vars = max(1, floor(n/3) - 1), n = rows in the ORIGINAL df.
    This guarantees every tested candidate at least has a theoretical chance
    at Grau I on item 2, without wasting time on models that are obviously
    too large for the sample.

    Combinatorial safety valve
    ---------------------------
    The exact number of exhaustive candidates (restricted to max_vars) is
    computed with a cheap 0/1-knapsack-style DP BEFORE any model is fit
    (see _count_exhaustive_candidates). Whether this stays small enough to
    run fully exhaustive depends less on the raw number of candidate base
    variables than on how many domain-valid transformation OPTIONS each one
    contributes: a strictly-positive continuous variable can offer up to 7
    mutually exclusive options (linear + all 6 entries of
    NON_LINEAR_TRANSFORMATIONS), so as few as ~10 such variables can already
    approach or exceed MAX_EXHAUSTIVE_CANDIDATES on their own (7**10 is
    already in the tens of millions) - it is NOT generally true that
    "typical" real-estate datasets always stay 100% exhaustive; that
    depends on this per-variable option count, not merely on how many
    columns are present. Only when the exact
    count exceeds MAX_EXHAUSTIVE_CANDIDATES (200_000) does the search fall
    back — documented, never silent — to the old top-N-by-correlation
    heuristic (kept as _iter_candidates_fallback, not deleted), and
    OptimalCombinationResult.exhaustive is set to False so callers can tell
    the "guarantee of optimum" does NOT hold for that particular run.

    IMPORTANT: the valve bounds the candidate COUNT, not wall-clock time.
    When avaliando_raw is supplied (see below), every candidate requires a
    full OLS fit plus a get_prediction() call; tens of thousands of
    candidates can still take a long time by design — the user has
    explicitly prioritized correctness over search cost.

    Grau-aware ranking during the search
    --------------------------------------
    If avaliando_raw is a non-empty dict, item 4 (extrapolação) and grau de
    precisão are computed for EVERY candidate (via
    ModelBuilder.add_precision_and_extrapolation), not only for the final
    winner, so grau_fundamentacao reflects items 1-6 in full during the
    entire comparison — this is what actually guarantees the returned model
    is optimal with respect to the real NBR 14653-2 grau, not merely to
    r2_adjusted. Base variables that have no value in avaliando_raw are
    excluded from the search entirely in that case (see find_best_model):
    letting add_precision_and_extrapolation silently fail per-candidate for
    only some candidates would make item 4 asymmetric across the ranking
    (some candidates fairly scored, others stuck at the 0/provisional
    default) — quietly corrupting the very ranking this rewrite exists to
    fix. If avaliando_raw is not provided, item 4 stays 0/provisional
    throughout the search (documented, known limitation — there is no way
    to evaluate extrapolação per variable without avaliando data).
    """

    # Valve threshold: exact candidate count above which the search falls
    # back to the heuristic top-N-by-correlation pruning below.
    MAX_EXHAUSTIVE_CANDIDATES = 200_000

    # Old heuristic, preserved as a named, documented fallback (NOT deleted)
    # for the extreme case where the exhaustive space is too large.
    FALLBACK_TOP_N = 15
    FALLBACK_MAX_VARS = 5

    # If more candidates than this are evaluated, history is sampled evenly
    # rather than returning every single entry, to keep the result size
    # manageable. The omission count is always reported (never hidden).
    HISTORY_SAMPLE_LIMIT = 5000

    NON_LINEAR_TRANSFORMATIONS = ['ln', 'sqrt', 'inverse', 'sqr', 'inv_sqr', 'inv_sqrt']

    def __init__(self):
        self.model_builder = ModelBuilder()
        self.transformer = Transformer()

    @staticmethod
    def _score_key(result: ModelResult) -> Tuple[int, float]:
        """
        Ordering key for candidate models: prefer higher grau_fundamentacao
        (None treated as -1 for comparison purposes), with r2_adjusted as a
        tie-breaker within the same grau.
        """
        grau = None
        if result.validation_result is not None:
            grau = result.validation_result.grau_fundamentacao
        grau_key = grau if grau is not None else -1
        r2_adj = result.model_metrics.r2_adjusted if result.model_metrics else -float('inf')
        return (grau_key, r2_adj)

    @staticmethod
    def _base_name(col: str) -> str:
        """Extracts 'area' from 'ln(area)', or returns col unchanged if it's already a base name."""
        if "(" in col and col.endswith(")"):
            return col[col.index("(") + 1: -1]
        return col

    def _build_variable_options(
        self, df: pd.DataFrame, X_cols: List[str],
        avaliando_raw: Optional[Dict[str, float]] = None,
    ) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
        """
        For each base variable, builds the column(s) for every domain-valid
        option: the base variable itself (linear/no transformation) plus
        every transformation whose domain constraints are satisfied (same
        validity checks as Transformer.apply_transformation) for the
        TRAINING column.

        When avaliando_raw is provided, a transformation is additionally
        required to be domain-valid for that specific base variable's
        avaliando value (e.g. ln/sqrt/inv_sqrt need a strictly positive
        value, inverse/inv_sqr a non-zero value) before it is offered as an
        option. A transformation can be perfectly valid across the whole
        training column yet undefined for one specific avaliando value
        (idade=0, distância=0, ...); without this check that candidate
        would only fail later, inside add_precision_and_extrapolation, on a
        per-candidate basis - making item 4 (extrapolação) asymmetric
        across candidates and corrupting the grau-aware ranking, exactly
        the failure mode this class exists to prevent (see class
        docstring), just triggered by a different root cause than the
        "missing base variable" case already filtered by the caller.

        Returns the augmented DataFrame (all valid transformed columns
        added) and a dict base_var -> [column names], one entry per valid
        option including the base column name itself (never includes a
        "não incluir" placeholder — that option is implicit: a base
        variable simply isn't picked into a given candidate's subset).
        """
        transformed_df = df.copy()
        vars_options: Dict[str, List[str]] = {}

        for col in X_cols:
            options = [col]  # linear / no transformation, always domain-valid
            dropped_for_avaliando = []
            for trans_name in self.NON_LINEAR_TRANSFORMATIONS:
                transformed, ok = Transformer.apply_transformation(df[col], trans_name)
                if not ok:
                    continue

                if avaliando_raw is not None and col in avaliando_raw:
                    _, avaliando_ok = Transformer.apply_transformation(
                        pd.Series([avaliando_raw[col]]), trans_name
                    )
                    if not avaliando_ok:
                        dropped_for_avaliando.append(trans_name)
                        continue

                new_col_name = f"{trans_name}({col})"
                transformed_df[new_col_name] = transformed
                options.append(new_col_name)

            if dropped_for_avaliando:
                logger.warning(
                    f"Variável '{col}': transformação(ões) {dropped_for_avaliando} válida(s) "
                    f"para a coluna de treino mas indefinida(s) para o valor do avaliando "
                    f"({avaliando_raw.get(col)!r}); excluída(s) do espaço de busca para manter "
                    f"o item 4 (extrapolação) simétrico entre candidatos."
                )

            vars_options[col] = options

        return transformed_df, vars_options

    @staticmethod
    def _count_exhaustive_candidates(option_counts: List[int], max_vars: int) -> int:
        """
        Counts EXACTLY how many candidates _iter_candidates_exhaustive will
        yield, without generating them: for each base variable i, choosing
        to include it multiplies the branch count by option_counts[i]
        (its number of domain-valid options); choosing to exclude it
        contributes a factor of 1. This is a standard 0/1-knapsack DP where
        "weight" = 1 included variable and "value multiplicity" = option
        count; dp[j] after processing all variables = number of ways to end
        up with exactly j included variables.

        Total = sum_{j=1}^{max_vars} dp[j]  (excludes j=0, the "no variable
        included at all" case, which is not a valid model).
        """
        dp = [1] + [0] * max_vars
        for c in option_counts:
            # Iterate j from high to low so each variable is only ever
            # "included" at most once per candidate (classic 0/1 knapsack
            # in-place update).
            for j in range(max_vars, 0, -1):
                dp[j] += dp[j - 1] * c
        return sum(dp[1:max_vars + 1])

    def _iter_candidates_exhaustive(self, vars_options: Dict[str, List[str]], max_vars: int):
        """
        True exhaustive enumeration: every subset of base variables of size
        1..max_vars, combined with every choice of one domain-valid option
        per variable in that subset. Yields lists of column names.
        """
        base_vars = list(vars_options.keys())
        for k in range(1, max_vars + 1):
            for subset in itertools.combinations(base_vars, k):
                option_lists = [vars_options[v] for v in subset]
                for choice in itertools.product(*option_lists):
                    yield list(choice)

    def _iter_candidates_fallback(
        self, transformed_df: pd.DataFrame, y: pd.Series,
        vars_options: Dict[str, List[str]], max_vars: int,
    ):
        """
        OLD heuristic (kept intentionally, not deleted): documented fallback
        used ONLY when the exhaustive space exceeds MAX_EXHAUSTIVE_CANDIDATES.
        Ranks all candidate columns by |correlation| with the target, keeps
        the top FALLBACK_TOP_N, and tests combinations up to
        FALLBACK_MAX_VARS variables, skipping any combo that would mix two
        transformations of the same base variable.
        """
        flat_cols = [c for opts in vars_options.values() for c in opts]

        correlations = []
        for col in flat_cols:
            try:
                corr = transformed_df[col].corr(y)
                if pd.notna(corr):
                    correlations.append((col, abs(corr)))
            except Exception:
                pass
        correlations.sort(key=lambda x: x[1], reverse=True)
        top_vars = [x[0] for x in correlations[:self.FALLBACK_TOP_N]]

        max_vars_in_model = min(len(top_vars), self.FALLBACK_MAX_VARS, max_vars)

        for k in range(1, max_vars_in_model + 1):
            for combo in itertools.combinations(top_vars, k):
                base_names = set()
                conflict = False
                for var in combo:
                    base = self._base_name(var)
                    if base in base_names:
                        conflict = True
                        break
                    base_names.add(base)
                if conflict:
                    continue
                yield list(combo)

    def find_best_model(
        self,
        df: pd.DataFrame,
        target_col: str,
        degree: int = 1,
        avaliando_raw: Optional[Dict[str, float]] = None,
        grau_item1: int = 1,
        grau_item3: int = 1,
        candidate_cols: Optional[List[str]] = None,
    ) -> OptimalCombinationResult:
        """
        Finds the best model by exhaustively testing combinations of
        variables and transformations (see class docstring for the full
        algorithm and the combinatorial safety valve).

        Candidates are scored primarily by the official NBR 14653-2 grau de
        fundamentação achieved (None counts as the worst possible grau), with
        r2_adjusted as a tie-breaker within the same grau. The search
        prefers a combination that reaches at least `degree`; if none does,
        the best combination found overall is returned with
        target_achieved=False.

        If avaliando_raw is provided (non-empty dict), grau de precisão and
        item 4 (extrapolação) are computed for EVERY candidate during the
        search itself, so the ranking is grau-aware throughout — not just
        at the end. Base variables absent from avaliando_raw are excluded
        from the search in that case (see class docstring). If avaliando_raw
        is not provided, item 4 stays 0/provisional for every candidate
        (documented known limitation).

        candidate_cols: optional explicit list of base variable column
        names (already cleaned via clean_column_name, matching df.columns)
        to restrict the search to. This is how the user's free choice of
        which market variables to bring in is honored - the search never
        pre-fixes candidates itself. Names not present in df (or equal to
        target_col) are ignored with a logged warning, never an error. None
        or an empty list keeps the previous behavior: every column except
        target_col is a candidate.
        """
        try:
            X_cols_all = [c for c in df.columns if c != target_col]
            y = df[target_col]
            n = len(df)

            if candidate_cols:
                requested = set(candidate_cols)
                missing_requested = [c for c in candidate_cols if c not in X_cols_all]
                if missing_requested:
                    logger.warning(
                        f"candidate_cols solicita coluna(s) inexistente(s) no DataFrame (ou "
                        f"igual ao alvo): {missing_requested}; serão ignoradas."
                    )
                X_cols_all = [c for c in X_cols_all if c in requested]

            if not X_cols_all:
                return OptimalCombinationResult(
                    success=False,
                    message="Nenhuma variável independente disponível no DataFrame.",
                    error="no_independent_variables",
                )

            effective_avaliando: Optional[Dict[str, float]] = None
            X_cols = X_cols_all
            avaliando_exclusion_disclosure = ""
            if avaliando_raw:
                missing_bases = [c for c in X_cols_all if c not in avaliando_raw]
                if missing_bases:
                    logger.warning(
                        f"avaliando_raw não contém valor para a(s) variável(is) base "
                        f"{missing_bases}; elas serão excluídas da busca. Deixá-las entrar "
                        f"faria add_precision_and_extrapolation falhar (silenciosamente, por "
                        f"candidato) só para modelos que as usassem, tornando o item 4 "
                        f"assimétrico entre candidatos e corrompendo o ranking por grau de "
                        f"fundamentação."
                    )
                    # User-facing version of the log line above: surfaced
                    # through OptimalCombinationResult.message so it reaches
                    # search_message in the worker response and the PDF
                    # report (see worker.py / results_generator.py), instead
                    # of being visible only in server logs. This is the
                    # ONLY signal the user gets that a candidate variable
                    # they selected (e.g. a categorical like "bairro",
                    # expanded here into "bairro_Centro", "bairro_Sul", ...)
                    # was silently dropped from the search because no
                    # avaliando value exists for it.
                    avaliando_exclusion_disclosure = (
                        f"Variável(is) candidata(s) excluída(s) da busca por falta de valor "
                        f"do imóvel avaliando: {missing_bases}. Nenhum valor foi informado "
                        f"para essa(s) coluna(s) no imóvel avaliando, portanto nenhum modelo "
                        f"testado durante a busca as utiliza (necessário para manter o item 4 "
                        f"- extrapolação - e o grau de precisão simétricos entre todos os "
                        f"candidatos comparados)."
                    )
                X_cols = [c for c in X_cols_all if c not in missing_bases]
                effective_avaliando = avaliando_raw

            if not X_cols:
                return OptimalCombinationResult(
                    success=False,
                    message=(
                        "Nenhuma variável base possui valor de avaliando informado em "
                        "avaliando_raw; busca impossível nessas condições."
                    ),
                    error="no_usable_variables",
                )

            transformed_df, vars_options = self._build_variable_options(
                df, X_cols, avaliando_raw=effective_avaliando
            )

            # Tabela 1, item 2 (n >= 3(k+1), o piso normativo mais permissivo,
            # válido até para Grau I): teto de variáveis por modelo derivado
            # do próprio critério normativo, não mais um número arbitrário.
            max_vars = max(1, n // 3 - 1)
            max_vars = min(max_vars, len(vars_options))

            option_counts = [len(opts) for opts in vars_options.values()]
            exhaustive_total = self._count_exhaustive_candidates(option_counts, max_vars)

            exhaustive = True
            fallback_disclosure = ""
            if exhaustive_total > self.MAX_EXHAUSTIVE_CANDIDATES:
                exhaustive = False
                fallback_max_vars = min(self.FALLBACK_MAX_VARS, max_vars)
                fallback_disclosure = (
                    f"Busca exaustiva exigiria {exhaustive_total} combinações "
                    f"(variável-base x transformação, até {max_vars} variáveis por modelo), "
                    f"acima do limite de segurança combinatória de "
                    f"{self.MAX_EXHAUSTIVE_CANDIDATES}. Aplicando fallback documentado de poda "
                    f"por correlação: top-{self.FALLBACK_TOP_N} colunas por |correlação| com o "
                    f"target, até {fallback_max_vars} variáveis por modelo. A garantia de ótimo "
                    f"global sobre TODO o espaço de busca NÃO se aplica a este resultado "
                    f"(OptimalCombinationResult.exhaustive=False)."
                )
                logger.warning(fallback_disclosure)
                candidate_iter = self._iter_candidates_fallback(transformed_df, y, vars_options, max_vars)
            else:
                candidate_iter = self._iter_candidates_exhaustive(vars_options, max_vars)

            best_global_result: Optional[ModelResult] = None
            best_global_key = (-2, -float('inf'))

            best_target_result: Optional[ModelResult] = None
            best_target_key = (-2, -float('inf'))

            combinations_tested = 0
            full_history: List[Dict] = []

            for cols in candidate_iter:
                combinations_tested += 1

                X_subset = transformed_df[cols]

                result = self.model_builder.build_model(
                    X_subset, y, degree, remove_outliers=True,
                    grau_item1=grau_item1, grau_item3=grau_item3
                )

                # Grau-aware ranking: compute item 4 / grau de precisão for
                # THIS candidate now, before it's compared to any other, so
                # grau_fundamentacao used in _score_key reflects items 1-6
                # in full — not a placeholder — for every candidate alike.
                if result.success and result.model_metrics and effective_avaliando:
                    result = self.model_builder.add_precision_and_extrapolation(
                        result, effective_avaliando, df, degree=degree
                    )

                if result.success and result.model_metrics:
                    key = self._score_key(result)
                    grau_fundamentacao = (
                        result.validation_result.grau_fundamentacao
                        if result.validation_result else None
                    )

                    if key > best_global_key:
                        best_global_key = key
                        best_global_result = result

                    if grau_fundamentacao is not None and grau_fundamentacao >= degree:
                        if key > best_target_key:
                            best_target_key = key
                            best_target_result = result

                    full_history.append({
                        "variables": cols,
                        "r2_adj": result.model_metrics.r2_adjusted,
                        "grau_fundamentacao": grau_fundamentacao,
                        "valid": result.validation_result.is_valid if result.validation_result else False,
                    })

            if exhaustive and combinations_tested != exhaustive_total:
                # Should never happen; if it does, the DP count and the
                # generator have drifted out of sync and need reconciling.
                logger.warning(
                    f"Divergência entre a contagem prevista de candidatos exaustivos "
                    f"({exhaustive_total}) e o número efetivamente gerado "
                    f"({combinations_tested}). Verifique _count_exhaustive_candidates vs. "
                    f"_iter_candidates_exhaustive."
                )

            if best_target_result is not None:
                best_model = best_target_result
                target_achieved = True
                best_grau_reached = best_model.validation_result.grau_fundamentacao
            elif best_global_result is not None:
                best_model = best_global_result
                target_achieved = False
                best_grau_reached = (
                    best_global_result.validation_result.grau_fundamentacao
                    if best_global_result.validation_result else None
                )
            else:
                best_model = None
                target_achieved = False
                best_grau_reached = None

            # Final safety-net recompute from the winner's actual
            # grau_fundamentacao. When effective_avaliando was set, this is a
            # no-op (already finalized per-candidate above). When
            # avaliando_raw was not provided at all, item 4 stayed
            # 0/provisional for every candidate — documented known
            # limitation — and this simply reflects that provisional state,
            # matching prior behavior.
            if best_model is not None and best_model.validation_result is not None:
                best_grau_reached = best_model.validation_result.grau_fundamentacao
                target_achieved = (
                    best_grau_reached is not None and best_grau_reached >= degree
                )

            message_parts = []
            if avaliando_exclusion_disclosure:
                message_parts.append(avaliando_exclusion_disclosure)
            if fallback_disclosure:
                # Surface the exhaustive->fallback disclosure through the
                # result's `message` field too, not just the log, so it
                # actually reaches the end user via the websocket payload
                # and the PDF report (see worker.py / results_generator.py)
                # instead of being visible only in server logs.
                message_parts.append(fallback_disclosure)

            if len(full_history) > self.HISTORY_SAMPLE_LIMIT:
                step = len(full_history) / self.HISTORY_SAMPLE_LIMIT
                sampled_indices = [int(i * step) for i in range(self.HISTORY_SAMPLE_LIMIT)]
                history = [full_history[i] for i in sampled_indices]
                omitted = len(full_history) - len(history)
                sample_note = (
                    f"Histórico amostrado: mantidas {len(history)} de {len(full_history)} "
                    f"combinações testadas ({omitted} omitidas) para limitar o tamanho do "
                    f"resultado. combinations_tested reflete o total real, não apenas o "
                    f"histórico amostrado."
                )
                logger.info(sample_note)
                message_parts.append(sample_note)
            else:
                history = full_history

            message = " ".join(message_parts)

            return OptimalCombinationResult(
                success=True,
                message=message,
                best_model=best_model,
                combinations_tested=combinations_tested,
                history=history,
                target_achieved=target_achieved,
                best_grau_reached=best_grau_reached,
                exhaustive=exhaustive,
            )

        except Exception as e:
            logger.error(f"Error finding optimal combination: {str(e)}")
            return OptimalCombinationResult(success=False, message=f"Error: {str(e)}", error=str(e))
