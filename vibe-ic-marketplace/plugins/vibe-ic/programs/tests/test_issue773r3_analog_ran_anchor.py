"""ORGANIC #773 r3 — the A/M-track waiver was gated on the FLAG, not the fact.

WHAT WAS BROKEN, MEASURED ON A REAL RUN
=======================================
#773 relieved a `kind=verification_intent` L10 case of the digital-TB
evidence requirement — correctly, because by this gate's own words such a case
is one "a digital testbench can NEVER carry an id-substring trace for, and
which the A/M track satisfies". But it made the relief conditional on
`--skip-analog`:

    waiver_active = bool(skip_analog) and bool(analog_anchor)

So a run that DEFERRED the analog work was credited, and a run that actually
DID it — nine real ngspice PVT corners per block, bound to the staged foundry
corner sections — was FAILED, for lacking evidence in a directory that cannot
hold it. Doing the work scored strictly worse than not doing it, and the
resulting Step-4 FAIL was what stopped the design entering Phase 3.

Neither the case's KIND nor the owner of its oracle changes with that flag.
Only the reviewable ANCHOR changes: the skip declaration when the track was
deferred, the track's own evidence when it ran. `analog_ran_anchor` resolves
the second, and `waiver_active` is now anchor-gated rather than flag-gated.

WHAT THIS IS NOT
================
It is NOT a claim that the analog result was good, and it does not upgrade any
analog verdict. The A/M track keeps its own gates and its own place in the
audit — on the run this came from, the analog stage was FAILING before this
change and is still FAILING after it. All this stops is a DIGITAL testbench
gate charging a second, duplicate failure for a measurement it cannot make in
either direction.

BLOCKING vs ADVISORY
====================
The gate stays BLOCKING and the tests assert the rc: rc 1 when a case that
needs digital evidence lacks it, rc 3 (PASS_WITH_WAIVERS) only for an
anchored, kind-scoped A/M case. Every #773 no-leak property is re-asserted
here against the NEW anchor, because a relaxation is only as good as the
leaks it still refuses.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "l10_tb_conformance_check.py"
sys.path.insert(0, str(SCRIPT.parent))
import l10_tb_conformance_check as gate  # noqa: E402

INTENT = {"name": "am_intent_row", "kind": "verification_intent",
          "stimulus": "corner sweep over the declared process/temperature set",
          "expected": "verification intent satisfied"}
DIGITAL = {"name": "digital_row", "kind": "cmd_response", "opcode": "0x11",
           "stimulus": "issue the command", "expected": "response checked"}


def _project(tmp_path, cases, *, analog=None, tag="p"):
    """A project tree. `analog` is a {block: [corner-record, ...]} map written
    to phase3/analog/<block>/corner_results.json — the artefact the A/M track
    leaves behind when it actually ran."""
    root = tmp_path / tag
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L10_TEST_CASES.json").write_text(json.dumps({"test_cases": cases}))
    tb = root / "phase2" / "stage1" / "sim" / "tb"
    tb.mkdir(parents=True)
    (tb / "tb_dummy.v").write_text("module tb_dummy;\nendmodule\n")
    for block, corners in (analog or {}).items():
        bd = root / "phase3" / "analog" / block
        bd.mkdir(parents=True)
        (bd / "corner_results.json").write_text(
            json.dumps({"corners": corners}))
    return root


def _real_corners(n=9):
    return [{"name": "c%d" % i, "simulator_run": True,
             "_provenance": "real_ngspice", "vout_v": 1.19}
            for i in range(n)]


class _R:
    """rc plus the combined transcript — this gate reports on stdout, and a
    test that only reads stderr would pass for the wrong reason."""
    def __init__(self, cp):
        self.returncode = cp.returncode
        self.out = (cp.stdout or "") + (cp.stderr or "")


def _run(root, *extra):
    return _R(subprocess.run(
        [sys.executable, str(SCRIPT),
         "--l10", str(root / "phase1/generated_docs/L10_TEST_CASES.json"),
         "--tb-dir", str(root / "phase2/stage1/sim/tb"), *extra],
        capture_output=True, text=True))


# ── the subject ───────────────────────────────────────────────────────────
def test_an_am_case_is_credited_when_the_analog_track_actually_ran(tmp_path):
    """THE SUBJECT. RED before r3: rc 1, because `--skip-analog` was absent."""
    root = _project(tmp_path, [INTENT], analog={"blk": _real_corners()})
    res = _run(root)
    assert res.returncode == 3, (res.returncode, res.out)
    assert "PASS_WITH_WAIVERS" in res.out
    assert "A/M track RAN" in res.out, res.out


def test_the_credit_names_the_evidence_it_stands_on(tmp_path):
    """An anchor a reader cannot follow is not reviewable. It must name the
    blocks and the count of simulator-produced records."""
    root = _project(tmp_path, [INTENT],
                    analog={"blk_a": _real_corners(9),
                            "blk_b": _real_corners(9)})
    out = tmp_path / "o.json"
    res = _run(root, "--out", str(out))
    assert res.returncode == 3
    rec = json.loads(out.read_text())
    anchor = rec["analog_anchor"]
    assert "blk_a" in anchor and "blk_b" in anchor, anchor
    assert "18" in anchor, anchor
    assert rec["waived"] == 1 and rec["fail"] == 0, rec


def test_the_deferred_path_is_untouched(tmp_path):
    """#773's original behaviour must survive byte-for-byte in its own case."""
    root = _project(tmp_path, [INTENT])
    sim = root / "phase2/stage1/sim"
    (sim / "results.xml").write_text(
        "<r><verdict>CONNECTIVITY_PASS</verdict>"
        "<capability_gap>cap:cpu_functional_oracle</capability_gap></r>")
    out = tmp_path / "deferred.json"
    res = _run(root, "--skip-analog", "--out", str(out))
    assert res.returncode == 3, (res.returncode, res.out)
    rec = json.loads(out.read_text())
    assert rec["waived"] == 1 and rec["fail"] == 0, rec
    ev = " ".join(rec["results"][0]["evidence"])
    assert "--skip-analog" in ev, ev
    assert "results.xml" in rec["analog_anchor"], rec["analog_anchor"]


# ── the controls: every leak the relaxation must still refuse ─────────────
def test_noleak_an_unrun_unskipped_analog_track_anchors_nothing(tmp_path):
    """THE PRIMARY CONTROL. A project with no analog evidence and no
    --skip-analog resolves NO anchor and FAILs exactly as it does today. This
    is the property that keeps the change from being a blanket relaxation."""
    root = _project(tmp_path, [INTENT])
    res = _run(root)
    assert res.returncode == 1, (res.returncode, res.out)


def test_noleak_a_corner_file_no_simulator_produced_is_not_evidence(tmp_path):
    """A corner record with no simulator marker is a FILE, not a measurement.
    Writing one must not buy the credit — otherwise the anchor is forgeable
    with a text editor."""
    fake = [{"name": "c0", "vout_v": 1.2}]          # no simulator_run marker
    root = _project(tmp_path, [INTENT], analog={"blk": fake})
    res = _run(root)
    assert res.returncode == 1, (res.returncode, res.out)


def test_noleak_an_empty_corner_list_is_not_evidence(tmp_path):
    root = _project(tmp_path, [INTENT], analog={"blk": []})
    assert _run(root).returncode == 1


def test_noleak_a_digital_case_still_fails_when_analog_ran(tmp_path):
    """§4.05 kind-scoping, re-asserted against the NEW anchor: a real analog
    track must not buy a missing digital testbench."""
    root = _project(tmp_path, [DIGITAL], analog={"blk": _real_corners()})
    res = _run(root)
    assert res.returncode == 1, (res.returncode, res.out)


def test_noleak_a_digital_case_beside_an_am_case_still_fails(tmp_path):
    """The mixed list is the case that matters: the A/M row may be credited
    and the digital row must still sink the run."""
    root = _project(tmp_path, [INTENT, DIGITAL],
                    analog={"blk": _real_corners()})
    out = tmp_path / "o.json"
    res = _run(root, "--out", str(out))
    assert res.returncode == 1, (res.returncode, res.out)
    rec = json.loads(out.read_text())
    assert rec["waived"] == 1 and rec["not_executed"] == 1, rec
    assert rec["fail"] == 0, rec


def test_noleak_a_mislabelled_digital_case_is_not_credited(tmp_path):
    """#773 r2's guard, re-asserted: a case carrying a digital signal (an
    opcode) does not escape by also wearing a verification_intent kind."""
    smuggled = dict(DIGITAL, kind="verification_intent")
    root = _project(tmp_path, [smuggled], analog={"blk": _real_corners()})
    assert _run(root).returncode == 1


def test_the_anchor_resolver_is_not_vacuous(tmp_path):
    """The resolver must return None on a tree with no analog at all — if it
    returned a truthy string unconditionally every test above would pass for
    the wrong reason."""
    root = _project(tmp_path, [INTENT])
    assert gate.analog_ran_anchor(str(root)) is None
    assert gate.analog_ran_anchor(None) is None
    root2 = _project(tmp_path, [INTENT], analog={"b": _real_corners()},
                     tag="q")
    assert gate.analog_ran_anchor(str(root2))
