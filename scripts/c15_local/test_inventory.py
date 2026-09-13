"""Regenerate or check the exact Linux wide-suite obligations, without running them.

Run from the repository root with its locked development environment:
python -m c15_local.test_inventory --write  # review the diff before committing
python -m c15_local.test_inventory          # fails on any added/removed obligation
"""
import argparse
import json
from pathlib import Path

INVENTORY = Path("docs/comercial/c06/mandatory-test-nodeids.json")


def check_inventory(nodes, path=INVENTORY):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected = payload["nodeids"]
        if (payload.get("schema") != "MP-C06-TEST-INVENTORY/1"
                or not isinstance(expected, list) or not expected
                or any(not isinstance(node, str) or "::" not in node for node in expected)
                or expected != sorted(set(expected))):
            raise ValueError("invalid inventory schema or nodeids")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"wide inventory: unreadable or invalid: {exc}"]
    missing = sorted(set(expected) - set(nodes))
    added = sorted(set(nodes) - set(expected))
    problems = []
    if len(nodes) != len(set(nodes)):
        problems.append("wide inventory: duplicate collected obligations")
    if missing:
        problems.append("wide inventory: missing obligations: " + ", ".join(missing))
    if added:
        problems.append("wide inventory: unrecorded obligations: " + ", ".join(added))
    return problems


def main():
    import pytest

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    class Collection:
        nodes = []

        def pytest_collection_finish(self, session):
            self.nodes = sorted(item.nodeid for item in session.items)

    collected = Collection()
    status = pytest.main(["tests", "--collect-only", "-q"], plugins=[collected])
    if status or not collected.nodes or len(collected.nodes) != len(set(collected.nodes)):
        return int(status) or 1
    if args.write:
        INVENTORY.write_text(json.dumps({
            "schema": "MP-C06-TEST-INVENTORY/1",
            "scope": "Linux mandatory wide suite: pytest tests, including collected platform skips",
            "nodeids": collected.nodes,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {len(collected.nodes)} obligations to {INVENTORY}; review and commit the diff.")
        return 0
    problems = check_inventory(collected.nodes)
    for problem in problems:
        print(problem)
    if not problems:
        print(f"Inventory matches all {len(collected.nodes)} collected obligations.")
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
