#!/usr/bin/env python3
"""tests/test_analog_deferred_adjacents.py — the four analog holes an earlier
fix group located precisely and then deliberately scoped out of its branch.

Every case here is exercised on a SYNTHETIC project. The reference completed
run this backlog was measured against (`converge_ihp-sg13g2`, IHP sg13g2) is a
pure DIGITAL standard-cell flow: it carries no `analog_block_list.json` and no
per-block analog artefact of any kind, so it cannot exercise A1-A9 at all.
Confirmed on that run: no `analog_block_list.json` anywhere in the tree, and
`analog_flow_compliance_check` / `analog_a5|a7|a8|a9_*_check` all rc=0
"no analog blocks declared" before AND after these changes.

1. BLOCK-LIST PATH SPLIT
   `flow/phase1_phase2_phase3.yaml` makes EVERY A-step applicable on
   `condition: files_exist: ["phase1/analog/analog_block_list.json"]`, while
   the A1-A9 gates read `phase3/analog/analog_block_list.json` only. A project
   laid out exactly as its own flow declares therefore had every A-step
   applicable AND every A-gate answering "VACUOUS_PASS: block list missing".

2. PARTIAL BLOCK COVERAGE (A5/A7/A8/A9)
   A1-A4 emit INCOMPLETE when some declared blocks carry the step's artefact
   and others carry none. A7/A8/A9 fell through to PASS on the same shape, so
   one partially-covered project read red at A1-A4 and green at A7-A9.

3. A5's INCOMPLETE REPORT SHAPE
   A5 carried a local copy of the shared emitter whose report omitted
   `incomplete_blocks` / `suggested_skill` / `reason`.

4. A6 SIGN-OFF FLAGS IN `analog_flow_compliance_check`
   `drc_clean.flag` / `lvs_match.flag` were accepted on `.exists()`, so a
   `touch`-created 0-byte flag — and a flag whose own text said
   `violations: 17` — certified A6 done.

Each section carries DIRECTION-1 guards for what must NOT change: the
no-analog VACUOUS_PASS, the all-blocks-missing deferral, the `--block` exit-2
WAIVED deferral, the ORGANIC #676 digital-class N/A skip, and honest sign-off
flags in every dialect the A6 parsers accept.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import _analog_a_check_common as c

PROGS = Path(__file__).resolve().parent.parent
A1 = PROGS / "analog_a1_spec_extract_check.py"
A5 = PROGS / "analog_a5_layout_check.py"
A7 = PROGS / "analog_a7_post_layout_resim_check.py"
A8 = PROGS / "analog_a8_hardmacro_gen_check.py"
A9 = PROGS / "analog_a9_hw_verify_check.py"
FCC = PROGS / "analog_flow_compliance_check.py"


# ── fixture builders ─────────────────────────────────────────────────────
def _block_list(project: Path, blocks: list, root: str = "phase3/analog"):
    d = project / root
    d.mkdir(parents=True, exist_ok=True)
    (d / "analog_block_list.json").write_text(json.dumps({"blocks": blocks}))


def _layout_ok(project: Path, block: str):
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.mag").write_text(
        "magic\ntech sky130A\n" + "rect 0 0 100 100\n" * 20)
    (d / "drc_clean.flag").write_text("DRC clean: 0 errors\n")
    (d / "lvs_match.flag").write_text("LVS match: 0 mismatches\n")


def _layout_stub(project: Path, block: str):
    """A layout source well under the 200-byte substance bar — the shape A5
    must FAIL on. Used to prove a gate actually MEASURED the block."""
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.mag").write_text("magic\ntech sky130A\n<< end >>\n")
    (d / "drc_clean.flag").write_text("violations: 0\n")
    (d / "lvs_match.flag").write_text("lvs: match\n")


def _content_ok(project: Path, block: str):
    """The pre-layout corner result, carrying the record of WHAT CIRCUIT the
    downstream artefacts describe.

    Every test in this file is about BLOCK COVERAGE (how many declared blocks
    produced an artefact at all), so each needs artefacts that clear every
    other rule; without this record they would now fail on content instead,
    and a coverage test that fails for a content reason measures neither.

    IT LIVES HERE AND NOT IN THE DOWNSTREAM ARTEFACT, and the move is the
    point: `_prevspost_ok` used to write `design_content` into
    `pre_vs_post.json` and ship no corner artefact at all, because the A7 gate
    read the derived file FIRST. Nothing deterministic writes the field there
    — an AI skill authors that file — so a fixture that bought a design-bound
    PASS with it was asserting that an AI-authored claim outranks the
    deterministic record. A comparison cannot be more design-bound than the
    pre-layout result it is compared against, and a hardmacro cannot model a
    circuit its own corner sweep never names.
    """
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "corner_results.json").write_text(json.dumps({
        "block": block, "_provenance": "real_ngspice",
        "corners": [{"name": "tt_27c_1v8", "simulator_run": True}],
        "design_content": "structure_and_geometry"}))


def _prevspost_ok(project: Path, block: str):
    """A well-formed A7 comparison, over a baseline that says what it is."""
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    _content_ok(project, block)
    (d / "pre_vs_post.json").write_text(json.dumps({
        "pre": {"gain_db": 60.0}, "post": {"gain_db": 59.0}}))


def _hardmacro_ok(project: Path, block: str):
    d = project / "phase3" / "analog" / "hardmacro" / block
    d.mkdir(parents=True, exist_ok=True)
    _content_ok(project, block)
    (d / f"{block}.lef").write_text(
        f"VERSION 5.8 ;\nMACRO {block}\n  SIZE 100 BY 200 ;\n"
        f"END {block}\nEND LIBRARY\n" + "#" * 400)
    (d / f"{block}.lib").write_text(
        f'library ({block}) {{\n  cell ({block}) {{}}\n}}\n'
        + "/* pad */\n" * 40)
    (d / f"{block}.v").write_text(
        f"module {block}(inout VDD);\nendmodule\n" + "// pad\n" * 40)


def _hwmeas_ok(project: Path, block: str):
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "hw_measurements.json").write_text(json.dumps({
        "instrument": "scope", "measurements": {"vout_v": 1.8}}))


def _spec_ok(project: Path, block: str, root: str = "phase3/analog"):
    d = project / root / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.json").write_text(json.dumps({
        "block": block, "type": "ldo",
        "specs": [{"name": "vout_v", "min": 1.75, "typ": 1.8, "max": 1.85},
                  {"name": "iout_ma", "target": 50}],
    }))


def _run(prog: Path, project: Path, *args: str):
    return subprocess.run(
        [sys.executable, str(prog), str(project),
         "--json", str(project / f"{prog.stem}.json"), *args],
        capture_output=True, text=True)


def _report(prog: Path, project: Path) -> dict:
    return json.loads((project / f"{prog.stem}.json").read_text())


# ═════════════════════════════════════════════════════════════════════════
# 1. BLOCK-LIST PATH SPLIT
# ═════════════════════════════════════════════════════════════════════════
def test_block_list_at_flow_declared_phase1_root_is_found(tmp_path):
    """The root the flow declares in every A-step `condition:` must resolve."""
    _block_list(tmp_path, ["ldo", "bandgap"], root="phase1/analog")
    assert c.load_block_list(tmp_path) == ["ldo", "bandgap"]


def test_phase1_only_project_is_gated_not_vacuously_passed(tmp_path):
    """A5 on a project whose block list sits ONLY at the flow-declared root,
    carrying a stub layout: the gate must MEASURE the block, not answer
    "block list missing"."""
    _block_list(tmp_path, ["ldo"], root="phase1/analog")
    _layout_stub(tmp_path, "ldo")
    r = _run(A5, tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert _report(A5, tmp_path)["verdict"] == "FAIL"


def test_block_list_root_does_not_change_the_verdict(tmp_path_factory):
    """The observable property, independent of HOW it is implemented: two
    projects with byte-identical analog artefacts must get the same verdict
    whichever legitimate root carries the block list."""
    verdicts = {}
    for root in ("phase1/analog", "phase3/analog"):
        p = tmp_path_factory.mktemp(root.replace("/", "_"))
        _block_list(p, ["ldo"], root=root)
        _layout_stub(p, "ldo")
        r = _run(A5, p)
        verdicts[root] = (r.returncode, _report(A5, p)["verdict"])
    assert verdicts["phase1/analog"] == verdicts["phase3/analog"]


def test_flow_compliance_sees_phase1_root_block_list(tmp_path):
    _block_list(tmp_path, ["osc"], root="phase1/analog")
    r = subprocess.run(
        [sys.executable, str(FCC), str(tmp_path),
         "--json", str(tmp_path / "fcc.json")], capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    rpt = json.loads((tmp_path / "fcc.json").read_text())
    assert rpt["summary"]["skipped"] is False
    assert rpt["summary"]["total_missing"] == 9


def test_flow_compliance_reads_a1_spec_at_its_declared_phase1_root(tmp_path):
    """A1's declared output is `phase1/analog/*/spec.json`. The compliance
    matrix must agree with `analog_a1_spec_extract_check`, which resolves it
    there — otherwise one gate calls A1 done and the other calls it MISSING
    on the same file."""
    _block_list(tmp_path, ["ldo"], root="phase1/analog")
    _spec_ok(tmp_path, "ldo", root="phase1/analog")
    subprocess.run(
        [sys.executable, str(FCC), str(tmp_path),
         "--json", str(tmp_path / "fcc.json")], capture_output=True, text=True)
    rpt = json.loads((tmp_path / "fcc.json").read_text())
    assert rpt["summary"]["matrix"]["ldo"]["A1"] == "PASS"
    a1 = _run(A1, tmp_path)
    assert a1.returncode == 0, a1.stdout + a1.stderr


# ── direction-1 guards for section 1 ────────────────────────────────────
def test_d1_no_block_list_anywhere_is_still_vacuous_pass(tmp_path):
    assert c.load_block_list(tmp_path) is None
    r = _run(A5, tmp_path)
    assert r.returncode == 0
    assert _report(A5, tmp_path)["verdict"] == "VACUOUS_PASS"


def test_d1_canonical_runner_root_still_wins_when_both_exist(tmp_path):
    """The analog runner writes phase3; that copy stays authoritative so a
    runner-produced project resolves exactly as it always has."""
    _block_list(tmp_path, ["runner_block"], root="phase3/analog")
    _block_list(tmp_path, ["stale_block"], root="phase1/analog")
    assert c.load_block_list(tmp_path) == ["runner_block"]


def _phantom_digital_soc(tmp_path: Path) -> Path:
    """A pure-digital SoC whose only "analog block" is a low_confidence
    phantom keyword hit, declared at the flow's phase1 root."""
    d = tmp_path / "phase1" / "analog"
    d.mkdir(parents=True)
    (d / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": "por", "low_confidence": True}]}))
    rd = tmp_path / "reports"
    rd.mkdir(parents=True)
    (rd / "ic_class.json").write_text(json.dumps({"has_analog": False}))
    return tmp_path


def test_d1_digital_soc_with_phantom_block_at_phase1_root_never_goes_red(
        tmp_path):
    """THE guard on this whole change: widening the block-list resolution
    must not turn a pure-digital SoC red. Holds on both trees.

    RED means rc 1 / verdict FAIL — the tier that blocks. #511 moved the
    ORGANIC #676 class-N/A skip off the rc-0 PASS tier and onto rc 2, the
    NOT-CHECKED tier the P0 umbrella records as a benign SKIP, because a gate
    that held ZERO A-step obligations to the rule had signed nothing off. The
    guard is unchanged in substance and is asserted in the terms it was always
    about: this project must never FAIL.
    """
    _phantom_digital_soc(tmp_path)
    r = subprocess.run(
        [sys.executable, str(FCC), str(tmp_path),
         "--json", str(tmp_path / "fcc.json")], capture_output=True, text=True)
    assert r.returncode != 1, r.stdout + r.stderr
    assert r.returncode == 2, r.stdout + r.stderr
    rpt = json.loads((tmp_path / "fcc.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS"
    assert not [f for f in rpt["findings"] if f["severity"] == "ERROR"]


def test_organic676_na_skip_is_disclosed_for_a_phase1_root_list(tmp_path):
    """...and the skip must be the DISCLOSED, named ORGANIC #676 N/A skip, not
    the undifferentiated "no analog blocks" skip a gate that cannot see the
    list emits. Both are non-failures; only one of them says why."""
    _phantom_digital_soc(tmp_path)
    assert c.analog_class_is_na(tmp_path) is True
    subprocess.run(
        [sys.executable, str(FCC), str(tmp_path),
         "--json", str(tmp_path / "fcc.json")], capture_output=True, text=True)
    rpt = json.loads((tmp_path / "fcc.json").read_text())
    assert rpt["summary"]["reason"] == "digital_class_na_low_confidence"


def test_phantom_block_at_phase1_root_without_ic_class_is_gated(tmp_path):
    """DISCLOSED COST — the ORGANIC #676 protection above is CONDITIONAL, not
    unconditional. `_ic_class_says_non_analog` is fail-closed by design: a
    project carrying NO class verdict at all is not assumed non-analog, so
    `analog_class_is_na` is False and the phantom block is GATED.

    Measured: BASE (phase3-only resolution, which could not see a phase1-root
    list) rc=0 passed=True 0 ERROR findings; here rc=1 passed=False 9 ERROR
    findings (A1..A9 MISSING for the phantom block). The sibling guard
    `test_d1_digital_soc_with_phantom_block_at_phase1_root_never_goes_red`
    writes `reports/ic_class.json` into its own fixture and so never covers
    this case; this test is what makes the conditionality explicit."""
    d = tmp_path / "phase1" / "analog"
    d.mkdir(parents=True)
    (d / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": "por", "low_confidence": True}]}))
    # Deliberately NO reports/ic_class.json — that is the whole point.
    assert not (tmp_path / "reports" / "ic_class.json").exists()
    assert c._all_blocks_low_confidence(tmp_path) is True
    assert c.analog_class_is_na(tmp_path) is False   # fail-closed, no verdict

    r = subprocess.run(
        [sys.executable, str(FCC), str(tmp_path),
         "--json", str(tmp_path / "fcc.json")], capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    rpt = json.loads((tmp_path / "fcc.json").read_text())
    assert rpt["passed"] is False
    assert rpt["summary"]["skipped"] is False
    assert sum(1 for f in rpt.get("findings", [])
               if f.get("severity") == "ERROR") == 9


def test_d1_real_analog_block_at_phase1_root_is_still_gated(tmp_path):
    """The §4.05 no-leak half of ORGANIC #676: a spec-backed (not
    low_confidence) block is gated even on a non-analog class verdict."""
    d = tmp_path / "phase1" / "analog"
    d.mkdir(parents=True)
    (d / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": "ldo"}]}))
    rd = tmp_path / "reports"
    rd.mkdir(parents=True)
    (rd / "ic_class.json").write_text(json.dumps({"has_analog": False}))
    assert c.analog_class_is_na(tmp_path) is False


# ═════════════════════════════════════════════════════════════════════════
# 2. PARTIAL BLOCK COVERAGE — A7 / A8 / A9
# ═════════════════════════════════════════════════════════════════════════
_PARTIAL = [
    (A7, _prevspost_ok, "analog-extraction-resim"),
    (A8, _hardmacro_ok, "analog-hardmacro-gen"),
    (A9, _hwmeas_ok, "analog-hw-measure"),
]


def _partial_project(tmp_path: Path, produce) -> Path:
    _block_list(tmp_path, ["ldo", "bandgap"])
    (tmp_path / "phase3" / "analog" / "bandgap").mkdir(parents=True,
                                                       exist_ok=True)
    produce(tmp_path, "ldo")
    return tmp_path


def test_partial_coverage_is_not_certified_a7(tmp_path):
    _check_partial(tmp_path, *_PARTIAL[0])


def test_partial_coverage_is_not_certified_a8(tmp_path):
    _check_partial(tmp_path, *_PARTIAL[1])


def test_partial_coverage_is_not_certified_a9(tmp_path):
    _check_partial(tmp_path, *_PARTIAL[2])


def _check_partial(tmp_path, prog, produce, skill):
    _partial_project(tmp_path, produce)
    r = _run(prog, tmp_path)
    assert r.returncode != 0, (
        f"{prog.stem} certified the step with 1 of 2 declared blocks "
        f"carrying no artefact at all:\n{r.stdout}{r.stderr}")
    rpt = _report(prog, tmp_path)
    assert rpt["verdict"] != "PASS"
    # The uncovered block must be NAMED — a non-zero rc that does not say
    # which block is unmeasured is not an explanation.
    assert "bandgap" in json.dumps(rpt)
    assert rpt["blocks_checked"] == 2
    assert rpt["blocks_pass"] == 1


def test_a5_and_a7_agree_on_the_same_partially_covered_project(tmp_path):
    """The consistency the deferral called out: A1-A4 red and A5-A9 green on
    one project is the symptom. Same shape, same class of verdict."""
    _block_list(tmp_path, ["ldo", "bandgap"])
    (tmp_path / "phase3" / "analog" / "bandgap").mkdir(parents=True)
    _layout_ok(tmp_path, "ldo")
    _prevspost_ok(tmp_path, "ldo")
    a5 = _run(A5, tmp_path)
    a7 = _run(A7, tmp_path)
    assert (a5.returncode != 0) == (a7.returncode != 0)
    assert (_report(A5, tmp_path)["verdict"]
            == _report(A7, tmp_path)["verdict"])


# ── direction-1 guards for section 2 ────────────────────────────────────
def test_d1_full_coverage_still_passes_a7(tmp_path):
    _block_list(tmp_path, ["ldo", "bandgap"])
    _prevspost_ok(tmp_path, "ldo")
    _prevspost_ok(tmp_path, "bandgap")
    r = _run(A7, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _report(A7, tmp_path)["verdict"] == "PASS"


def test_d1_full_coverage_still_passes_a8(tmp_path):
    _block_list(tmp_path, ["ldo", "bandgap"])
    _hardmacro_ok(tmp_path, "ldo")
    _hardmacro_ok(tmp_path, "bandgap")
    r = _run(A8, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _report(A8, tmp_path)["verdict"] == "PASS"


def test_d1_full_coverage_still_passes_a9(tmp_path):
    _block_list(tmp_path, ["ldo", "bandgap"])
    _hwmeas_ok(tmp_path, "ldo")
    _hwmeas_ok(tmp_path, "bandgap")
    r = _run(A9, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _report(A9, tmp_path)["verdict"] == "PASS"


def test_d1_zero_coverage_is_still_a_deferral_not_incomplete(tmp_path):
    """The step has not run at all: defer to the skill, do not FAIL. A9's
    simulation-only close depends on exactly this tier staying rc=0."""
    for prog in (A7, A8, A9):
        p = tmp_path / prog.stem
        p.mkdir()
        _block_list(p, ["ldo", "bandgap"])
        r = _run(prog, p)
        assert r.returncode == 0, f"{prog.stem}: {r.stdout}{r.stderr}"
        assert _report(prog, p)["verdict"] == "VACUOUS_PASS"


def test_d1_block_mode_deferral_is_untouched(tmp_path):
    """`--block <uncovered>` must still exit 2 so analog_one_shot_runner
    translates it to WAIVED, not 1."""
    for prog, produce, _skill in _PARTIAL:
        p = tmp_path / prog.stem
        p.mkdir()
        _partial_project(p, produce)
        r = _run(prog, p, "--block", "bandgap")
        assert r.returncode == 2, f"{prog.stem}: {r.stdout}{r.stderr}"
        assert _report(prog, p)["verdict"] == "WAIVED"


# ═════════════════════════════════════════════════════════════════════════
# 3. A5's INCOMPLETE REPORT SHAPE
# ═════════════════════════════════════════════════════════════════════════
_MACHINE_READABLE = ("incomplete_blocks", "suggested_skill", "reason")


def test_a5_incomplete_report_matches_a1s_for_the_same_shape(tmp_path):
    """One project, partial coverage for BOTH A1 and A5. Whatever
    machine-readable fields A1's INCOMPLETE report carries, A5's must carry
    too — a consumer must not have to special-case which gate produced it."""
    _block_list(tmp_path, ["ldo", "bandgap"])
    (tmp_path / "phase3" / "analog" / "bandgap").mkdir(parents=True)
    _spec_ok(tmp_path, "ldo")
    _layout_ok(tmp_path, "ldo")
    a1 = _run(A1, tmp_path)
    a5 = _run(A5, tmp_path)
    r1, r5 = _report(A1, tmp_path), _report(A5, tmp_path)
    assert r1["verdict"] == "INCOMPLETE", a1.stdout + a1.stderr
    assert r5["verdict"] == "INCOMPLETE", a5.stdout + a5.stderr
    present1 = [k for k in _MACHINE_READABLE if k in r1]
    present5 = [k for k in _MACHINE_READABLE if k in r5]
    assert present5 == present1, (
        f"A5's INCOMPLETE report is missing "
        f"{sorted(set(present1) - set(present5))} that A1's carries")
    assert r5["incomplete_blocks"] == ["bandgap"]
    assert r5["suggested_skill"] == "analog-layout"


def test_d1_a5_partial_verdict_and_exit_code_unchanged(tmp_path):
    """Deduping the emitter must not move A5's verdict string or exit code —
    `flow_compliance_check` and the analog runner key on both."""
    _block_list(tmp_path, ["ldo", "bandgap"])
    (tmp_path / "phase3" / "analog" / "bandgap").mkdir(parents=True)
    _layout_ok(tmp_path, "ldo")
    r = _run(A5, tmp_path)
    assert r.returncode == 1
    assert _report(A5, tmp_path)["verdict"] == "INCOMPLETE"


# ═════════════════════════════════════════════════════════════════════════
# 4. A6 SIGN-OFF FLAGS IN analog_flow_compliance_check
# ═════════════════════════════════════════════════════════════════════════
def _pv_project(tmp_path: Path, drc: str, lvs: str) -> Path:
    """Everything A1-A9 needs, with the two A6 markers under test.
    `drc`/`lvs` are written verbatim; "" means `touch` (0 bytes)."""
    _block_list(tmp_path, ["ldo"])
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True, exist_ok=True)
    (ad / "spec.json").write_text("{}")
    (ad / "topology.md").write_text("# ldo\n")
    (ad / "ldo.sp").write_text(".title ldo\n.end\n")
    # WAS `{}`. An empty object is a corner artefact that declares nothing —
    # no corners, no provenance, no statement of what circuit it measured —
    # and every test here asserting a whole-project rc 0 was therefore also
    # asserting that such an artefact signs off A4. These fixtures are about
    # the A6 PV markers, so A4 carries what a run that reached it would.
    (ad / "corner_results.json").write_text(json.dumps({
        "netlist_provenance": "a3_netlist",
        "design_content": "structure_and_geometry",
        "corners": [{"name": "tt_27c", "simulator_run": True, "vout_v": 1.8}],
        "spec_results": [{"name": "vout", "status": "PASS", "target": None}],
    }))
    (ad / "layout.mag").write_text("magic\n")
    (ad / "drc_clean.flag").write_text(drc)
    (ad / "lvs_match.flag").write_text(lvs)
    (ad / "pre_vs_post.json").write_text("{}")
    hm = tmp_path / "phase3" / "analog" / "hardmacro" / "ldo"
    hm.mkdir(parents=True, exist_ok=True)
    (hm / "ldo.lef").write_text("MACRO ldo\nEND ldo\n")
    cd = tmp_path / "phase3" / "mixed_signal" / "cosim"
    cd.mkdir(parents=True, exist_ok=True)
    (cd / "ldo_cosim_results.json").write_text("{}")
    return tmp_path


def _a6_verdict(tmp_path: Path):
    r = subprocess.run(
        [sys.executable, str(FCC), str(tmp_path),
         "--json", str(tmp_path / "fcc.json")], capture_output=True, text=True)
    rpt = json.loads((tmp_path / "fcc.json").read_text())
    return r.returncode, rpt["summary"]["matrix"]["ldo"]["A6"]


def test_touch_created_pv_flags_do_not_certify_a6(tmp_path):
    """0-byte markers: the flag was created, the sign-off never happened."""
    _pv_project(tmp_path, "", "")
    rc, a6 = _a6_verdict(tmp_path)
    assert a6 != "PASS"
    assert rc == 1


def test_pv_flags_reporting_a_violation_do_not_certify_a6(tmp_path):
    """The sharper half: the flag's own text says the block FAILED, and the
    gate used to certify A6 because it never read the text."""
    _pv_project(tmp_path, "violations: 17\n", "lvs: mismatch\n")
    rc, a6 = _a6_verdict(tmp_path)
    assert a6 != "PASS"
    assert rc == 1


def test_pv_flags_with_no_verdict_at_all_do_not_certify_a6(tmp_path):
    """Non-empty but content-free: `echo clean > drc_clean.flag`."""
    _pv_project(tmp_path, "clean\n", "match\n")
    rc, a6 = _a6_verdict(tmp_path)
    assert a6 != "PASS"
    assert rc == 1


# ── direction-1 guards for section 4 ────────────────────────────────────
def test_d1_honest_pv_flags_still_certify_a6(tmp_path):
    _pv_project(tmp_path, "violations: 0\n", "lvs: match\n")
    rc, a6 = _a6_verdict(tmp_path)
    assert a6 == "PASS"
    assert rc == 0


def test_d1_honest_pv_flags_in_another_tool_dialect_still_certify_a6(tmp_path):
    """The rule must be "an explicit clean/match verdict", not one vendor's
    phrasing. Magic/KLayout/Calibre/Netgen wordings all count."""
    _pv_project(tmp_path, "DRC clean: 0 errors\n",
                "LVS match: 0 mismatches\n")
    rc, a6 = _a6_verdict(tmp_path)
    assert a6 == "PASS"
    assert rc == 0


def test_d1_the_actual_producers_flag_text_still_certifies_a6(tmp_path):
    """THE guard on the A6 tightening: `analog_one_shot_runner` is the program
    that writes these two flags (its deterministic A6 stub emits an explicit
    `violations: 0` / `lvs: match` line precisely because
    `analog_a6_block_pv_check` already rejects a bare flag). Verbatim producer
    output must keep certifying A6, or the tightening would break the runner's
    own dry-run path. Holds on both trees."""
    _pv_project(
        tmp_path,
        "# ldo — DRC clean (deterministic stub)\ndeterministic_stub\n"
        "violations: 0\n",
        "# ldo — LVS match (deterministic stub)\ndeterministic_stub\n"
        "lvs: match\n")
    rc, a6 = _a6_verdict(tmp_path)
    assert a6 == "PASS"
    assert rc == 0


def test_d1_missing_pv_flags_are_still_plain_missing(tmp_path):
    _pv_project(tmp_path, "violations: 0\n", "lvs: match\n")
    (tmp_path / "phase3" / "analog" / "ldo" / "drc_clean.flag").unlink()
    rc, a6 = _a6_verdict(tmp_path)
    assert a6 == "MISSING"
    assert rc == 1


def test_d1_a6_waiver_still_works_when_the_flags_are_absent(tmp_path):
    """A disclosed, named waiver is the sanctioned way past a step. This
    shape (no flags at all) is waiver-covered on both trees."""
    _pv_project(tmp_path, "violations: 0\n", "lvs: match\n")
    (tmp_path / "phase3" / "analog" / "ldo" / "drc_clean.flag").unlink()
    (tmp_path / "phase3" / "analog" / "ldo" / "lvs_match.flag").unlink()
    (tmp_path / "phase3" / "analog" / "waivers.json").write_text(json.dumps(
        {"analog_waivers": [{"block": "ldo", "step": "A6"}]}))
    rc, a6 = _a6_verdict(tmp_path)
    assert a6 == "WAIVED"
    assert rc == 0


def test_a6_waiver_is_reachable_under_the_stricter_flag_rule(tmp_path):
    """A newly-red step must still be waivable. Before the fix the 0-byte
    flags took the PASS branch, so the waiver was never consulted at all —
    the honest escape hatch was unreachable for exactly the projects that
    needed it."""
    _pv_project(tmp_path, "", "")
    (tmp_path / "phase3" / "analog" / "waivers.json").write_text(json.dumps(
        {"analog_waivers": [{"block": "ldo", "step": "A6"}]}))
    rc, a6 = _a6_verdict(tmp_path)
    assert a6 == "WAIVED"
    assert rc == 0
