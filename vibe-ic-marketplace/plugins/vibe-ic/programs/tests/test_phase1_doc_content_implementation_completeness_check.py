#!/usr/bin/env python3
"""Tests for phase1_doc_content_implementation_completeness_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parent.parent /
        "phase1_doc_content_implementation_completeness_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _setup(tmp_path: Path, doc_text: str, l_docs: dict[str, dict],
           waivers: dict | None = None) -> Path:
    docs = tmp_path / "phase1" / "input_doc"
    docs.mkdir(parents=True)
    (docs / "spec.txt").write_text(doc_text, encoding="utf-8")
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    for name, content in l_docs.items():
        (gd / name).write_text(json.dumps(content))
    if waivers is not None:
        (tmp_path / "waivers.json").write_text(json.dumps(waivers))
    return tmp_path


def test_no_sections_skip(tmp_path):
    docs = tmp_path / "phase1" / "input_doc"
    docs.mkdir(parents=True)
    (docs / "spec.txt").write_text("plain prose, no headings here", encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "SKIP" in r.stdout


def test_high_coverage_pass(tmp_path):
    doc = (
        "1. Overview\nthis section describes the chip\n"
        "2. Pinout\npin list table\n"
        "3. Electrical Specs\nDC params\n"
    )
    l_docs = {
        "L1_DATASHEET.json": {"overview": "1. Overview content",
                              "pinout": "2. Pinout pin assignments",
                              "elec": "3. Electrical Specs full table"}
    }
    _setup(tmp_path, doc, l_docs)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_low_coverage_fail(tmp_path):
    doc = (
        "1. Overview\n2. Pinout\n3. Electrical\n4. Timing\n5. Protocol\n"
        "6. OTP\n7. Test Mode\n8. Calibration\n9. Package\n10. Ordering\n"
    )
    # Only 1 of 10 sections cited.
    l_docs = {
        "L1_DATASHEET.json": {"overview": "1. Overview content"}
    }
    _setup(tmp_path, doc, l_docs)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout


def test_waiver_per_section(tmp_path):
    doc = (
        "1. Overview\n2. Pinout\n3. Skipped Section\n"
    )
    l_docs = {
        "L1_DATASHEET.json": {"overview": "1. Overview content",
                              "pinout": "2. Pinout list"}
    }
    waivers = {
        "phase1_section_intentionally_unimplemented_skipped_section":
            "This section deliberately deferred per user agreement; reason "
            "documented in BACKLOG-v12 with foundry sign-off plan."
    }
    _setup(tmp_path, doc, l_docs, waivers)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_warn_band(tmp_path):
    # 80%-90% coverage should WARN (exit 0, "WARN" in stdout).
    doc = "\n".join(f"{i}. Section{i}\nbody{i}" for i in range(1, 11))
    l_docs = {
        "L1_DATASHEET.json": {
            "f1": "1. Section1", "f2": "2. Section2",
            "f3": "3. Section3", "f4": "4. Section4",
            "f5": "5. Section5", "f6": "6. Section6",
            "f7": "7. Section7", "f8": "8. Section8",
        }
    }
    _setup(tmp_path, doc, l_docs)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "WARN" in r.stdout or "PASS" in r.stdout


def _source_contract(project: Path) -> Path:
    sys.path.insert(0, str(PROG.parent))
    import l9_l19_contract_carrythrough as carry
    docs = project / "input/docs"
    docs.mkdir(parents=True)
    (docs / "L8_submodule_integration.md").write_text("""layer: L8
## 8.4 假如 Plugin 產生多個 sub-module
- 每個 sub-module **必須**內部完整、無懸空 port、無未連接的 input
- Top module **必須**例化所有有用的 sub-module,**禁止**留 stub
- 命名空間 **不得**與 PDK std-cell 命名衝突(避免 link 階段被誤認)
""")
    (docs / "L9_constraints.md").write_text("""layer: L9
# I/O delay
Input and output delay default to 20% of the clock period.
The plugin may override this default; an override must be recorded in declaration.json.
""")
    gd = project / "phase1/generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text("{}")
    (gd / "L19_CONSTRAINTS_PDK.json").write_text("{}")
    carry.run(project)
    return gd


def test_complete_owned_clauses_pass_actual_consumer(tmp_path):
    _source_contract(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_missing_owned_clause_is_rejected_by_actual_completeness_consumer(tmp_path):
    gd = _source_contract(tmp_path)
    path = gd / "L9_INTEGRATION_SPEC.json"
    doc = json.loads(path.read_text())
    rows = doc.get("integration", {}).get("architecture", [])
    assert rows, doc
    for row in rows:
        row["evidence"] = "\n".join(line for line in row["evidence"].splitlines()
                                    if "命名空間" not in line)
    path.write_text(json.dumps(doc))
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "命名空間" in result.stdout


@pytest.mark.parametrize("mutation", [
    "internal_completeness", "instantiation", "io_default", "override_disclosure",
    "conditional_context", "wrong_source", "wrong_owner",
])
def test_owned_clauses_require_their_actual_source_and_consumer(tmp_path, mutation):
    gd = _source_contract(tmp_path)
    l9_path, l19_path = gd / "L9_INTEGRATION_SPEC.json", gd / "L19_CONSTRAINTS_PDK.json"
    l9, l19 = json.loads(l9_path.read_text()), json.loads(l19_path.read_text())
    rows = l9["integration"]["architecture"]
    if mutation in {"internal_completeness", "instantiation", "conditional_context"}:
        token = {"internal_completeness": "無懸空", "instantiation": "例化所有",
                 "conditional_context": "假如 Plugin"}[mutation]
        for row in rows:
            row["evidence"] = "\n".join(line for line in row["evidence"].splitlines()
                                        if token not in line)
    elif mutation in {"io_default", "override_disclosure"}:
        token = "20%" if mutation == "io_default" else "declaration.json"
        record = l19["constraints"]["io_delay"]
        record["evidence"] = "\n".join(line for line in record["evidence"].splitlines()
                                       if token not in line)
    elif mutation == "wrong_source":
        for row in rows:
            row["source"] = "input/docs/unrelated.md"
    elif mutation == "wrong_owner":
        # Complete text in an unrelated L-doc cannot discharge L9 ownership.
        (gd / "L1_DATASHEET.json").write_text(json.dumps({"evidence": rows}))
        l9["integration"]["architecture"] = []
    l9_path.write_text(json.dumps(l9))
    l19_path.write_text(json.dumps(l19))
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "source-owned integration/timing obligations missing" in result.stdout
