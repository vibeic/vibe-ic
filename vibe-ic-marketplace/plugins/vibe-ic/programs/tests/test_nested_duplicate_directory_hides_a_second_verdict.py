#!/usr/bin/env python3
"""A published cell must not nest a directory inside a same-named parent.

WHY THIS RULE, AND WHY IT IS NOT A STYLE PREFERENCE
====================================================
`u_hawaii_adc x sky130A` was WITHDRAWN from the published corpus on 2026-08-20
because one run wrote TWO completion audits: the one every consumer reads, at
`reports/audit/...`, saying PASS, and a second at `reports/reports/audit/...`
-- one directory too deep -- saying FAIL, written 3.5 s earlier. The public
matrix generator only reads the first, so the FAIL was invisible.

The corpus repository turned that into a rule for humans (`INDEX.md`, rule 3:
"Check for a nested `reports/reports/` before committing") and NOTHING in this
repository checks it: `grep -rn 'reports/reports' programs/ tools/` returns
nothing, and there is no general nested-duplicate detector either.

MEASURED, 2026-08-22, and this is what makes the rule an invariant rather than
today's coincidence:

  * Over the FULL historical published-cell corpus at the last commit that
    carried it -- 5 cells, 388 distinct directories -- there is exactly ONE
    same-name nesting, and it is `u_hawaii_adc/v1.9.86_sky130A/reports/reports`.
    One true positive, 387 clean directories, zero false positives.

  * Over the published corpus repository as it stands (`vibeic/benchmark-data`
    @ 3b58ccd42, 6929 blobs) there are THREE, none of them legitimate:
        protocol_parity/lpc/phase2/phase2          (12 files)
        protocol_parity/lpc/phase3/phase3          (28 files)
        protocol_parity/usb_pd/reports/phase3/phase3
    In the third, FOUR report names exist at BOTH depths and THREE of the four
    DIFFER in content -- including `foundry_handoff_audit.json`, which reads
    `"verdict": "SKIP"` with both required files missing at the depth consumers
    read, and `"verdict": "PASS"` with both present one directory deeper. Same
    cell, same report name, opposite answers. That is the withdrawal shape,
    still committed, in a different design.

AND IT IS WHY THE ROUTED-DEF HYGIENE CORPUS CAN STAY EMPTY WHILE FULL.
`tools/ci/routed_def_corpus.py` counts a path only at EXACTLY six components
below `ic/`, with `parts[2:] == ("phase3", "stage3", "pnr", "routed.def")`. A
cell published with `phase3/phase3/stage3/pnr/routed.def` is seven, so the
producer exits 0 having printed nothing -- byte-identical to an empty corpus --
and the blocking row keeps reporting `is EMPTY - nothing was checked over it`
while a routed DEF IS published. The producer is a protected authority file and
is right as written; the publish path is what must refuse a shape it cannot see.

chip-AGNOSTIC: synthetic folders, generic IC/PDK tokens, no design or PDK
literal is load-bearing.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "benchmark_evidence_structure_check.py")

_GOOD_MANIFEST = ("top.gds 1180456B sha256:"
                  + "2915355c69e0162887e4c3e3e60855a0710a8bccb0e02f1b08191989ef392c8f")
_RESULT_PASS = "# RESULT\n\n## VERDICT\n\n**PASS_WITH_WAIVERS.** re-derived.\n"

RULE = "NESTED_DUPLICATE"


def _run(args):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True)


def _conformant(base: Path, name: str = "v9.9.9_openpdkx") -> Path:
    """The canonical cell shape, with BOTH `reports/phase3` and `phase3/...`.

    Deliberately carries the two spellings a real cell carries, so a rule that
    fired on "the name `phase3` appears twice in one tree" would be caught by
    the negative control below rather than by a reviewer.
    """
    d = base / name
    (d / "phase1" / "generated_docs").mkdir(parents=True)
    (d / "phase1" / "generated_docs" / "L1.json").write_text("{}")
    (d / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (d / "phase2" / "stage1" / "rtl" / "top.v").write_text("module top; endmodule\n")
    (d / "reports" / "phase3").mkdir(parents=True)
    (d / "reports" / "phase3" / "drc.json").write_text("{}")
    (d / "reports" / "audit").mkdir(parents=True)
    (d / "reports" / "audit" / "phase23_completion_audit.json").write_text(
        json.dumps({"schema_version": 1, "verdict": "PASS_WITH_WAIVERS",
                    "registered_gate_count": 246, "passed_gate_count": 154,
                    "failed_gate_count": 0}))
    (d / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (d / "phase3" / "stage3" / "pnr" / "routed.def").write_text("VERSION 5.8 ;\nEND DESIGN\n")
    (d / "phase3" / "stage4" / "gds").mkdir(parents=True)
    (d / "phase3" / "stage4" / "gds" / "GDS_MANIFEST.txt").write_text(_GOOD_MANIFEST + "\n")
    (d / "RESULT.md").write_text(_RESULT_PASS)
    return d


# --------------------------------------------------------------------------
# NEGATIVE CONTROL FIRST. A rule that refuses the canonical shape is worse than
# no rule, and this fixture is the shape 387 of the 388 measured directories had.
# --------------------------------------------------------------------------

def test_the_canonical_cell_is_not_refused(tmp_path):
    d = _conformant(tmp_path)
    r = _run([str(d)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert RULE not in r.stdout, (
        "the canonical cell carries `phase3/` and `reports/phase3/` in one tree; "
        "a rule that reads that as a duplicate is matching the NAME instead of "
        "the NESTING\n" + r.stdout)


def test_the_rule_reports_a_verdict_on_a_clean_cell(tmp_path):
    """PASS must be a verdict this rule RENDERED, not one it never reached."""
    d = _conformant(tmp_path)
    out = tmp_path / "report.json"
    r = _run([str(d), "--json", str(out)])
    assert r.returncode == 0, r.stdout + r.stderr
    row = json.loads(out.read_text())["folders"][0]
    assert row["checks"].get(RULE) is True, (
        f"{RULE} rendered {row['checks'].get(RULE)!r} on a clean cell; a rule "
        "absent from `checks` has not passed, it was never asked\n"
        + out.read_text())


# --------------------------------------------------------------------------
# POSITIVE CONTROLS.
# --------------------------------------------------------------------------

def test_the_withdrawal_shape_is_refused(tmp_path):
    """`reports/reports/audit/` — the exact nesting a cell was withdrawn for."""
    d = _conformant(tmp_path)
    hidden = d / "reports" / "reports" / "audit"
    hidden.mkdir(parents=True)
    (hidden / "phase23_completion_audit.json").write_text(
        json.dumps({"schema_version": 1, "verdict": "FAIL",
                    "registered_gate_count": 246, "passed_gate_count": 3,
                    "failed_gate_count": 12}))
    r = _run([str(d)])
    assert r.returncode != 0, (
        "a cell carrying a second, contradictory audit one directory too deep "
        "was accepted\n" + r.stdout + r.stderr)
    assert RULE in r.stdout, r.stdout
    assert "reports/reports" in r.stdout, (
        "the finding must NAME the offending directory — a reader who cannot "
        "see which one it is cannot remove it\n" + r.stdout)


def test_the_shape_that_makes_the_routed_def_corpus_look_empty_is_refused(tmp_path):
    """`phase3/phase3/stage3/pnr/routed.def` — seven components, uncountable."""
    d = _conformant(tmp_path)
    deep = d / "phase3" / "phase3" / "stage3" / "pnr"
    deep.mkdir(parents=True)
    (deep / "routed.def").write_text("VERSION 5.8 ;\nEND DESIGN\n")
    r = _run([str(d)])
    assert r.returncode != 0, (
        "a cell whose routed DEF sits at a depth the hygiene producer cannot "
        "count was accepted; the corpus would report EMPTY over a published "
        "routed DEF\n" + r.stdout + r.stderr)
    assert RULE in r.stdout, r.stdout
    assert "phase3/phase3" in r.stdout, r.stdout


def test_every_offender_is_named_not_just_the_first(tmp_path):
    """The measured cell doubled TWO stages. Reporting one hides the other."""
    d = _conformant(tmp_path)
    for rel in ("phase2/phase2/rtl", "phase3/phase3/stage3"):
        (d / rel).mkdir(parents=True)
        (d / rel / "artefact.txt").write_text("x\n")
    r = _run([str(d)])
    assert r.returncode != 0, r.stdout + r.stderr
    assert "phase2/phase2" in r.stdout and "phase3/phase3" in r.stdout, (
        "one run tree in the published corpus doubles both its phase-2 and its "
        "phase-3 stage; a finding that names only the first leaves the second "
        "to be found by the next withdrawal\n" + r.stdout)


def test_the_finding_is_machine_readable(tmp_path):
    d = _conformant(tmp_path)
    (d / "reports" / "reports").mkdir(parents=True)
    (d / "reports" / "reports" / "drc.json").write_text("{}")
    out = tmp_path / "report.json"
    r = _run([str(d), "--json", str(out)])
    assert r.returncode != 0, r.stdout + r.stderr
    row = json.loads(out.read_text())["folders"][0]
    assert row["checks"].get(RULE) is False, out.read_text()
    assert any(f.startswith(RULE + ":") for f in row["failures"]), out.read_text()


def test_an_empty_nested_duplicate_still_counts(tmp_path):
    """The directory is the defect. Waiting for it to be filled is waiting for
    the second verdict to be written."""
    d = _conformant(tmp_path)
    (d / "reports" / "reports").mkdir(parents=True)
    r = _run([str(d)])
    assert r.returncode != 0, (
        "an empty `reports/reports/` is the same path bug one write away from "
        "the withdrawal\n" + r.stdout + r.stderr)
    assert RULE in r.stdout, r.stdout
