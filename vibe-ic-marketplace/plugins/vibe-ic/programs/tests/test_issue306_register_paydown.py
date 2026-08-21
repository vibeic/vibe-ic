#!/usr/bin/env python3
"""vibe-ic#306 — paying down the enforcement register, not just recording it.

`flow_gate_enforcement_audit` keeps a SHRINK-ONLY register of gates that
DECLARE an intent they are not wired for. It held four:

    contradiction::gds_substance_check                    (in flow, audit-only)
    orphan::drv_promotion_corroboration_check             (in no flow step)
    orphan::l16_compliance_properties_actionable_check    (another concern)
    orphan::l17_channel_catalog_consumer_contract_check   (another concern)

This change pays the FIRST TWO. The l16/l17 pair is owned by a separate change
that corrects their DECLARATION (BLOCKS -> ADVISES) rather than their wiring,
so nothing here asserts anything about their register entries beyond "not
mine" — the assertions below are written to survive that landing in either
order.

Each of the two was DECIDED on its merits, and the deciding fact is the BLAST
RADIUS measured over the 15 published run-roots under `benchmark-data/ic`
BEFORE wiring anything:

    gds_substance_check                 blocks 0/15 -> wired ENFORCED
    drv_promotion_corroboration_check   blocks 0/15 -> wired ENFORCED

A blast radius of 0 is only meaningful beside evidence the gate can fire at
all — "zero false positives" is vacuous in a gate that never runs. Both are
therefore two-sided controlled here: `test_306_gds_substance_gate_blocks_*`
and `test_306_drv_promotion_step_blocks_*` drive each one to a real FAIL
through the wiring that now carries it.

THE MUTATION CONTROL is `test_306_mutation_control_*`: it strips the two
invocations this change added from COPIES of the runner source and proves both
gates fall straight back into the register. Without it, the "ENFORCED"
assertions below would pass against any tree that merely happened to name
these gates somewhere.
"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_BASELINE = _PROGRAMS / "flow_gate_enforcement_baseline.json"

sys.path.insert(0, str(_PROGRAMS))
import flow_gate_enforcement_audit as AUDIT  # noqa: E402

# The two entries THIS change pays down. Both live in phase3_one_shot_runner.
_PAID = (
    "gds_substance_check",
    "drv_promotion_corroboration_check",
)
_RUNNER = "phase3_one_shot_runner.py"


def _audit():
    return AUDIT.audit(_FLOW, _PROGRAMS)


def _row(rep, gate):
    for r in rep["gates"]:
        if r["gate"] in (gate, f"{gate}.py"):
            return r
    return None


# ---------------------------------------------------------------------------
# The register itself
# ---------------------------------------------------------------------------
def test_306_register_never_grows():
    bl = json.loads(_BASELINE.read_text())
    prev = bl.get("previous_size")
    assert prev is None or len(bl["known"]) <= prev, (
        f"the register grew {prev} -> {len(bl['known'])}; it records debt to "
        f"be paid down, never permission to add more")


@pytest.mark.parametrize("gate", _PAID)
def test_306_paid_gates_left_the_register(gate):
    known = set(json.loads(_BASELINE.read_text())["known"])
    assert f"contradiction::{gate}" not in known
    assert f"orphan::{gate}" not in known


def test_306_shipped_tree_is_green_against_its_register():
    """An audit that ships red blocks nothing — the failure mode it names."""
    r = subprocess.run([sys.executable,
                        str(_PROGRAMS / "flow_gate_enforcement_audit.py")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("gate", _PAID)
def test_306_paid_gates_are_enforced_not_merely_declared(gate):
    """ENFORCED means a runner invokes it inline, so it can stop the step it
    guards. Being present in the flow YAML is NOT that: the YAML gates are
    evaluated by `flow_compliance_check`, which the runners call as the LAST
    step — after every artefact already exists."""
    rep = _audit()
    row = _row(rep, gate)
    assert row is not None, f"{gate} is not in the flow definition at all"
    assert row["enforcement"] == "ENFORCED", row
    assert row["declared"] == "blocking", row
    assert not any(c["gate"].startswith(gate) for c in rep["contradictions"])
    assert not any(o["gate"].startswith(gate) for o in rep["orphaned"])


def test_306_drv_blast_radius_is_stated_where_the_wiring_is():
    """A gate wired blocking needs its measured blast radius written beside
    the wiring, not rediscovered when main turns red."""
    prose = " ".join(_FLOW.read_text(errors="replace").replace("#", " ").split())
    assert "drv_promotion_corroboration_check" in prose
    assert "15 published run-roots" in prose and "it blocks 0" in prose, (
        "the measurement that justified the blocking slot is not recorded")


# ---------------------------------------------------------------------------
# MUTATION CONTROL — the assertions above must be caused by the wiring
# ---------------------------------------------------------------------------
def _mutated_programs(tmp_path: Path) -> Path:
    """A programs dir whose runner no longer INVOKES the two gates.

    Reproduces the pre-fix tree: the gate files and the flow YAML are
    untouched, only the runner-side invocation is gone.
    """
    d = tmp_path / "programs"
    d.mkdir()
    text = (_PROGRAMS / _RUNNER).read_text(errors="replace")
    mutations = 0
    for gate in _PAID:
        token = f"{gate}.py"
        mutations += text.count(token)
        text = text.replace(token, "__mutated_away__.py")
    assert mutations == 2, (
        f"expected exactly 2 invocation sites to strip, stripped {mutations}: "
        "a control that mutates nothing proves nothing")
    (d / _RUNNER).write_text(text)
    for gate in _PAID:
        (d / f"{gate}.py").write_text(
            (_PROGRAMS / f"{gate}.py").read_text(errors="replace"))
    return d


def test_306_mutation_control_removing_the_wiring_restores_the_debt(tmp_path):
    """Strip the invocations -> both fall straight back into the register.

    This is what makes the ENFORCED assertions above load-bearing rather than
    a restatement of the tree's current text.
    """
    rep = AUDIT.audit(_FLOW, _mutated_programs(tmp_path))
    back = {c["gate"] for c in rep["contradictions"]} | \
           {o["gate"] for o in rep["orphaned"]}
    for gate in _PAID:
        assert gate in back, (
            f"{gate} stayed clean with its invocation removed — the audit is "
            f"not measuring the wiring")


def test_306_mutation_control_the_unmutated_tree_is_clean(tmp_path):
    """The other side of the control: same harness, real source, no debt for
    either gate. A one-sided control cannot tell a working audit from a stuck
    one."""
    d = tmp_path / "programs"
    d.mkdir()
    for f in (_RUNNER,) + tuple(f"{g}.py" for g in _PAID):
        (d / f).write_text((_PROGRAMS / f).read_text(errors="replace"))
    rep = AUDIT.audit(_FLOW, d)
    back = {c["gate"] for c in rep["contradictions"]} | \
           {o["gate"] for o in rep["orphaned"]}
    for gate in _PAID:
        assert gate not in back, rep


# ---------------------------------------------------------------------------
# The wiring must BEHAVE, not merely be detectable by the audit.
# Each gate is driven to a REAL FAIL through the wiring that now carries it —
# a blast radius of 0 means nothing beside a gate that cannot fire.
# ---------------------------------------------------------------------------
def _rec(rt: int, payload: bytes = b"") -> bytes:
    return struct.pack(">HH", 4 + len(payload), rt) + payload


_TS = struct.pack(">12h", 2026, 7, 25, 12, 0, 0, 2026, 7, 25, 12, 0, 0)


def _lib_prologue(libname: bytes = b"chip\x00\x00") -> bytes:
    return (_rec(0x0002, struct.pack(">h", 600))
            + _rec(0x0102, _TS)
            + _rec(0x0206, libname)
            + _rec(0x0305, b"\x00" * 16))


def _real_gds(n_cells: int = 10, n_boundaries: int = 40) -> bytes:
    out = _lib_prologue()
    for i in range(n_cells):
        name = f"cell_{i}".encode()
        if len(name) % 2:
            name += b"\x00"
        out += _rec(0x0502, _TS) + _rec(0x0606, name)
        for j in range(n_boundaries):
            out += (_rec(0x0800)
                    + _rec(0x0D02, struct.pack(">h", (j % 5) + 1))
                    + _rec(0x0E02, struct.pack(">h", 0))
                    + _rec(0x1003, struct.pack(">8i", 0, 0, 100, 0,
                                               100, 100, 0, 100))
                    + _rec(0x1100))
        out += _rec(0x0700)
    return out + _rec(0x0400)


def _empty_library_gds(kb: int = 150) -> bytes:
    """Structurally valid GDSII, ZERO structures, padded to look big. This is
    the artefact class that used to sign off clean."""
    body = _lib_prologue() + _rec(0x0400)
    return body + b"\x00" * (kb * 1024 - len(body))


def _gds_project(tmp_path: Path, blob: bytes, instances: int = 100):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "chip.gds").write_bytes(blob)
    (pnr / "chip.def").write_text(
        f"VERSION 5.8 ;\nDESIGN chip ;\nCOMPONENTS {instances} ;\n"
        "END COMPONENTS\nEND DESIGN\n")
    return pnr / "chip.gds", pnr / "chip.def"


def test_306_gds_substance_gate_passes_a_real_streamout(tmp_path):
    import phase3_one_shot_runner as R
    gds, df = _gds_project(tmp_path, _real_gds(), instances=100)
    assert R._gds_substance_gate(gds, df) is None


def test_306_gds_substance_gate_blocks_a_substance_less_streamout(tmp_path):
    """The negative control the #306 defect is about: a 150 KB structurally
    valid GDSII with no layout in it. The gate FAILed on exactly this class of
    file before, and the flow ran to completion anyway."""
    import phase3_one_shot_runner as R
    gds, df = _gds_project(tmp_path, _empty_library_gds(), instances=100)
    msg = R._gds_substance_gate(gds, df)
    assert msg, "a GDS with zero structures was let through"
    assert "FAIL" in msg or "NO_" in msg or "substance" in msg.lower(), msg


def test_306_gds_substance_gate_is_wired_at_both_streamout_engines(tmp_path):
    """Magic and KLayout are independent stream-out paths with independent
    PASS returns. Gating one would leave the other open."""
    src = (_PROGRAMS / _RUNNER).read_text(errors="replace")
    assert src.count("_gds_substance_gate(gds_out, def_file)") == 2, (
        "expected the substance gate at both stream-out exits")
    assert "streamout=magic" in src and "streamout=klayout" in src


def test_306_drv_promotion_step_passes_when_nothing_was_promoted(tmp_path):
    import phase3_one_shot_runner as R
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    r = R.step_drv_promotion_corroboration(tmp_path)
    assert r.status == "PASS", r
    assert (tmp_path / "reports" / "phase3" / "sta"
            / "drv_promotion_corroboration.json").is_file()


def test_306_drv_promotion_step_blocks_an_uncorroborated_promotion(tmp_path):
    """A promotion with NO sign-off report to corroborate it is exactly the
    failure mode: the route was swapped on its own in-session numbers.

    This is also the evidence that the gate CAN fire. It has returned no
    finding on the published corpus — but that is because no published run
    promoted a route (0 of 15 carry `routed_base_prerepair.def`), not because
    the gate is inert. The promoting step (`step_signoff_spef_repair`) is live
    in the runner chain, so the trigger is reachable, and it fired once in the
    field (#293) — which is why the gate exists.
    """
    import phase3_one_shot_runner as R
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed_base_prerepair.def").write_text("DESIGN x ;\n")
    (pnr / "signoff_spef_repair.log").write_text(
        "Found 330 slew violations.\nFound 178 slew violations.\n")
    r = R.step_drv_promotion_corroboration(tmp_path)
    assert r.status == "FAIL", r


def test_306_drv_promotion_trigger_is_reachable_not_dead_code():
    """The measurement behind the paragraph above: the step that writes the
    promotion marker is still CALLED by the runner. A gate guarding a code
    path that cannot execute would be wiring for its own sake."""
    src = (_PROGRAMS / _RUNNER).read_text(errors="replace")
    assert "_sr = step_signoff_spef_repair(" in src, (
        "the promoting step is no longer invoked — re-assess whether this "
        "gate still guards anything")
    assert 'routed_base_prerepair.def"' in src, (
        "the promotion marker this gate keys on is no longer written")


def test_306_drv_promotion_step_does_not_fail_on_a_checker_fault(tmp_path):
    """rc=2 is inconclusive, not a verdict about the design. A blocking gate
    that fails runs over its own I/O errors is breakage, not enforcement.

    #544 SPLIT THE ORIGINAL ASSERTION, which was `status in ("PASS", "SKIP")`
    and passed on the WRONG member of that pair. Measured on the pre-fix tree,
    a non-existent project returned `PASS  verdict: VACUOUS_PASS  no route
    promotion this run — gate inapplicable`, because this step created
    `reports/phase3/sta/` unconditionally and so FABRICATED the project
    directory it was asked to audit; the checker then found an empty-but-real
    tree and reported "nothing was promoted". A green verdict about a project
    that is not there.

    What survives is the real half — a checker fault is not a design FAIL. What
    replaces the rest is that it is not a pass either.
    """
    import phase3_one_shot_runner as R
    missing = tmp_path / "does_not_exist"
    r = R.step_drv_promotion_corroboration(missing)
    assert r.status != "FAIL", (
        "a checker fault is not a verdict about the design", r)
    assert r.status == "BLOCKED", r
    assert not missing.exists(), (
        "the step created the project directory it was asked to audit")
