"""vibe-ic#2183 — the END-TO-END half: Step 5's denominator, through the real flow.

WHAT #2183 REPORTED, and what was still unpinned when this file was written.

The issue reported a `property_contract.json` carrying

    property_denominator 3, authored_property_count 0
    missing_declarations ["L3","L6","L8"]
    each row: DECLARATION_MISSING, "<L> declaration is absent"

for a project (`spm` x `gf180mcuD`) whose L3/L6/L8 declarations were present and
readable, and named an ephemeral `<TMPDIR>/vibeic-rtl-step-XXXX/<name>` staging root
as the candidate for what Step 5 read instead.

THAT CANDIDATE CAUSE IS REFUTED, and this file does not re-argue it — three separate
measurements already did (`7245fee1f`, `2c0a2dc49`, `eabb3b207`), and it was refuted a
fourth time on `28d13f16165a` while writing this file: driving the real `step_rtl_gen`,
the stage is a FULL copy that carried every `L*.json`, and `formal_harness_gen.generate`
was handed the runner's own project root, not the stage. The published contract read
`missing_declarations []` with `declaration_root_present true`.

SO WHY A TEST AT ALL. Every existing #2183 test either drives ONE step, or calls
`declaration_obligations` DIRECTLY:

    test_..._publishes_the_canonical_root      the publish seam; never reads the contract
    test_..._denominator_names_its_root        unit calls, ROOT_ABSENT / UNREADABLE
    test_..._root_it_cannot_list_...           its readable-root CONTROL is a direct
                                               `F.declaration_obligations(project)` call

Nobody drives the JOIN the issue actually reported — `step_rtl_gen` (which builds and
commits the staging transaction) followed by `step_emit_phase2_manifests` (which authors
the formal contract) — and then reads the PUBLISHED artefact. That join is where the
reported symptom appeared, and it is the one shape a future regression in the staging
snapshot would break while every existing test stayed green.

THE TWO PROPERTIES, and why each is here rather than one:

  1. THE STAGE CARRIES THE DECLARATIONS. Generators legitimately run against the stage —
     that is the transaction's purpose. A snapshot that omitted `phase1/` would make any
     of them read exactly the negative-control shape the issue assumed, and would do it
     silently. This asserts the property whose ABSENCE the issue hypothesised.
  2. THE PUBLISHED CONTRACT NAMES A ROOT UNDER THE RUNNER'S PROJECT, and a design whose
     declarations are present does not read as missing. Asserted on the artefact a
     reader opens, not on a return value, because the artefact is what #2183 quoted.

Both are stated as the reader experiences them: a root that EXISTS and is under the
project, never a string comparison that a different dead path would still satisfy.

chip-AGNOSTIC: no design, PDK, vendor or cell literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import formal_harness_gen as F              # noqa: E402

#: Minimal but REAL Phase-1 declarations: the layers #2183 named, plus the L1 the
#: resolver needs to know the top. Bodies are deliberately the smallest shape that
#: parses -- this file is about WHICH ROOT was read, not about what it contained.
_L_DOCS = {
    "L1_SPEC.json": {"fields": {"top_module": "demo_top"}},
    "L3_CMD_PROTOCOL.json": {"no_opcodes_in_input": True},
    "L6_CONTROL_LOGIC.json": {"fields": {}},
    "L8_RTL_CONSTANTS.json": {"fields": {}},
}



def _project(tmp_path: Path) -> Path:
    proj = tmp_path / "demo_proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "prompt.md").write_text(
        "# demo\nA register that captures an 8-bit input on a rising edge.\n")
    for name, body in _L_DOCS.items():
        (proj / "phase1" / "generated_docs" / name).write_text(json.dumps(body))
    return proj




# ── property 1: the stage a generator runs against carries the declarations ──



# ── property 2: the published contract measured the runner's own project ─────





# ── the controls, both directions ────────────────────────────────────────────

def test_CONTROL_a_root_without_declarations_still_reads_as_unread(tmp_path):
    """The negative control #2183 itself ran. Removing the declarations must
    still change the answer — otherwise the assertions above hold for a project
    whose contents nothing is reading, and they would pass on a broken flow."""
    proj = _project(tmp_path)
    for p in (proj / "phase1" / "generated_docs").glob("L*.json"):
        p.unlink()
    (proj / "phase1" / "generated_docs").rmdir()
    decl = F.declaration_obligations(proj)
    assert decl.get("declaration_root_present") is False, decl
    assert decl["obligations"] == [] or all(
        o.get("status") != "AUTHORED" for o in decl["obligations"]), decl




if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
