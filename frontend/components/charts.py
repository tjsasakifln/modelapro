"""Gráficos da avaliação em português (campanha C09).

Não expõe nomes internos (mean_ci80, residuals_vs_fitted) como legenda.
Valor ausente não vira zero no eixo.
"""

from __future__ import annotations

import base64
import math
from typing import Any, Mapping, Optional

import streamlit as st

from .layout import INTERVAL_LABELS, format_optional_number, present_snapshot

LEGACY_CAPTIONS = {
    "residuals_vs_fitted": "Resíduos em relação aos valores ajustados",
    "residuals_hist": "Distribuição dos resíduos",
    "observed_vs_estimated": "Preços observados e valores estimados",
}


def interval_chart_model(snapshot: Optional[Mapping[str, Any]]) -> Optional[dict]:
    """Especificação do gráfico de faixas. None se o ponto não foi calculado."""
    if not snapshot:
        return None
    value = snapshot.get("value") or {}
    point = value.get("point")
    if point is None:
        return None
    if isinstance(point, bool) or not isinstance(point, (int, float)) or not math.isfinite(point):
        return None

    target = snapshot.get("target") or {}
    series = [{
        "label": "Valor pontual",
        "low": point,
        "high": point,
        "kind": "point",
    }]
    for key, label in INTERVAL_LABELS:
        raw = value.get(key)
        if not isinstance(raw, Mapping):
            continue
        lower, upper = raw.get("lower"), raw.get("upper")
        if lower is None or upper is None:
            continue
        if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)):
            continue
        if not math.isfinite(lower) or not math.isfinite(upper):
            continue
        series.append({
            "label": label,
            "low": lower,
            "high": upper,
            "kind": key,
        })
    return {
        "title": "Valor e intervalos",
        "unit": target.get("unit") or "",
        "series": series,
        "language": "pt-BR",
        "point": point,
        "point_display": format_optional_number(point, unit=target.get("unit")),
    }


def render_charts(charts_data: dict) -> None:
    """Adaptador legado: imagens enviadas em base64, legendas em português."""
    if not charts_data:
        return

    st.subheader("Análise gráfica")
    columns = st.columns(max(1, min(3, len(charts_data))))
    items = list(charts_data.items())
    for index, (key, payload) in enumerate(items):
        caption = LEGACY_CAPTIONS.get(key, key.replace("_", " "))
        if caption == key.replace("_", " ") and key not in LEGACY_CAPTIONS:
            caption = {
                "residuals_vs_fitted": LEGACY_CAPTIONS["residuals_vs_fitted"],
            }.get(key, "Gráfico da análise")
        with columns[index % len(columns)]:
            try:
                st.image(
                    base64.b64decode(payload),
                    caption=caption,
                    use_container_width=True,
                )
            except Exception:
                st.caption(f"Gráfico «{caption}» indisponível.")


def render_value_charts(snapshot: Optional[Mapping[str, Any]]) -> None:
    model = interval_chart_model(snapshot)
    if model is None:
        st.caption("Valor pontual não calculado — o gráfico de intervalos foi omitido para não sugerir zero.")
        return

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        st.write(model)
        return

    labels = [item["label"] for item in model["series"]]
    lows = [item["low"] for item in model["series"]]
    highs = [item["high"] for item in model["series"]]
    centers = [(lo + hi) / 2 for lo, hi in zip(lows, highs)]
    xerr = [(hi - lo) / 2 for lo, hi in zip(lows, highs)]

    fig, ax = plt.subplots(figsize=(8, max(2.2, 0.55 * len(labels))))
    ax.errorbar(centers, range(len(labels)), xerr=xerr, fmt="o", color="#1f3d2b", ecolor="#8a6a2f", capsize=4)
    ax.set_yticks(range(len(labels)), labels)
    ax.invert_yaxis()
    unit = model.get("unit") or ""
    ax.set_xlabel(f"Valor ({unit})" if unit else "Valor")
    ax.set_title(model["title"])
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    fig.tight_layout()
    st.pyplot(fig, clear_figure=True)
    plt.close(fig)


def render_snapshot_charts(snapshot: Optional[Mapping[str, Any]]) -> None:
    """Ponto de entrada preferencial: snapshot MP/1, não o payload WS legado."""
    view = present_snapshot(snapshot)
    if view.get("empty"):
        return
    render_value_charts(snapshot)
    model = (snapshot or {}).get("model") or {}
    charts = model.get("charts") or (snapshot or {}).get("charts")
    if charts:
        render_charts(charts)
