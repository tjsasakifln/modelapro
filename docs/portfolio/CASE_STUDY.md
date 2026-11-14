# Modela Pro: Engineering and software case study

## Problem

Real estate valuation combines market observations, statistical modeling, professional judgment and reporting. A useful digital workflow must preserve data provenance and make assumptions visible instead of producing an unexplained number.

## System boundaries

- **Backend and orchestration:** [FastAPI service](../../backend/) and modules for dataset ingestion, model evaluation and frozen result snapshots.
- **User interface:** [Streamlit frontend](../../frontend/) for local interactions.
- **Outputs:** [PDF and reporting modules](../../modules/), with output generation separated from the frozen calculation result.
- **Verification:** [Automated tests](../../tests/), including component and acceptance-oriented suites.
- **Deployment model:** local workstation. [Security policy](../../SECURITY.md) explicitly excludes shared or Internet-facing deployment of the complete application.

## Engineering decisions visible in the repository

1. Separate input ingestion, modeling and reporting, keeping module boundaries inspectable.
2. Preserve a frozen calculation snapshot before producing downstream reports, so PDF rendering does not silently recalculate a result.
3. Distinguish known data and explicit unknowns; do not silently infer missing units, dates or target variables.
4. Document limitations and unverified normative rules instead of presenting a calculation as an automatically certified appraisal.
5. Provide test suites and reproducible local commands, while distinguishing documented tests from confirmed execution in any given environment.

## Reproduce and inspect

Start with the [README](../../README.md) for installation instructions and platform-specific dependencies. The package requires Python 3.11+ according to [pyproject.toml](../../pyproject.toml). The README contains Linux-oriented setup guidance and names the validation commands. **Those commands are documented, not represented here as having been run as part of this portfolio publication.**

A reviewer can inspect:

- [Core modeling modules](../../modules/)
- [Test suite](../../tests/)
- [Acceptance scripts](../../scripts/c17_acceptance/)
- [Security boundary and unresolved release conditions](../../SECURITY.md)

## Status and limitations

This repository is a work in progress. It does not independently establish statistical suitability for every use case, conformity with all provisions of NBR 14653, production scalability or authorization to issue professional valuation reports. Real-world appraisal decisions remain with appropriately qualified professionals.

## Why this project matters

This case illustrates how engineering-domain constraints influence software architecture: transparent assumptions, controlled calculations, provenance, reproducibility and documented limits. It is one example in the [maintainer's broader portfolio](https://github.com/tjsasakifln/devflow/blob/main/PORTFOLIO.md).
