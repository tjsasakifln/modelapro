#!/usr/bin/env python3
"""Discover P01/P02/P03 pull requests by lote prefix. No hand-supplied IDs."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OWNER = "tjsasakifln"
REPO = "modelapro"
PREFIXES = {
    "P01": "[MP-PRO-20260911/P01]",
    "P02": "[MP-PRO-20260911/P02]",
    "P03": "[MP-PRO-20260911/P03]",
}
BRANCHES = {
    "P01": "mp-pro-20260911/p01-nucleo-reuso",
    "P02": "mp-pro-20260911/p02-rotina-interface",
    "P03": "mp-pro-20260911/p03-relatorio-tecnico",
}
SEAL_TOKEN = "SEALED"


def _gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


def discover() -> dict:
    matrix = {
        "campaign_id": "MP-PRO-20260911/P04",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_sha": "6d54f902b85a5a37bfbf154d39f74cf854ff9b2b",
        "rows": {},
    }
    listing = _gh(
        [
            "pr",
            "list",
            "--repo",
            f"{OWNER}/{REPO}",
            "--state",
            "all",
            "--limit",
            "100",
            "--json",
            "number,title,headRefName,headRefOid,baseRefName,isDraft,url,body,state",
        ]
    )
    prs = []
    if listing.returncode == 0 and listing.stdout.strip():
        prs = json.loads(listing.stdout)
    for pid, prefix in PREFIXES.items():
        matches = [pr for pr in prs if str(pr.get("title") or "").startswith(prefix)]
        if not matches:
            matches = [pr for pr in prs if pr.get("headRefName") == BRANCHES[pid]]
        chosen = matches[0] if matches else None
        comments = []
        sealed = False
        sealed_head = None
        if chosen:
            thread = _gh(
                [
                    "api",
                    f"repos/{OWNER}/{REPO}/issues/{chosen['number']}/comments",
                ]
            )
            if thread.returncode == 0 and thread.stdout.strip():
                comments = json.loads(thread.stdout)
            blob = (chosen.get("body") or "") + "\n" + "\n".join(c.get("body") or "" for c in comments)
            if SEAL_TOKEN in blob:
                sealed = True
                sealed_head = chosen.get("headRefOid")
        matrix["rows"][pid] = {
            "id": pid,
            "prefix": prefix,
            "branch": BRANCHES[pid],
            "pr": None if chosen is None else chosen.get("number"),
            "url": None if chosen is None else chosen.get("url"),
            "head": None if chosen is None else chosen.get("headRefOid"),
            "base": None if chosen is None else chosen.get("baseRefName"),
            "state": None if chosen is None else chosen.get("state"),
            "draft": None if chosen is None else chosen.get("isDraft"),
            "sealed": sealed,
            "sealed_head": sealed_head,
            "contracts": [],
            "evidence": [],
        }
    return matrix


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    matrix = discover()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(matrix, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v.get("pr") for k, v in matrix["rows"].items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
