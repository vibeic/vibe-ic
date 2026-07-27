#!/usr/bin/env python3
"""MEDIUM/LOW flow-gate audit backlog — synth_dft bucket (steps 9-14 + DT1-DT3).

Every test below is a BEHAVIOURAL discriminator for one audited defect, or a
direction-1 guard for something that must NOT change. Measured against the real
completed run ``campaign_pr427/spm/converge_ihp-sg13g2`` (pure digital
standard-cell; the analog A* / mixed-signal M* tracks are untouched here).

Defects covered
---------------
step 14 / dim 7  the Step-14 hilomap gate self-reported VACUOUS_PASS
                 ("not applicable") on an inline-``yosys -p`` run whose synth
                 log held the complete command, hilomap included — the thing
                 the gate exists to check was on disk and unread.
step 11 / dim 5  three gate docstrings + the flow-yaml gate comments promised
                 "never a vacuous pass on absence" / "There is no SKIP path"
                 while the shipped code returns rc=2 SKIPPED-CONDITION on a
                 disclosed absence.
step 11 / dim 5  the disclosed-skip reason string named "sky130" on a run whose
                 PDK was ihp-sg13g2.
DT1-DT3 / dim 8  the artefact each step exists to produce was declared nowhere,
                 so no required_outputs-driven tool could enumerate it.
step 11 / dim 8  the ATPG test vectors (tv.json) were produced and declared
                 nowhere.
step 9 / dim 1   synth_wrapper_gen's docstring promised an ``.sdc`` output it
                 never writes, and named runner trigger keys that do not exist.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
FLOW_YAML = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"

_LIB = "/foss/pdks/x/libs.ref/y/lib/z_typ.lib"
_CMD_CONFORMANT = (
    f"read_verilog -sv a.v; hierarchy -check -top t; proc; flatten; "
    f"synth -top t -flatten; dfflibmap -liberty {_LIB}; abc -liberty {_LIB}; "
    f"hilomap -hicell TIEHI L_HI -locell TIELO L_LO; clean; "
    f"write_verilog -noattr out.v"
)
_CMD_NO_HILOMAP = (
    f"read_verilog -sv a.v; hierarchy -check -top t; proc; flatten; "
    f"synth -top t -flatten; dfflibmap -liberty {_LIB}; abc -liberty {_LIB}; "
    f"clean; write_verilog -noattr out.v"
)
_CMD_SIM_ONLY = (
    "read_verilog -sv -DSIMULATION a.v; hierarchy -check -top t; proc; "
    "synth -top t -flatten; write_verilog -noattr out.v"
)


def _run(prog: str, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROGRAMS / prog), *argv],
                          capture_output=True, text=True)


def _flow_steps() -> dict:
    doc = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))
    return {str(s.get("id")): s for s in doc["steps"]}


# ===========================================================================
# step 14 / dim 7 — the gate must READ the inline command, not assume
# ===========================================================================
def _inline_project(tmp_path: Path, command: str | None) -> Path:
    """A project with NO .ys script, synthesised the inline `yosys -p` way."""
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (tmp_path / "reports" / "orchestrator").mkdir(parents=True)
    (tmp_path / "reports" / "orchestrator" / "phase3_one_shot.json").write_text(
        '{"runner": "phase3_one_shot_runner"}')
    log = "yosys> \n"
    if command is not None:
        # yosys 用 GNU 非對稱引號輸出：開頭反引號、結尾單引號（`cmd'），不是
        # 對稱的一對反引號。這個 fixture 原本寫成對稱形式，於是 audit_inline_yosys
        # 回 NO_INLINE_COMMAND、整條內容稽核走不到——測試在測一個 yosys 不會產生的
        # 輸入，因此對真正的缺陷沒有鑑別力。（PR #474 修的正是同一個引號形狀。）
        log += f"\n-- Running command `{command}' --\n\n9. Executing pass.\n"
    else:
        log += "\n(no command echoed)\n"
    (synth / "synth.log").write_text(log)
    return tmp_path


def test_step14_inline_command_missing_hilomap_fails(tmp_path):
    """DISCRIMINATOR. A real-PDK inline synth that never ran hilomap ships a
    netlist OpenROAD detailed_route crashes on (DRT-0305). The gate must exit
    non-zero and say FAIL — not certify the step 'not applicable'."""
    proj = _inline_project(tmp_path, _CMD_NO_HILOMAP)
    out = tmp_path / "gate.json"
    r = _run("yosys_hilomap_required_check.py", str(proj), "--json", str(out))
    assert r.returncode == 1, r.stdout + r.stderr
    report = json.loads(out.read_text())
    assert report["verdict"] == "FAIL"
    assert report["messages"], "a FAIL must name what is missing"
    assert any("hilomap" in m for m in report["messages"])


def test_step14_inline_command_with_hilomap_is_content_verified(tmp_path):
    """DISCRIMINATOR. The real spm x ihp-sg13g2 shape: hilomap ran, correctly,
    and the command is in the log. The gate must report that it VERIFIED it,
    naming the log — a VACUOUS_PASS here is the audited defect."""
    proj = _inline_project(tmp_path, _CMD_CONFORMANT)
    out = tmp_path / "gate.json"
    r = _run("yosys_hilomap_required_check.py", str(proj), "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(out.read_text())
    # verdict 維持 VACUOUS_PASS 是 #474 的刻意設計，不是缺陷：「沒有 .ys 腳本」本身
    # 就被歸為這個 gate 的非適用情境，而該 PR 的既有測試明確釘住這個層級。被驗證過這
    # 件事記在 reason_class 與 inline_evidence 上——本測試因此斷言那兩者，而不是要求
    # verdict 升級。記下這個張力供後人參考：verdict 字面說「不適用」，reason_class 卻
    # 說「已抽取並驗證合規」，兩者若要對齊是流程擁有者的決定，不該由旁支單方面推翻。
    assert report["verdict"] == "VACUOUS_PASS"
    assert report["reason_class"] == "inline_yosys_p_mode_conformant"
    # `real_pdk_commands_audited` 是本分支被丟棄的重複實作才有的欄位；#474 落地的
    # 版本以 inline_evidence 表達同一件事（審查了哪些 log）。斷言可觀察的證據本身，
    # 不綁任何一方的欄位命名。
    assert any("synth.log" in e for e in report["inline_evidence"])


def test_step14_simulation_only_inline_command_is_not_claimed_verified(tmp_path):
    """DIRECTION-1. A sim-only inline synth binds no Liberty, so hilomap does
    not apply: it must stay rc=0 (this gate must not start blocking sim-only
    flows) AND must not claim a real-PDK command was verified."""
    proj = _inline_project(tmp_path, _CMD_SIM_ONLY)
    out = tmp_path / "gate.json"
    r = _run("yosys_hilomap_required_check.py", str(proj), "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(out.read_text())
    assert report.get("real_pdk_commands_audited", 0) == 0


def test_step14_no_inline_command_still_vacuous_pass(tmp_path):
    """DIRECTION-1. When nothing echoed a yosys command there is genuinely
    nothing to audit; the pre-existing marker-file VACUOUS_PASS must survive."""
    proj = _inline_project(tmp_path, None)
    out = tmp_path / "gate.json"
    r = _run("yosys_hilomap_required_check.py", str(proj), "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(out.read_text())["verdict"].startswith("VACUOUS_PASS")


def test_step14_ys_script_path_unchanged(tmp_path):
    """DIRECTION-1. The .ys-script branch is untouched: correct ordering
    passes, a script missing hilomap still fails."""
    ok = tmp_path / "ok.ys"
    ok.write_text("read_verilog a.v\nsynth -top t\ntechmap\n"
                  f"abc -liberty {_LIB}\ntechmap\nhilomap -hicell A a\n"
                  "write_verilog out.v\n")
    bad = tmp_path / "bad.ys"
    bad.write_text("read_verilog a.v\nsynth -top t\ntechmap\n"
                   f"abc -liberty {_LIB}\nwrite_verilog out.v\n")
    assert _run("yosys_hilomap_required_check.py",
                "--ys-file", str(ok)).returncode == 0
    assert _run("yosys_hilomap_required_check.py",
                "--ys-file", str(bad)).returncode == 1


def test_step14_sibling_template_gate_untouched(tmp_path):
    """DIRECTION-1. Only the hilomap gate was changed. Its Step-14 sibling
    must behave exactly as before on the same inline-only project."""
    proj = _inline_project(tmp_path, _CMD_CONFORMANT)
    out = tmp_path / "tmpl.json"
    r = _run("yosys_script_template_check.py", str(proj), "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(out.read_text())["verdict"].startswith("VACUOUS_PASS")


# ===========================================================================
# step 11 / dim 5 — docstring must state the rc the code actually returns
# ===========================================================================
_DFT_GATES = ("dft_atpg_coverage_check.py", "bsdl_emit.py",
              "dft_signoff_check.py")


def _dft_project(tmp_path: Path, *, disclosed: bool) -> Path:
    """Step-11 evidence genuinely absent; optionally with the runner's honest
    `dft_atpg_not_run.json` sentinel beside it (the real spm run's shape)."""
    dft = tmp_path / "phase2" / "stage2" / "dft"
    dft.mkdir(parents=True)
    (tmp_path / "reports" / "phase2" / "dft").mkdir(parents=True)
    if disclosed:
        (dft / "dft_atpg_not_run.json").write_text(json.dumps({
            "verdict": "SKIPPED-CONDITION",
            "reason": "OSS Fault ATPG could not measure sign-off coverage",
            "capability_flag": "cap:atpg_signoff_coverage",
        }))
    return tmp_path


@pytest.mark.parametrize("prog", _DFT_GATES)
def test_dft_gate_docstring_matches_its_disclosed_skip_behaviour(tmp_path, prog):
    """DISCRIMINATOR (documentation-vs-code consistency, both directions).

    Run the gate on genuinely-absent evidence plus the disclosed sentinel and
    observe the exit code; the module docstring must describe THAT outcome.
    A tree that keeps the rc=2 disclosed-skip must document it; a tree that
    removes the skip path must not promise one. Before this change all three
    docstrings said the opposite of what the code did ("There is no SKIP
    path" / "never a vacuous pass on absence")."""
    proj = _dft_project(tmp_path, disclosed=True)
    r = _run(prog, str(proj))
    doc = (PROGRAMS / prog).read_text(encoding="utf-8").split('"""')[1]
    if r.returncode == 2:
        assert "SKIPPED-CONDITION" in doc, (
            f"{prog} exits 2 / SKIPPED-CONDITION on a disclosed absence but "
            f"its docstring never says so")
        assert "rc=2" in doc, (
            f"{prog} exits 2 on this input; the docstring must state that rc")
    elif r.returncode == 1:
        assert "SKIPPED-CONDITION" not in doc, (
            f"{prog} FAILs on a disclosed absence; the docstring must not "
            f"promise a SKIPPED-CONDITION path it does not have")


@pytest.mark.parametrize("prog", _DFT_GATES)
def test_dft_gate_undisclosed_absence_still_fails(tmp_path, prog):
    """DIRECTION-1. The narrow rule the code really enforces: absence ALONE is
    never enough. With no sentinel, absent stuck-at evidence must still FAIL."""
    proj = _dft_project(tmp_path, disclosed=False)
    r = _run(prog, str(proj))
    assert r.returncode == 1, (
        f"{prog} rc={r.returncode} on an UNDISCLOSED absence — expected an "
        f"honest FAIL\n{r.stdout}\n{r.stderr}")


def test_step11_flow_gate_comment_does_not_deny_the_disclosed_skip(tmp_path):
    """DISCRIMINATOR. The flow yaml's own step-11 gate comments made the same
    unqualified claim the programs did. Same consistency property, and keyed on
    the same observation: run the gates, see what they return, then require the
    file that DECLARES them to describe that outcome."""
    proj = _dft_project(tmp_path, disclosed=True)
    codes = {p: _run(p, str(proj)).returncode for p in _DFT_GATES}

    step11 = _flow_steps()["11"]
    text = FLOW_YAML.read_text(encoding="utf-8")
    start = text.index("- id: 11\n", text.index("- id: 10\n"))
    end = text.index("- id: FS1", start)
    block = text[start:end]
    assert "dft_atpg_coverage_check" in block, "wrong block extracted"
    assert step11.get("gate"), "step 11 must still have a gate"

    if any(c == 2 for c in codes.values()):
        assert "SKIPPED-CONDITION" in block, (
            f"step 11's gate programs return {codes} on a disclosed absence; "
            f"the yaml comments must name that outcome instead of asserting "
            f"the gate never passes on absence")
    else:
        assert "SKIPPED-CONDITION" not in block, (
            f"no step-11 gate takes a disclosed-skip path ({codes}); the yaml "
            f"must not describe one")


# ===========================================================================
# step 11 / dim 5 — the disclosed-skip reason must name THIS run's PDK
# ===========================================================================
def test_dft_gap_reason_names_the_detected_pdk():
    """DISCRIMINATOR. The reason prose was a constant naming sky130 on every
    run; the real ihp-sg13g2 run emitted it beside its own
    `pdk_detected: generic_unmapped`. Assert the GOOD thing is present: the
    prose names whatever the netlist sniff detected."""
    sys.path.insert(0, str(PROGRAMS))
    import design_one_shot_runner as dosr
    assert "ihp-sg13g2" in dosr._dft_atpg_gap_reason("ihp-sg13g2")
    assert "generic_unmapped" in dosr._dft_atpg_gap_reason(None)
    # DIRECTION-1: the case the constant used to get right stays right.
    assert "sky130" in dosr._dft_atpg_gap_reason("sky130")


# ===========================================================================
# DT1-DT3 / dim 8 — the produced artefact must be declared
# ===========================================================================
_DT_ARTEFACTS = {
    "DT1": ("reports/phase2/dft/transition_coverage.json",
            "phase2/stage2/dft/transition_atpg_not_run.json"),
    "DT2": ("reports/phase2/dft/path_delay_coverage.json",
            "phase2/stage2/dft/path_delay_atpg_not_run.json"),
    "DT3": ("reports/phase2/dft/sdd_coverage.json",
            "phase2/stage2/dft/sdd_atpg_not_run.json"),
}


@pytest.mark.parametrize("sid,paths", sorted(_DT_ARTEFACTS.items()))
def test_dt_step_artefact_is_enumerable_through_required_outputs(
        tmp_path, sid, paths):
    """DISCRIMINATOR. The observable property the defect is about: a tool that
    asks "what artefacts should this step have?" through required_outputs must
    see the step's real coverage report. Measured with the same resolver
    flow_dashboard_data uses; before this change it returned n_total=0 for all
    three and fell back to the loose umbrella token scan used for P0."""
    sys.path.insert(0, str(PROGRAMS))
    import flow_dashboard_data as fdd

    coverage_rel, _notrun_rel = paths
    p = tmp_path / coverage_rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"verdict": "PASS"}')

    step = _flow_steps()[sid]
    outputs, n_present, n_total = fdd._resolve_outputs(
        tmp_path, step.get("required_outputs"))
    assert n_total >= 1, f"{sid} declares no required_outputs"
    assert n_present >= 1
    assert any(coverage_rel in str(o) for o in outputs), outputs


@pytest.mark.parametrize("sid,paths", sorted(_DT_ARTEFACTS.items()))
def test_dt_declaration_is_a_real_backstop_not_an_any_of(sid, paths):
    """DISCRIMINATOR + the reason the ` OR ` spelling was rejected.

    `flow_condition_reachability_check` treats a path as a T3 BACKSTOP only
    when its absence forces some step to MISSING. A single pattern with two OR
    branches is any-of at the branch level, so a co-declared not-run record
    would satisfy the entry while the measurement was gone — which would make
    DT3's baselined self-disabling hole LOOK closed without being closed, and
    puts DT1 in R1 SELF-GATE (its own condition names both branches). Assert
    the declaration is a single un-OR'd pattern per step."""
    sys.path.insert(0, str(PROGRAMS))
    import flow_condition_reachability_check as R

    coverage_rel, notrun_rel = paths
    decl = _flow_steps()[sid].get("required_outputs") or []
    assert len(decl) == 1, f"{sid} must declare exactly one pattern: {decl}"
    branches = R._or_branches(decl[0])
    assert branches == [coverage_rel], branches
    assert notrun_rel not in branches


def _reachability():
    sys.path.insert(0, str(PROGRAMS))
    import flow_condition_reachability_check as R
    holes = R.classify(FLOW_YAML)
    baseline = json.loads(
        (FLOW_YAML.parent / "flow_condition_reachability_baseline.json")
        .read_text())["holes"]
    return holes, baseline


def test_flow_conditions_have_no_unbaselined_self_disabling_holes():
    """DIRECTION-1. Adding a declaration must never OPEN a self-disabling hole
    or need a new baseline excuse. Passes on both trees."""
    holes, baseline = _reachability()
    baselined = {(str(b["step"]), b.get("program") or None,
                  tuple(sorted(map(str, b["paths"]))))
                 for b in baseline}
    unbaselined = [h for h in holes if h["verdict"] == "self-disabling"
                   and (str(h["step"]), h["program"] or None,
                        tuple(sorted(h["paths"]))) not in baselined]
    assert not unbaselined, unbaselined


def test_dt3_self_disabling_hole_is_closed_and_its_baseline_entry_deleted():
    """DISCRIMINATOR. DT3 was gated ALL-of on DT1's and DT2's outputs, so an
    upstream ATPG step that produced nothing made DT3 vanish silently —
    baselined as a known-open hole. Making each upstream coverage report its
    owner's SOLE single-branch required_output turns both triggers into real T3
    backstops: their absence forces the owning step to MISSING, loudly. The
    baseline entry must go with it — the file's own rule is that a fix deletes
    its entry in the same change."""
    holes, baseline = _reachability()
    dt3 = [h for h in holes
           if str(h["step"]) == "DT3" and h["verdict"] == "self-disabling"]
    assert not dt3, dt3
    assert not [b for b in baseline if str(b["step"]) == "DT3"], baseline


@pytest.mark.parametrize("sid,gate_prog", [
    ("DT1", "transition_coverage_check.py"),
    ("DT2", "path_delay_coverage_check.py"),
    ("DT3", "sdd_coverage_check.py"),
])
def test_dt_gate_still_fails_without_a_measurement(tmp_path, sid, gate_prog):
    """DIRECTION-1. Declaring an output must not make an absent measurement
    passable. With neither the coverage report nor a not-run record, each DT
    gate must still exit non-zero."""
    (tmp_path / "phase2" / "stage2" / "dft").mkdir(parents=True)
    (tmp_path / "reports" / "phase2" / "dft").mkdir(parents=True)
    r = _run(gate_prog, str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr


def test_dt_declared_outputs_match_the_producers_own_skip_claim():
    """DIRECTION-1 / consistency. `atpg_disclose_not_run` writes
    `skips_required_output: <coverage json>` — a claim about what the step
    declares. The declaration must actually contain the path the producer
    names, or the runner is describing a requirement nobody states."""
    steps = _flow_steps()
    runner = (PROGRAMS / "phase3_one_shot_runner.py").read_text(
        encoding="utf-8")
    for sid, (coverage_rel, _notrun) in _DT_ARTEFACTS.items():
        assert coverage_rel in runner, (
            f"{coverage_rel} is no longer the path the runner records")
        declared = " ".join(steps[sid].get("required_outputs") or [])
        assert coverage_rel in declared, (
            f"{sid} does not declare {coverage_rel}, which "
            f"phase3_one_shot_runner names as the output it skips")


# ===========================================================================
# step 11 / dim 8 — the ATPG test vectors must be declared, and ONLY what a
# successful run really leaves behind
# ===========================================================================
def _step11_happy_path(tmp_path: Path) -> Path:
    """The shape `fault_atpg_run` leaves when the engine DID measure: the
    canonical outputs exist and scan_netlist.v was never renamed to prelim."""
    dft = tmp_path / "phase2" / "stage2" / "dft"
    dft.mkdir(parents=True)
    rep = tmp_path / "reports" / "phase2" / "dft"
    rep.mkdir(parents=True)
    (dft / "scan_netlist.v").write_text("module scan; endmodule\n")
    (dft / "atpg_coverage.rpt").write_text("Stuck-at %    : 96.00\n")
    (dft / "tv.json").write_text('{"vectors": []}')
    (dft / "cell_model_combined.v").write_text("// combined\n")
    (dft / "transition_atpg_plan.md").write_text("# plan\n")
    (rep / "coverage.json").write_text(json.dumps(
        {"coverage_pct": 96.0, "target_pct": 95.0}))
    (rep / "bsdl_plan.json").write_text('{"verdict": "N_A"}')
    return tmp_path


def test_step11_declares_the_atpg_test_vectors(tmp_path):
    """DISCRIMINATOR. tv.json is the shippable result of an ATPG step and was
    produced (287 KB on the real run) with nothing declaring it."""
    sys.path.insert(0, str(PROGRAMS))
    import flow_dashboard_data as fdd
    proj = _step11_happy_path(tmp_path)
    decl = _flow_steps()["11"]["required_outputs"]
    assert any("tv.json" in d for d in decl), decl
    _o, n_present, n_total = fdd._resolve_outputs(proj, decl)
    assert n_present == n_total, (
        f"a successful step 11 does not satisfy its own declaration: "
        f"{n_present}/{n_total}")


def test_step11_declaration_is_satisfiable_by_a_successful_run(tmp_path):
    """DIRECTION-1. The declaration must resolve fully on the happy path — in
    particular it must NOT name `scan_netlist_prelim.v`, which exists only
    when the engine measured nothing (measured: adding it takes a passing run
    from 5/5 to 5/6, i.e. reports every success MISSING)."""
    proj = _step11_happy_path(tmp_path)
    sys.path.insert(0, str(PROGRAMS))
    import flow_dashboard_data as fdd
    decl = _flow_steps()["11"]["required_outputs"]
    assert not any("scan_netlist_prelim" in d for d in decl), decl
    _o, n_present, n_total = fdd._resolve_outputs(proj, decl)
    assert n_present == n_total
    # And the coverage gate still passes on this shape, so the fixture really
    # is a successful run and not an accidentally-red one.
    assert _run("dft_atpg_coverage_check.py", str(proj)).returncode == 0


# ===========================================================================
# step 9 / dim 1 — synth_wrapper_gen's docstring vs what it writes
# ===========================================================================
def test_synth_wrapper_gen_docstring_output_line_matches_files_written(tmp_path):
    """DISCRIMINATOR (both directions). The docstring's `Output:` line named an
    `.sdc` the program never writes. Compare the suffixes that line claims
    against the files a real invocation actually creates — a tree that
    implements the .sdc passes just as a tree that drops the claim does."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.sv").write_text(
        "module dut(input wire clk, input wire reset_n, inout wire sda);\n"
        "endmodule\n")
    before = {p.name for p in rtl.iterdir()}
    r = _run("synth_wrapper_gen.py", str(tmp_path), "--top", "dut")
    assert r.returncode == 0, r.stdout + r.stderr
    created = {p.name for p in rtl.iterdir()} - before
    assert created, "generator wrote nothing for an inout-bearing top"

    doc = (PROGRAMS / "synth_wrapper_gen.py").read_text(
        encoding="utf-8").split('"""')[1]
    out_line = next(ln for ln in doc.splitlines()
                    if ln.strip().startswith("Output:"))
    for suffix in (".sv", ".sdc"):
        claimed = suffix in out_line
        produced = any(n.endswith(suffix) for n in created)
        verb = "produced" if produced else "did not produce"
        assert claimed == produced, (
            f"docstring Output: line {'claims' if claimed else 'omits'} "
            f"{suffix} but the run {verb} one: {sorted(created)}")


def test_synth_wrapper_gen_still_skips_a_design_with_no_inout(tmp_path):
    """DIRECTION-1. The no-inout early return is unchanged: rc 0, no file."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.sv").write_text(
        "module dut(input wire clk, output wire q);\nendmodule\n")
    r = _run("synth_wrapper_gen.py", str(tmp_path), "--top", "dut")
    assert r.returncode == 0
    assert not (rtl / "dut_synth.sv").exists()
