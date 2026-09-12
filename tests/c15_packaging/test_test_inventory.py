"""Exact obligations catch deletion/replacement even when the total stays green."""
import json

import pytest

from c15_local.test_inventory import check_inventory


@pytest.mark.parametrize("mutation", [None, "missing", "added", "replaced", "duplicate", "empty", "malformed"])
def test_inventory_rejects_changed_obligations(tmp_path, mutation):
    path = tmp_path / "inventory.json"
    expected = ["tests/test_a.py::test_first", "tests/test_b.py::test_second"]
    path.write_text(json.dumps({"schema": "MP-C06-TEST-INVENTORY/1", "nodeids": expected}), encoding="utf-8")
    nodes = list(expected)
    if mutation == "missing":
        nodes.pop()
    elif mutation == "added":
        nodes.append("tests/test_c.py::test_new")
    elif mutation == "replaced":
        nodes[-1] = "tests/test_c.py::test_replacement"
    elif mutation == "duplicate":
        nodes.append(nodes[0])
    elif mutation == "empty":
        path.write_text('{"schema":"MP-C06-TEST-INVENTORY/1","nodeids":[]}', encoding="utf-8")
    elif mutation == "malformed":
        path.write_text("{", encoding="utf-8")
    assert bool(check_inventory(nodes, path)) == (mutation is not None)


def test_absent_inventory_is_not_an_empty_approval(tmp_path):
    assert check_inventory(["tests/test_a.py::test_first"], tmp_path / "absent.json")
