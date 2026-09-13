#!/usr/bin/env python3
"""Verify that every applied threshold traces to a consulted source.

Two independent checks, both runnable without redistributing the standards:

  1. INTERNAL COHERENCE (always runnable, no protected file needed)
     Every numeric constant the product applies must have a matching entry in
     normative_rules.THRESHOLD_PROVENANCE, and the recorded value must equal
     the constant it documents. A provenance record that drifts away from the
     code it describes is treated as a defect, not as documentation.

  2. SOURCE INTEGRITY (only when the licensed copies are present locally)
     Re-hashes the files under docs/normas/ and compares with the sha256
     recorded in normative_rules.SOURCE_DOCUMENTS. The standards are
     copyright-protected and git-ignored; this script never copies, prints or
     redistributes their content — only digests.

Exit codes: 0 all checks passed; 1 a mismatch was found; 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from modules import normative_rules as rules  # noqa: E402

#: Each provenance key mapped to the constants it must agree with.
CONSTANT_BINDINGS = {
    "ITEM2_FACTORS": {"grau_iii": 6, "grau_ii": 4, "grau_i": 3},
    "MEASURE_LOWER_FACTOR": {"factor": rules.MEASURE_LOWER_FACTOR},
    "MEASURE_UPPER_FACTOR": {"factor": rules.MEASURE_UPPER_FACTOR},
    "VALUE_LIMITS": {
        "grau_ii": rules.VALUE_LIMIT_GRAU_II,
        "grau_i": rules.VALUE_LIMIT_GRAU_I,
    },
    "ITEM5_LIMITS": {
        "grau_iii": rules.ITEM5_LIM_III,
        "grau_ii": rules.ITEM5_LIM_II,
        "grau_i": rules.ITEM5_LIM_I,
    },
    "ITEM6_LIMITS": {
        "grau_iii": rules.ITEM6_LIM_III,
        "grau_ii": rules.ITEM6_LIM_II,
        "grau_i": rules.ITEM6_LIM_I,
    },
    "TABELA2_PONTOS": {
        "grau_iii": rules.TABELA2_PONTOS_III,
        "grau_ii": rules.TABELA2_PONTOS_II,
        "grau_i": rules.TABELA2_PONTOS_I,
    },
    "PRECISAO_LIMITS": {
        "grau_iii": rules.PRECISAO_LIM_III,
        "grau_ii": rules.PRECISAO_LIM_II,
        "grau_i": rules.PRECISAO_LIM_I,
    },
    "CAMPO_ARBITRIO": {"amplitude": rules.CAMPO_ARBITRIO},
    "TABELA7_PONTOS_CUSTO": {
        "grau_iii": rules.TABELA7_PONTOS_III,
        "grau_ii": rules.TABELA7_PONTOS_II,
        "grau_i": rules.TABELA7_PONTOS_I,
    },
    "MICRONUMEROSIDADE": {
        "n_min_factor": 3,
        "ni_small": rules.minimum_ni(10),
        "ni_large": rules.minimum_ni(500),
        "n_small_max": 30,
        "n_mid_max": 100,
        "ni_mid_fraction": 0.10,
    },
    "SIGNIFICANCE_AUX": {"max_alpha": rules.max_auxiliary_alpha()},
    "CORRELATION_ATTENTION": {"threshold": 0.80},
}

REQUIRED_PROVENANCE_FIELDS = ("edition", "clause", "page", "literal", "detail")


def check_internal_coherence() -> list[str]:
    problems: list[str] = []
    for key, expected in CONSTANT_BINDINGS.items():
        record = rules.THRESHOLD_PROVENANCE.get(key)
        if record is None:
            problems.append(f"{key}: sem entrada em THRESHOLD_PROVENANCE")
            continue
        for field in REQUIRED_PROVENANCE_FIELDS:
            if field not in record:
                problems.append(f"{key}: proveniência sem campo {field!r}")
        values = record.get("values") or {}
        for name, want in expected.items():
            got = values.get(name)
            if got is None:
                problems.append(f"{key}.{name}: ausente na proveniência")
            elif abs(float(got) - float(want)) > 1e-12:
                problems.append(
                    f"{key}.{name}: proveniência registra {got!r} mas o código aplica {want!r}"
                )
    for key in rules.THRESHOLD_PROVENANCE:
        if key not in CONSTANT_BINDINGS:
            problems.append(f"{key}: proveniência sem vínculo com constante verificada")

    # Any threshold whose provenance is an interpretation must say so.
    upper = rules.THRESHOLD_PROVENANCE["MEASURE_UPPER_FACTOR"]
    if upper.get("literal") is not False or not upper.get("alternative_reading"):
        problems.append(
            "MEASURE_UPPER_FACTOR: leitura do 'superiores a 100%' deve permanecer "
            "marcada como interpretação, com a leitura alternativa registrada"
        )

    audit = rules.inventory_audit()
    if not audit["complete"]:
        problems.append(f"inventário incompleto: {audit['missing_destination']}")
    return problems


def check_source_integrity(normas_dir: Path) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    notes: list[str] = []
    by_sha = {doc["sha256"]: (edition, doc)
              for edition, doc in rules.SOURCE_DOCUMENTS.items()}
    if not normas_dir.is_dir():
        notes.append(
            f"{normas_dir} ausente: integridade das fontes NÃO verificada nesta execução "
            "(as normas são protegidas e não são versionadas)."
        )
        return problems, notes
    seen: set[str] = set()
    for path in sorted(normas_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in by_sha:
            edition, _ = by_sha[digest]
            seen.add(digest)
            notes.append(f"OK  {edition}: sha256 confere ({path.name})")
        else:
            notes.append(
                f"--  {path.name}: sha256 {digest[:16]}… não corresponde a nenhuma "
                "fonte registrada (exemplar diferente ou norma não catalogada)"
            )
    for digest, (edition, doc) in by_sha.items():
        if digest not in seen:
            problems.append(
                f"{edition}: exemplar registrado (sha256 {digest[:16]}…) não encontrado "
                f"em {normas_dir}; o limiar correspondente não pode ser reconferido aqui"
            )
    return problems, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--normas-dir", default=str(ROOT / "docs" / "normas"),
                    help="diretório com os exemplares licenciados (não versionado)")
    ap.add_argument("--json", action="store_true", help="saída em JSON")
    ap.add_argument("--require-sources", action="store_true",
                    help="falhar se os exemplares licenciados não estiverem presentes")
    args = ap.parse_args()

    coherence = check_internal_coherence()
    integrity, notes = check_source_integrity(Path(args.normas_dir))

    sources_present = any(n.startswith("OK ") for n in notes)
    problems = list(coherence)
    if args.require_sources:
        problems.extend(integrity)
        if not sources_present:
            problems.append(
                "--require-sources exigido mas nenhum exemplar registrado foi encontrado"
            )

    report = {
        "internal_coherence": {"problems": coherence, "ok": not coherence},
        "source_integrity": {
            "problems": integrity,
            "notes": notes,
            "sources_present": sources_present,
        },
        "inventory": rules.inventory_audit(),
        "currency_note": (
            "A VIGÊNCIA das edições não é verificada por este script: o catálogo ABNT "
            "não entrega o registro da norma por requisição estática. Conferido aqui é "
            "que os limiares aplicados correspondem às edições efetivamente consultadas."
        ),
        "ok": not problems,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("== coerência interna limiar<->proveniência ==")
        print("  OK" if not coherence else "\n".join("  FALHA " + p for p in coherence))
        print("== integridade das fontes ==")
        for n in notes:
            print("  " + n)
        for p in integrity:
            print("  PENDENTE " + p)
        print("== inventário de regras ==")
        print("  " + json.dumps(report["inventory"]["counts"], ensure_ascii=False))
        print("== vigência ==")
        print("  " + report["currency_note"])
        print("\nRESULTADO:", "OK" if report["ok"] else "FALHA")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(2)
