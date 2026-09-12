"""An inflated count cannot replace a missing selected C06 obligation."""
import json
import xml.etree.ElementTree as ET

import pytest

from c15_local.aggregate_required import check_collection


@pytest.mark.parametrize("mutation", [
    None, "missing_file", "missing_call", "extra_call", "bad_call", "junit", "sha", "run", "exit",
])
def test_collection_cross_checks_obligations_and_execution(tmp_path, monkeypatch, mutation):
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    files = [
        "tests/comercial/test_c06_numeric_disclosure.py",
        "tests/comercial/test_c06_arbitration_policy.py",
        "tests/comercial/test_c06_output_conformance.py",
        "tests/comercial/test_c06_professional_report_ui.py",
        "tests/comercial/test_c06_commercial_surfaces.py",
        "tests/comercial/test_c06_qualification_integration.py",
        "tests/comercial/test_c06_document_flow.py",
        "tests/comercial/test_c06_cost_flow.py",
        "tests/comercial/test_c06_cost_consumer.py",
        "tests/comercial/test_c06_browser_document_flow.py",
        "tests/comercial/test_c06_browser_cost_flow.py",
        "tests/comercial/test_c06_recipient_document.py",
        "tests/comercial/test_c06_security_routes.py",
        "tests/comercial/test_c06_runtime_bootstrap.py",
        "tests/comercial/c06/test_catalog_distribution.py",
        "tests/pro_workflow/p04/test_nist_strd.py",
        "tests/comercial/c02/test_playwright_path.py",
        "tests/pro_workflow/p04/test_mutations_commercial.py",
    ]
    from c15_local import test_inventory
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({
        "schema": "MP-C06-TEST-INVENTORY/1",
        "nodeids": sorted(name + "::test_obligation" for name in files),
    }), encoding="utf-8")
    real_check = test_inventory.check_inventory
    monkeypatch.setattr(test_inventory, "check_inventory", lambda nodes: real_check(nodes, inventory))
    if mutation == "missing_file":
        files.pop()
    nodes = [name + "::test_obligation" for name in files]
    payload = {"schema": "MP-C06-COLLECTION/1", "tested_commit_sha": "a" * 40,
               "run_id": "123", "exit_code": 0, "nodeids": nodes,
               "calls": {node: {"outcome": "passed", "phase": "call"} for node in nodes}}
    if mutation == "missing_call":
        payload["calls"].pop(nodes[0])
    elif mutation == "extra_call":
        payload["calls"]["not_selected"] = {"outcome": "passed"}
    elif mutation == "bad_call":
        payload["calls"][nodes[0]] = {"outcome": "invented", "phase": "call"}
    elif mutation in {"sha", "run", "exit"}:
        payload[{"sha": "tested_commit_sha", "run": "run_id", "exit": "exit_code"}[mutation]] = "wrong"
    root = ET.Element("testsuite")
    for name in files[1:] if mutation == "junit" else files:
        ET.SubElement(root, "testcase", {
            "classname": name.removesuffix(".py").replace("/", "."),
            "name": "test_obligation",
        })
    ET.ElementTree(root).write(tmp_path / "wide.junit.xml")
    (tmp_path / "collection.json").write_text(json.dumps(payload), encoding="utf-8")
    assert bool(check_collection(tmp_path, "a" * 40)) == (mutation is not None)
