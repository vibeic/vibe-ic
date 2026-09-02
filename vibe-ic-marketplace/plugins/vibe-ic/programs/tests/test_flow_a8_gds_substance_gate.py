"""A8's gate of record must reject a hardmacro GDS that carries no layout.

The defect
----------
`analog_hardmacro_check.py`'s only GDS predicate was
`not gds.exists() or gds.stat().st_size == 0`, while its LEF / LIB / V branches
right below it all read and pattern-match CONTENT. Measured on
phase3/analog/hardmacro/blk1/ with `blk1.gds` = 500 bytes of non-GDS noise plus
a syntactically valid LEF/LIB/V:

    analog_hardmacro_check          -> [PASS], rc=0 (HARDMACRO_COMPLETE)
    analog_a8_hardmacro_gen_check   -> never inspects the .gds at all
    analog_artefact_substance_check -> a 200-byte size floor, defeated by padding
    analog_a5_layout_check          -> 0 geometry records, REJECTS the same bytes

and the one gate that got it right —
`programs/analog_lef_gds_outline_check.py`, which returns rc=1
`A8_GDS_NO_GEOMETRY` on exactly that artefact — appeared in NO flow yaml gate
and in NO flow_compliance_check gate list. It was referenced only by
skills/analog-output-verify/SKILL.md, programs/INDEX.md and its own unit test.
The correct check was written and unwired.

The fix
-------
1. `analog_hardmacro_check` uses the record walk A5 already uses
   (`_gds_geometry_count`: BOUNDARY / PATH / SREF / AREF / BOX), placed AFTER
   the deterministic-stub short-circuit.
2. A8's flow gate becomes an all_of that also runs
   `analog_lef_gds_outline_check`.
3. `analog_lef_gds_outline_check` learns the deterministic-stub tier so wiring
   it does not contradict `HARDMACRO_STUB_ACCEPTED` / PASS_WITH_STUB.

Digital-run note: this defect is on the ANALOG track. The completed
spm x ihp-sg13g2 run is pure digital and ships no
`phase1/analog/analog_block_list.json`, so A8 is SKIPPED-CONDITION there and
these gates are VACUOUS_PASS — verified by `test_guard_*_vacuous_pass_*`
below. Everything here is therefore verified by code + fixtures, not by
artefacts from that run.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_PLUGIN = _PROGRAMS.parent
for _p in (str(_PROGRAMS), str(_PLUGIN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
HARDMACRO = _PROGRAMS / "analog_hardmacro_check.py"
OUTLINE = _PROGRAMS / "analog_lef_gds_outline_check.py"

_STUB_MARKER = "// deterministic_stub extraction_strategy=deterministic_stub\n"


# ── fixtures ────────────────────────────────────────────────────────────────

def _rec(rec_type: int, payload: bytes = b"") -> bytes:
    return struct.pack(">HH", 4 + len(payload), rec_type) + payload


def _real_gds(w_um: float, h_um: float, dbu_per_um: int = 1000) -> bytes:
    import analog_lef_gds_outline_check as _mod
    out = _rec(0x0002, struct.pack(">h", 600))
    out += _rec(0x0102, struct.pack(">12h", *([0] * 12)))
    out += _rec(0x0206, b"TOP\x00")
    out += _rec(0x0305, _mod.encode_gds_real8(1.0 / dbu_per_um)
                + _mod.encode_gds_real8(1e-6 / dbu_per_um))
    out += _rec(0x0502, struct.pack(">12h", *([0] * 12)))
    out += _rec(0x0606, b"TOP\x00")
    out += _rec(0x0800)
    out += _rec(0x0D02, struct.pack(">h", 1))
    out += _rec(0x0E02, struct.pack(">h", 0))
    w, h = int(w_um * dbu_per_um), int(h_um * dbu_per_um)
    pts = [(0, 0), (w, 0), (w, h), (0, h), (0, 0)]
    out += _rec(0x1003, b"".join(struct.pack(">ii", x, y) for x, y in pts))
    out += _rec(0x1100) + _rec(0x0700) + _rec(0x0400)
    return out


def _noise(n: int = 500) -> bytes:
    state, buf = 12345, bytearray()
    for _ in range(n):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        buf.append((state >> 16) & 0xFF)
    return bytes(buf)


def _project(tmp_path: Path, block: str = "blk1", *, gds: bytes = None,
             lef_w: float = 100.0, lef_h: float = 100.0,
             stub: bool = False, declare: bool = True) -> Path:
    project = tmp_path / "proj"
    hm = project / "phase3" / "analog" / "hardmacro" / block
    hm.mkdir(parents=True)
    # The corner artefact carrying the record of what circuit this package
    # models. `analog_hardmacro_check` — the gate the FLOW declares for A8 —
    # stopped signing off a macro digital PnR will instantiate and
    # integration STA will close on when nothing on the tree names its
    # subject. These fixtures are about GDS SUBSTANCE and LEF/GDS OUTLINE, so
    # each needs a package that clears every other rule; without this record
    # the direction-1 guard below would fail on content instead, and a guard
    # that fails for the wrong reason guards nothing.
    ad = project / "phase3" / "analog" / block
    ad.mkdir(parents=True, exist_ok=True)
    (ad / "corner_results.json").write_text(json.dumps({
        "block": block, "_provenance": "real_ngspice",
        "corners": [{"name": "tt_27c_1v8", "simulator_run": True}],
        "design_content": "structure_and_geometry"}))
    if declare:
        for rel in ("phase3/analog/analog_block_list.json",
                    "phase1/analog/analog_block_list.json"):
            p = project / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"blocks": [block]}))
    marker = _STUB_MARKER if stub else ""
    (hm / f"{block}.lef").write_text(
        marker + "VERSION 5.8 ;\n"
        f"MACRO {block}\n  CLASS BLOCK ;\n"
        f"  SIZE {lef_w} BY {lef_h} ;\n"
        "  PIN VDD\n    DIRECTION INOUT ;\n  END VDD\n"
        f"END {block}\nEND LIBRARY\n")
    (hm / f"{block}.lib").write_text(
        marker + f'library ({block}) {{\n  cell ({block}) {{ area : 1; }}\n}}\n')
    (hm / f"{block}.v").write_text(
        marker + f"module {block} (inout VDD, inout VSS);\nendmodule\n")
    if gds is not None:
        (hm / f"{block}.gds").write_bytes(gds)
    return project


def _run(prog: Path, project: Path, *extra):
    return _pr.run([sys.executable, str(prog), str(project), *extra],
                          capture_output=True, text=True)


# ── the wiring (a declaration is not an implementation) ─────────────────────

def _a8_gate_commands() -> list:
    doc = yaml.safe_load(FLOW.read_text())
    for st in doc.get("steps", []):
        if str(st.get("id")) != "A8":
            continue
        gate = st.get("gate") or {}
        if "all_of" in gate:
            return [m["program_exit_zero"] for m in gate["all_of"]
                    if isinstance(m, dict) and "program_exit_zero" in m]
        if "program_exit_zero" in gate:
            return [gate["program_exit_zero"]]
        return []
    raise AssertionError("premise: step A8 not found in the flow yaml")


def test_a8_gate_runs_the_hardmacro_check():
    cmds = _a8_gate_commands()
    assert any(c.startswith("analog_hardmacro_check") for c in cmds), cmds


def test_a8_gate_runs_the_lef_gds_outline_check():
    """The check existed, was tested, and was wired NOWHERE. Pin the wiring."""
    cmds = _a8_gate_commands()
    assert any(c.startswith("analog_lef_gds_outline_check") for c in cmds), (
        f"A8 must run analog_lef_gds_outline_check; gate commands: {cmds}")


def test_outline_gate_is_blocking_not_advisory():
    doc = yaml.safe_load(FLOW.read_text())
    step = next(s for s in doc["steps"] if str(s.get("id")) == "A8")
    members = step["gate"]["all_of"]
    outline = [m for m in members
               if str(m.get("program_exit_zero", "")).startswith(
                   "analog_lef_gds_outline_check")]
    assert outline, members
    assert "advisory_program_exit_zero" not in outline[0], (
        "the outline check must BLOCK A8; an advisory slot cannot fail a step")


# ── behavioural discriminators ─────────────────────────────────────────────

def test_hardmacro_check_rejects_a_padded_garbage_gds(tmp_path):
    """THE measurement: 500 bytes of noise + valid LEF/LIB/V used to be
    `[PASS] analog_hardmacro_check`, rc=0."""
    project = _project(tmp_path, gds=_noise())
    cp = _run(HARDMACRO, project)
    assert cp.returncode == 1, cp.stdout
    assert "HARDMACRO_GDS_NO_GEOMETRY" in cp.stdout, cp.stdout


def test_outline_check_rejects_the_same_artefact(tmp_path):
    project = _project(tmp_path, gds=_noise())
    cp = _run(OUTLINE, project)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "A8_GDS_NO_GEOMETRY" in (cp.stdout + cp.stderr)


def _members_that_read_the_gds(tmp_path) -> list:
    """The A8 members whose verdict DEPENDS ON THE GDS BYTES, derived by
    running each one twice over projects that differ in nothing else.

    THE POPULATION IS BEHAVIOURAL ON PURPOSE, and the test this replaces is why.
    It asserted that EVERY member of A8's `all_of` refuses a noise `.gds`, which
    was true when A8 had two members and both were GDS-substance checks. A8 has
    since grown to four, and the two new ones measure other properties —
    MEASURED on a noise fixture: `analog_macro_rtl_interface_check` rc 2
    (VACUOUS: nothing could be compared) and `analog_topology_behaviour_check`
    rc 0 (PASS: no block states a behavioural claim). Neither is a defect; both
    are correct answers to questions that are not about GDS substance.

    A HAND-WRITTEN NAME LIST WOULD BE THE SAME MISTAKE ONE VERSION LATER: it is
    blind to the next member, which is exactly how the assertion above expired.
    So membership is decided by what a member READS — flip the GDS bytes,
    holding everything else identical, and keep the members whose verdict
    moves. A member that answers the same thing to a real macro and to 500
    bytes of noise is not reading the GDS, whatever it is called."""
    real = _project(tmp_path / "real", gds=_real_gds(100.0, 100.0))
    noise = _project(tmp_path / "noise", gds=_noise())
    out = []
    for cmd in _a8_gate_commands():
        prog = _PROGRAMS / f"{cmd.split()[0]}.py"
        if _run(prog, real).returncode != _run(prog, noise).returncode:
            out.append(prog)
    return out


def test_a8_all_of_fails_when_a_gds_substance_member_fails(tmp_path):
    """Every member whose subject IS the GDS refuses 500 bytes of noise, and
    `all_of` makes any one of them enough to fail the step.

    TWO CLAIMS, AND NEITHER IS `any(...)`. Weakening to "at least one member
    refuses" would pass even if BOTH GDS members had degraded to rc 0, because
    a non-GDS member returning rc 2 would carry it. So the population is
    identified first, by behaviour, and then EVERY member of it must refuse."""
    members = _members_that_read_the_gds(tmp_path)
    # A FLOOR, BECAUSE THE POPULATION IS THE THING A DEGRADED MEMBER LEAVES.
    # A member that stopped reading the GDS — say it degraded to rc 0 on every
    # input — would simply drop OUT of the behavioural population above, and
    # "every remaining member refuses noise" would still be true. Measured on
    # this tree, two members' verdicts move with the GDS bytes
    # (`analog_hardmacro_check`, `analog_lef_gds_outline_check`), so two is the
    # floor. It is a COUNT derived from behaviour, not a list of names: adding
    # a GDS-reading member raises it, and one going blind drops below it and
    # reddens here rather than quietly narrowing what A8 checks.
    assert len(members) >= 2, (
        f"only {[p.name for p in members]} still answer differently to a real "
        f"macro and to 500 bytes of noise; A8 had two such members and a "
        f"member that stopped reading the GDS leaves this population instead "
        f"of failing in it")
    project = _project(tmp_path / "subject", gds=_noise())
    rcs = {p.name: _run(p, project).returncode for p in members}
    assert all(rc != 0 for rc in rcs.values()), rcs


def test_the_all_of_conjunction_is_what_makes_one_member_enough(tmp_path):
    """The second half, stated separately because it is a different claim: A8
    is declared `all_of`, so a single refusing member fails the step. Read from
    the flow definition rather than assumed from the word in the test name."""
    doc = yaml.safe_load(FLOW.read_text())
    step = next(st for st in doc.get("steps", []) if str(st.get("id")) == "A8")
    gate = step.get("gate") or {}
    assert "all_of" in gate, sorted(gate)
    assert "any_of" not in gate, sorted(gate)
    assert len(gate["all_of"]) >= len(_a8_gate_commands()) >= 2, gate["all_of"]


def test_outline_check_catches_a_lying_lef_outline(tmp_path):
    """The SECOND, separate class of newly-red that wiring buys: a REAL GDS
    paired with a LEF whose SIZE does not describe it. Called out explicitly
    because it was never measured before."""
    project = _project(tmp_path, gds=_real_gds(250.0, 80.0),
                       lef_w=100.0, lef_h=100.0)
    cp = _run(OUTLINE, project)
    assert cp.returncode == 1, cp.stdout
    assert "A8_LEF_GDS_OUTLINE_MISMATCH" in (cp.stdout + cp.stderr)


# ── direction-1 guards ─────────────────────────────────────────────────────

def test_guard_real_gds_matching_lef_passes_both_gates(tmp_path):
    project = _project(tmp_path, gds=_real_gds(100.0, 100.0))
    for prog in (HARDMACRO, OUTLINE):
        cp = _run(prog, project)
        assert cp.returncode == 0, f"{prog.name}: {cp.stdout}{cp.stderr}"


def test_stub_tier_survives_wiring_the_outline_check(tmp_path):
    """NOT a direction-1 guard — this asserts NEW behaviour and correctly fails
    on the base tree, where the unwired outline check FAILs a stub hardmacro
    with A8_GDS_MISSING_FOR_LEF. Wiring it without teaching it the stub tier
    would have red-lined every deterministic-stub run, contradicting
    analog_hardmacro_check's HARDMACRO_STUB_ACCEPTED / PASS_WITH_STUB."""
    project = _project(tmp_path, gds=None, stub=True)
    cp = _run(HARDMACRO, project)
    assert cp.returncode == 0, cp.stdout
    cp = _run(OUTLINE, project)
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_stub_skip_is_disclosed_by_name_not_silent(tmp_path):
    """A gate may EXPLAIN an absent artefact; it may not pass over one in
    silence. The stub skip must be named in the report AND on stdout."""
    project = _project(tmp_path, gds=None, stub=True)
    out = project / "rep.json"
    cp = _run(OUTLINE, project, "--json", str(out))
    rep = json.loads(out.read_text())
    assert rep["blocks_stub_not_packaged"] == 1, rep
    assert rep["blocks"][0]["status"] == "STUB_NOT_PACKAGED"
    assert rep["blocks"][0]["findings"][0]["rule"] == "A8_STUB_HARDMACRO_NO_GDS"
    assert "A8_STUB_HARDMACRO_NO_GDS" in cp.stdout, cp.stdout


def test_guard_stub_marker_buys_no_free_pass_when_a_gds_is_shipped(tmp_path):
    """The exemption is narrow ON PURPOSE: a stub-marked LEF that DOES ship a
    .gds is compared like any other."""
    project = _project(tmp_path, gds=_real_gds(250.0, 80.0),
                       lef_w=100.0, lef_h=100.0, stub=True)
    cp = _run(OUTLINE, project)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "A8_LEF_GDS_OUTLINE_MISMATCH" in (cp.stdout + cp.stderr)


def test_guard_digital_only_project_is_vacuous_pass_on_both_gates(tmp_path):
    """A completed digital-only run ships no analog_block_list.json. Neither
    gate may turn that red.

    #521 — this test's NAME already said "vacuous pass" while its assertion
    said rc 0, which is the whole defect in one line: the tier was named in
    prose and discarded in the exit code. `analog_hardmacro_check` now answers
    rc 2 (the vacuous tier); `analog_lef_gds_outline_check` was already at
    rc 0 with its own stdout disclosure and is untouched. Neither is red,
    which is what this guard protects.
    """
    project = tmp_path / "digital"
    (project / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    expected = {HARDMACRO: 2, OUTLINE: 0}
    for prog in (HARDMACRO, OUTLINE):
        cp = _run(prog, project)
        assert cp.returncode == expected[prog], (
            f"{prog.name}: {cp.stdout}{cp.stderr}")
        assert cp.returncode != 1, f"{prog.name} turned a digital project red"


def test_guard_outline_check_self_skips_an_unpackaged_block(tmp_path):
    """Documented contract: a hardmacro dir with NEITHER .lef NOR .gds is
    `analog_a8_hardmacro_gen_check`'s business, not this gate's."""
    project = tmp_path / "proj"
    (project / "phase3" / "analog" / "hardmacro" / "blk1").mkdir(parents=True)
    bl = project / "phase3" / "analog" / "analog_block_list.json"
    bl.write_text(json.dumps({"blocks": ["blk1"]}))
    cp = _run(OUTLINE, project)
    assert cp.returncode == 0, cp.stdout + cp.stderr
