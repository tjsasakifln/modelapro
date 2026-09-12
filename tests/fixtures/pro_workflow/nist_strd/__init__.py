"""NIST/ITL Statistical Reference Datasets (StRD), linear least squares.

Externally-sourced numeric reference material for MP-PRO P04 / MP-COM-20260912
C06 acceptance item C06-A02. The certified values in `datasets.py` were produced
by NIST, not by MODELA PRO and not by this repository's oracle.

Scope, stated plainly: StRD exercises ARITHMETIC ONLY. Agreement with these
certified values is *not a certification of MODELA PRO*, is not an ABNT/NBR
normative act, and says nothing about real-estate valuation practice or about
institutional acceptance of any report. See PROVENANCE.md.

This package must not import from modules/, backend/ or frontend/.
"""

from .datasets import DATASETS, RETRIEVAL_DATE, SOURCE_URL_TEMPLATE

__all__ = ["DATASETS", "RETRIEVAL_DATE", "SOURCE_URL_TEMPLATE"]
