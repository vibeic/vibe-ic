#!/usr/bin/env python3
"""FX_P2_DECLARATION_BEFORE_STEP4 — the design's option selection is emitted
before Step 4 reads it, by the SAME producer, and a later emission that
disagrees refuses by name.

Step 4's gate narrows the conditional L10 cases (`applies_when`, R-0915-102)
against `plugin_output/declaration.json`. `step_arith_declaration_emit` wrote
that file at phase-2 row 33, after Step 4 at row 20, so on a FIRST run the gate
never saw a selection the producer could already derive, and a case the design
excludes stayed blocking; only a re-run tree was narrowed. The contract-driven
producer (`spec_declaration_emit`) reads only the design input, the RTL's
`key = value` comment blocks and a prior declaration, so the runner now asks it
before Step 4 as well (`declaration_before_step4`), and row 33 refuses when the
later emission is not identical or a superset (`declaration_disagreement`).

Driven through the real producer and the real Step-4 gate; the Step-4 tree is
the review fixture (execution record planted in the shape `run_unit_tbs`
writes). chip-AGNOSTIC: synthetic options and cases.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


_spec = importlib.util.spec_from_file_location(
    "_fx_p2_review_fixture",
    Path(__file__).with_name(
        "test_fx_p2_review_input_gap_needs_positive_evidence.py"))
_FX = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_FX)

DECL = "plugin_output/declaration.json"
#: A conditional case, as Phase 1 emits it from "(if option M is chosen)".
COND = {"name": "opt_m_mul_div", "kind": "functional_vector",
        "stimulus": "(if option M is chosen) multiply/divide instructions",
        "expected": "PASS",
        "applies_when": {"option": "M", "stated": "(if option M is chosen)"}}

#: The input's own declaration contract. The design DESIGNATES its selection
#: with the producer's own grammar (`(primary)` on exactly one value).
_CONTRACT = """# L7

The Plugin MUST declare `{path}` before authoring:

| Field | Required | Example |
|---|---|---|
| `isa_extensions` | Yes | {values} |
"""


#: Asked through getattr, so a tree without the early emission ANSWERS (no
#: declaration exists before Step 4) instead of raising.




EXCLUDES_M = '`["I", "Zifencei"]`(primary)/ `["I", "M", "Zifencei"]`(secondary)'
SELECTS_M = '`["I", "M", "Zifencei"]`(primary)/ `["I", "Zifencei"]`(secondary)'
UNDESIGNATED = '`["I", "Zifencei"]` / `["I", "M", "Zifencei"]`'










def test_main_emits_before_step4_reads_it():
    """Wiring, read off the AST: the early emission precedes Step 4 in main,
    and row 33 is checked against it."""
    src = (_PROGRAMS / "design_one_shot_runner.py").read_text()
    main = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    lines = {}
    for n in ast.walk(main):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            lines.setdefault(n.func.id, []).append(n.lineno)
    assert "declaration_before_step4" in lines, sorted(lines)[:40]
    assert (min(lines["declaration_before_step4"])
            < min(lines["step_step4_functional_evidence"]))
    assert "_refuse_a_disagreeing_declaration" in lines


# ---- the agreement between the two emissions -------------------------------
#: A tree without the check leaves row 33 exactly as the producer returned it.













# #3112: neutral producer/currentness control, not extraction or AI approval.
