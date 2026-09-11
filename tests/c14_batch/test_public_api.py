"""Structural checks: the shipped module exposes the MP/1 seam."""

from __future__ import annotations

import inspect

import modules.valuation_batch as vb


def test_evaluate_batch_is_the_public_entry():
    assert callable(vb.evaluate_batch)
    sig = inspect.signature(vb.evaluate_batch)
    params = list(sig.parameters)
    assert params[:5] == [
        "frozen_project",
        "subjects",
        "request_spec",
        "progress_callback",
        "cancel_requested",
    ]


def test_reuse_key_function_is_pure_and_stable():
    from tests.c14_batch.conftest import make_frozen_project, make_request_spec

    frozen = make_frozen_project()
    spec = make_request_spec()
    k1 = vb.compute_reuse_key(frozen, spec)
    k2 = vb.compute_reuse_key(frozen, spec)
    assert k1 == k2
    assert len(k1) == 64
