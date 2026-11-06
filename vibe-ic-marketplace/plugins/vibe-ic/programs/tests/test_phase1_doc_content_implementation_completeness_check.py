#!/usr/bin/env python3
"""Tests for phase1_doc_content_implementation_completeness_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest





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












def _source_contract(project: Path) -> Path:
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
