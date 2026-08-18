"""phase1_evidence_grounding_check haystack must read EVERY text input-doc form,
RECURSIVELY — closes a false-fail found running the gate on the IC-datasheet corpus.

cv32e40p_p3 false-FAILed (131/146 literals "ungrounded") because its docs are
Sphinx `.rst` files in a NESTED `input/docs/source/` subdir, while the haystack
read only top-level `*.txt`. The real signals (`debug_req_i`, …) WERE in
`source/debug.rst` — the gate just never read them. Fix: recurse + read
.txt/.md/.rst/.adoc. Without this the gate leaks the WRONG way (false-fails a
faithful extraction), which would block a legitimate markdown/RST-input project.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import phase1_evidence_grounding_check as G  # noqa: E402


def _proj(tmp_path, doc_relpath: str, doc_text: str, literal: str):
    docp = tmp_path / "input" / "docs" / doc_relpath
    docp.parent.mkdir(parents=True, exist_ok=True)
    docp.write_text(doc_text)
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "core",
        "extraction_evidence": {f"input/docs/{doc_relpath}": [
            {"literal": literal, "label": "port"}]}}))
    return tmp_path


def test_nested_rst_input_grounds(tmp_path):
    # the cv32e40p_p3 shape: a .rst doc in a nested source/ subdir
    p = _proj(tmp_path, "source/debug.rst",
              "The debug_req_i signal requests entry to Debug Mode.\n",
              "``debug_req_i`` input Request to enter Debug Mode")
    assert G.check(p)["status"] == "PASS"


def test_markdown_input_grounds(tmp_path):
    p = _proj(tmp_path, "README.md",
              "The core exposes `irq_ack_o` to acknowledge interrupts.\n",
              "irq_ack_o acknowledge")
    assert G.check(p)["status"] == "PASS"


def test_fabrication_still_caught_with_rst_present(tmp_path):
    # a real .rst doc present, but the literal names a signal NOT in it -> FAIL
    p = _proj(tmp_path, "source/ports.rst",
              "The core has clk_i and rst_ni.\n",
              "phantom_xyz_o interrupt asserted")
    res = G.check(p)
    assert res["status"] == "FAIL"
    assert any("phantomxyzo" in u["missing_identifiers"] for u in res["ungrounded"])
