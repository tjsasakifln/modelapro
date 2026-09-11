"""C05 search space: counting, units, domain filters, exact and diverse enumeration.

Pure functions with no I/O. Candidate generation does not fit models.
Transformations of indicators are not proposed; categorical groups stay grouped.
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "MP/1"
NON_LINEAR_TRANSFORMATIONS: Tuple[str, ...] = (
    "ln",
    "sqrt",
    "inverse",
    "sqr",
    "inv_sqr",
    "inv_sqrt",
)
LINEAR_OPTION = "linear"
GROUP_OPTION = "encoded"
Y_IDENTITY = "identity"
INCLUDE_OPTIONS_POSITIVE = 1 + len(NON_LINEAR_TRANSFORMATIONS)  # 7

# Domain-true aliases only. Train-set numerical coincidence is not equivalence.
_TRANSFORM_ALIASES = {
    None: LINEAR_OPTION,
    "identity": LINEAR_OPTION,
    "none": LINEAR_OPTION,
    LINEAR_OPTION: LINEAR_OPTION,
}


@dataclass(frozen=True)
class SearchUnit:
    unit_id: str
    kind: str  # "quantitative" | "group"
    base_variable: str
    columns: Tuple[str, ...]
    options: Tuple[str, ...]  # include-options only; exclusion is implicit


def count_exhaustive_candidates(
    option_counts: Sequence[int],
    max_vars: Optional[int] = None,
) -> int:
    """Exact candidate count for inclusion x one-option-per-unit, excluding the empty model.

    For each unit, exclude (factor 1) or include one of ``option_counts[i]``
    domain-valid include-options. If ``max_vars`` is None, this is
    ``prod(c_i + 1) - 1``. With a cap, a 0/1-knapsack DP counts only models
    with 1..max_vars included units.
    """
    counts = [int(c) for c in option_counts]
    if not counts:
        return 0
    if max_vars is None:
        total = 1
        for c in counts:
            total *= c + 1
        return total - 1
    max_vars = int(max_vars)
    if max_vars <= 0:
        return 0
    dp = [1] + [0] * max_vars
    for c in counts:
        for j in range(max_vars, 0, -1):
            dp[j] += dp[j - 1] * c
    return sum(dp[1 : max_vars + 1])


def canonical_transform_name(name: Optional[str]) -> str:
    if name in _TRANSFORM_ALIASES:
        return _TRANSFORM_ALIASES[name]
    return str(name)


def transforms_are_domain_equivalent(a: Optional[str], b: Optional[str]) -> bool:
    """True only for proven domain aliases (linear/identity), never train-only coincidence."""
    return canonical_transform_name(a) == canonical_transform_name(b)


def dedupe_include_options(options: Sequence[str]) -> Tuple[str, ...]:
    seen = []
    seen_canon = set()
    for opt in options:
        key = canonical_transform_name(opt)
        if key in seen_canon:
            continue
        seen_canon.add(key)
        seen.append(opt if opt is not None else LINEAR_OPTION)
    return tuple(seen)


def domain_valid_include_options(
    series,
    subject_value: Optional[float] = None,
    apply_transformation=None,
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """Linear plus each non-linear transform valid on the training series and subject.

    Returns (include_options, dropped_for_subject).
    """
    if apply_transformation is None:
        from .transformations import Transformer

        apply_transformation = Transformer.apply_transformation

    options: List[str] = [LINEAR_OPTION]
    dropped_for_subject: List[str] = []
    for trans_name in NON_LINEAR_TRANSFORMATIONS:
        _, ok = apply_transformation(series, trans_name)
        if not ok:
            continue
        if subject_value is not None:
            import pandas as pd

            _, subject_ok = apply_transformation(
                pd.Series([subject_value]), trans_name
            )
            if not subject_ok:
                dropped_for_subject.append(trans_name)
                continue
        options.append(trans_name)
    return dedupe_include_options(options), tuple(dropped_for_subject)


def parse_feature_name(col: str) -> Tuple[str, str]:
    """Return (transform, base) for 'ln(area)' or ('linear', col)."""
    if "(" in col and col.endswith(")"):
        return col[: col.index("(")], col[col.index("(") + 1 : -1]
    return LINEAR_OPTION, col


def feature_column_name(base: str, transform: str) -> str:
    t = canonical_transform_name(transform)
    if t in (LINEAR_OPTION, GROUP_OPTION):
        return base
    return f"{t}({base})"


def candidate_id_for(
    base_choices: Sequence[Tuple[str, str]],
    y_transformation: str = Y_IDENTITY,
    intercept: bool = True,
) -> str:
    parts = [
        f"{base}:{canonical_transform_name(opt)}"
        for base, opt in sorted(base_choices, key=lambda x: x[0])
    ]
    y_name = canonical_transform_name(y_transformation)
    if y_name == LINEAR_OPTION:
        y_name = Y_IDENTITY
    parts.append(f"y:{y_name}")
    parts.append("int:1" if intercept else "int:0")
    return "|".join(parts)


def build_candidate_spec(
    units: Sequence[SearchUnit],
    options: Sequence[str],
    y_transformation: str = Y_IDENTITY,
    intercept: bool = True,
) -> Dict[str, Any]:
    if len(units) != len(options):
        raise ValueError("units and options must have the same length")
    features: List[str] = []
    base_variables: List[str] = []
    feature_groups: Dict[str, List[str]] = {}
    x_transformations: Dict[str, str] = {}
    choices: List[Tuple[str, str]] = []
    for unit, opt in zip(units, options):
        opt_c = canonical_transform_name(opt) if unit.kind != "group" else (
            GROUP_OPTION if canonical_transform_name(opt) == LINEAR_OPTION else canonical_transform_name(opt)
        )
        if unit.kind == "group":
            opt_c = GROUP_OPTION
            feature_groups[unit.unit_id] = list(unit.columns)
            features.extend(unit.columns)
            x_transformations[unit.base_variable] = GROUP_OPTION
        else:
            features.append(feature_column_name(unit.base_variable, opt_c))
            x_transformations[unit.base_variable] = opt_c
        base_variables.append(unit.base_variable)
        choices.append((unit.base_variable, opt_c))
    y_name = canonical_transform_name(y_transformation)
    if y_name == LINEAR_OPTION:
        y_name = Y_IDENTITY
    spec = {
        "candidate_id": candidate_id_for(choices, y_name, intercept),
        "features": features,
        "base_variables": base_variables,
        "feature_groups": feature_groups,
        "x_transformations": x_transformations,
        "y_transformation": {"name": y_name},
        "intercept": bool(intercept),
    }
    return spec


def resolve_authorized_base_variables(
    request_spec: Mapping[str, Any],
    available_names: Sequence[str],
    target_col: Optional[str] = None,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Resolve candidate_cols: null/missing = auto-by-role; [] = none authorized.

    Returns (authorized_names, issues). An empty authorized list with an error
    issue means the caller must not search.
    """
    issues: List[Dict[str, Any]] = []
    available = [n for n in available_names if n != target_col and n != "row_id"]
    roles = request_spec.get("roles") if isinstance(request_spec.get("roles"), dict) else {}

    def auto_by_role() -> List[str]:
        predictor_roles = {n for n, role in roles.items() if role == "predictor"}
        blocked = {
            n
            for n, role in roles.items()
            if role in ("target", "identifier", "source", "date", "excluded")
        }
        if predictor_roles:
            return [n for n in available if n in predictor_roles and n not in blocked]
        return [n for n in available if n not in blocked]

    if "candidate_cols" not in request_spec:
        authorized = auto_by_role()
        return authorized, issues

    cols = request_spec.get("candidate_cols")
    if cols is None:
        return auto_by_role(), issues

    if not isinstance(cols, (list, tuple)):
        issues.append(
            _issue(
                "invalid_candidate_cols",
                "error",
                "candidate_cols must be null (auto-by-role) or a list of names; "
                "an empty list authorizes no variables.",
            )
        )
        return [], issues

    if len(cols) == 0:
        issues.append(
            _issue(
                "no_authorized_variables",
                "error",
                "candidate_cols=[] authorizes no variables (it does not mean all). "
                "Use null for automatic selection by role.",
            )
        )
        return [], issues

    requested = [str(c) for c in cols]
    available_set = set(available)
    unknown = [c for c in requested if c not in available_set]
    authorized = [c for c in requested if c in available_set]
    if unknown:
        issues.append(
            _issue(
                "unknown_candidate_cols",
                "warning",
                "candidate_cols names are not available as predictors: "
                + ", ".join(unknown),
                affected_ids=unknown,
                evidence={"unknown": unknown, "available": list(available)},
            )
        )
    if not authorized:
        issues.append(
            _issue(
                "no_authorized_variables",
                "error",
                "No requested candidate_cols remain after dropping unknown or blocked names.",
                affected_ids=unknown,
            )
        )
    return authorized, issues


def _issue(
    code: str,
    severity: str,
    message: str,
    affected_ids: Optional[List[str]] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "origin": "C05",
        "message": message,
        "affected_ids": list(affected_ids or []),
        "evidence": dict(evidence or {}),
    }


def search_units_from_prepared(
    prepared_dataset: Mapping[str, Any],
    authorized: Sequence[str],
    subject_raw: Optional[Mapping[str, Any]] = None,
    apply_transformation=None,
) -> Tuple[List[SearchUnit], List[Dict[str, Any]]]:
    """Build search units from a PreparedDataset mapping.

    Quantitative columns get domain-valid include-options. Categorical groups
    are a single unit (all indicator columns together, no transforms).
    """
    issues: List[Dict[str, Any]] = []
    schema = prepared_dataset.get("feature_schema") or {}
    columns_meta = schema.get("columns") or {}
    groups_meta = schema.get("groups") or {}
    base_frame = prepared_dataset.get("base_frame")
    X = prepared_dataset.get("X")
    frame = base_frame if base_frame is not None else X

    authorized_set = set(authorized)
    grouped_columns = set()
    units: List[SearchUnit] = []
    seen_groups = set()

    for group_id, gmeta in groups_meta.items():
        g_cols = list(gmeta.get("columns") or [])
        base_var = gmeta.get("base_variable") or group_id
        if base_var not in authorized_set and group_id not in authorized_set:
            if not any(c in authorized_set for c in g_cols):
                continue
        if not g_cols:
            continue
        seen_groups.add(group_id)
        grouped_columns.update(g_cols)
        grouped_columns.add(base_var)
        units.append(
            SearchUnit(
                unit_id=str(group_id),
                kind="group",
                base_variable=str(base_var),
                columns=tuple(g_cols),
                options=(GROUP_OPTION,),
            )
        )

    quantitative_names: List[str] = []
    for name in authorized:
        if name in grouped_columns:
            continue
        meta = columns_meta.get(name) or {}
        kind = meta.get("kind")
        group_id = meta.get("group_id")
        if group_id and group_id in seen_groups:
            continue
        if kind == "categorical":
            continue
        quantitative_names.append(name)

    dropped_by_var: Dict[str, Tuple[str, ...]] = {}
    for name in quantitative_names:
        series = None
        if frame is not None and name in getattr(frame, "columns", []):
            series = frame[name]
        elif X is not None and name in getattr(X, "columns", []):
            series = X[name]
        subject_value = None
        if subject_raw is not None and name in subject_raw:
            subject_value = subject_raw[name]
        if series is None:
            options = (LINEAR_OPTION,)
            dropped: Tuple[str, ...] = ()
        else:
            options, dropped = domain_valid_include_options(
                series, subject_value=subject_value, apply_transformation=apply_transformation
            )
        if dropped:
            dropped_by_var[name] = dropped
        units.append(
            SearchUnit(
                unit_id=name,
                kind="quantitative",
                base_variable=name,
                columns=(name,),
                options=options,
            )
        )

    if dropped_by_var:
        issues.append(
            _issue(
                "domain_exclusion",
                "info",
                "Transforms domain-invalid for the training column or the subject "
                "were dropped from the search space, not scored.",
                affected_ids=list(dropped_by_var.keys()),
                evidence={"dropped_transforms": {k: list(v) for k, v in dropped_by_var.items()}},
            )
        )
    return units, issues


def derived_max_vars(
    n_rows: int,
    n_units: int,
    search_policy: Optional[Mapping[str, Any]] = None,
    evaluation_policy: Optional[Mapping[str, Any]] = None,
) -> int:
    """Variable cap. Never defaults to an arbitrary five-variable norm."""
    search_policy = search_policy or {}
    evaluation_policy = evaluation_policy or {}
    n_units = max(0, int(n_units))
    if n_units == 0:
        return 0
    if search_policy.get("max_variables") is not None:
        try:
            cap = int(search_policy["max_variables"])
        except (TypeError, ValueError):
            cap = n_units
        return max(1, min(cap, n_units))

    rule = evaluation_policy.get("sample_size_rule")
    if rule == "nbr_item2_grau1":
        # Tabela 1 item 2 loosest: n >= 3(k+1) => k <= floor(n/3) - 1
        n_rows = int(n_rows)
        cap = max(1, n_rows // 3 - 1)
        return min(cap, n_units)
    return n_units


def iter_exact_candidates(
    units: Sequence[SearchUnit],
    max_vars: int,
    y_transformation: str = Y_IDENTITY,
    intercept: bool = True,
) -> Iterator[Dict[str, Any]]:
    units = list(units)
    max_vars = min(int(max_vars), len(units))
    if max_vars <= 0 or not units:
        return
        yield  # pragma: no cover — makes this a generator
    for k in range(1, max_vars + 1):
        for subset in itertools.combinations(units, k):
            option_lists = [u.options for u in subset]
            for choice in itertools.product(*option_lists):
                yield build_candidate_spec(subset, choice, y_transformation, intercept)


def _product_size(units: Sequence[SearchUnit]) -> int:
    total = 1
    for u in units:
        total *= max(1, len(u.options))
    return total


def _sample_option_products(
    units: Sequence[SearchUnit],
    n: int,
    rng: random.Random,
    skip: Optional[set] = None,
) -> List[Tuple[str, ...]]:
    skip = set(skip or ())
    option_lists = [list(u.options) for u in units]
    total = _product_size(units)
    out: List[Tuple[str, ...]] = []
    if total <= n + len(skip):
        for choice in itertools.product(*option_lists):
            if choice in skip:
                continue
            out.append(choice)
            if len(out) >= n:
                break
        return out
    seen = set(skip)
    attempts = 0
    limit = max(n * 30, 32)
    while len(out) < n and attempts < limit:
        attempts += 1
        choice = tuple(rng.choice(opts) for opts in option_lists)
        if choice in seen:
            continue
        seen.add(choice)
        out.append(choice)
    return out


def iter_diverse_candidates(
    units: Sequence[SearchUnit],
    max_vars: int,
    budget: int,
    seed: int = 0,
    y_transformation: str = Y_IDENTITY,
    intercept: bool = True,
) -> Iterator[Dict[str, Any]]:
    """Budgeted approximate enumerator that covers every search unit.

    Does not rank by univariate correlation and does not keep only 15
    transformed columns or cap at five variables. Yields at most ``budget``
    unique CandidateSpec mappings. Never a proof of global optimality.
    """
    units = list(units)
    max_vars = min(int(max_vars), len(units))
    budget = int(budget)
    if budget <= 0 or max_vars <= 0 or not units:
        return
        yield  # pragma: no cover
    rng = random.Random(int(seed))
    emitted = set()

    def emit(subset: Sequence[SearchUnit], choice: Sequence[str]):
        spec = build_candidate_spec(subset, choice, y_transformation, intercept)
        cid = spec["candidate_id"]
        if cid in emitted:
            return None
        emitted.add(cid)
        return spec

    # Phase 1: one default include per unit so every base/group is represented.
    for u in units:
        spec = emit((u,), (u.options[0],))
        if spec is not None:
            yield spec
            if len(emitted) >= budget:
                return

    coverage = {i: 1 for i in range(len(units))}

    def yield_default_combos(k: int):
        combos = list(itertools.combinations(range(len(units)), k))
        rng.shuffle(combos)
        while combos and len(emitted) < budget:
            combos.sort(key=lambda c: (min(coverage[i] for i in c), sum(coverage[i] for i in c)))
            combo = combos.pop(0)
            subset = [units[i] for i in combo]
            default_choice = tuple(u.options[0] for u in subset)
            spec = emit(subset, default_choice)
            if spec is not None:
                yield spec
            for i in combo:
                coverage[i] += 1

    # Phase 2: default pairs/higher-k before exhausting singleton transforms,
    # so a weakly correlated unit still appears jointly with others under a small budget.
    for k in range(2, max_vars + 1):
        for spec in yield_default_combos(k):
            yield spec
            if len(emitted) >= budget:
                return

    # Phase 3: remaining include-options of each unit (transform diversity).
    for u in units:
        for opt in u.options[1:]:
            spec = emit((u,), (opt,))
            if spec is not None:
                yield spec
                if len(emitted) >= budget:
                    return

    # Phase 4: extra transform variants of higher-k subsets already covered.
    for k in range(2, max_vars + 1):
        combos = list(itertools.combinations(range(len(units)), k))
        rng.shuffle(combos)
        for combo in combos:
            if len(emitted) >= budget:
                return
            subset = [units[i] for i in combo]
            default_choice = tuple(u.options[0] for u in subset)
            remaining = budget - len(emitted)
            extra = _sample_option_products(
                subset,
                n=min(remaining, 8, max(0, _product_size(subset) - 1)),
                rng=rng,
                skip={default_choice},
            )
            for choice in extra:
                spec = emit(subset, choice)
                if spec is not None:
                    yield spec
                    if len(emitted) >= budget:
                        return


def possible_count_for_units(units: Sequence[SearchUnit], max_vars: int) -> int:
    return count_exhaustive_candidates([len(u.options) for u in units], max_vars=max_vars)


def y_transformations_from_policy(search_policy: Optional[Mapping[str, Any]]) -> List[str]:
    search_policy = search_policy or {}
    raw = search_policy.get("y_transformations")
    if not raw:
        return [Y_IDENTITY]
    out = []
    seen = set()
    for name in raw:
        canon = canonical_transform_name(name)
        if canon == LINEAR_OPTION:
            canon = Y_IDENTITY
        if canon in seen:
            continue
        seen.add(canon)
        out.append(canon)
    return out or [Y_IDENTITY]


def iter_search_candidates(
    units: Sequence[SearchUnit],
    max_vars: int,
    mode: str,
    budget: int,
    seed: int,
    y_transformations: Optional[Sequence[str]] = None,
    intercept: bool = True,
) -> Iterator[Dict[str, Any]]:
    y_list = list(y_transformations or [Y_IDENTITY])
    if mode == "exact":
        for y_t in y_list:
            yield from iter_exact_candidates(units, max_vars, y_t, intercept)
        return
    remaining = int(budget)
    if remaining <= 0:
        return
        yield  # pragma: no cover
    share = max(1, remaining // max(1, len(y_list)))
    for i, y_t in enumerate(y_list):
        # Last transform gets the remainder.
        this_budget = share if i < len(y_list) - 1 else remaining
        n_before = 0
        for spec in iter_diverse_candidates(
            units, max_vars, this_budget, seed + i, y_t, intercept
        ):
            n_before += 1
            yield spec
        remaining -= n_before
        if remaining <= 0:
            return
