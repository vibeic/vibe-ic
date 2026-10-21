#!/usr/bin/env python3
"""Focused controls for persistent P2/P3 canonical-run admission."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import canonical_run_admission as cra  # noqa: E402
import design_input_digest as did  # noqa: E402
from _delivery_declaration import declare_delivery as _declare  # noqa: E402


def test_standalone_isolated_path_load_resolves_required_siblings(tmp_path):
    """The inventory may load this file outside ``programs/`` and under ``-I``.

    That path must retain the ordinary, fail-loud sibling imports; this is not
    an import fallback or a test-only ``PYTHONPATH`` workaround.
    """
    target = PROGRAMS / "canonical_run_admission.py"
    loader = (
        "import importlib.util, sys; "
        "p = sys.argv[1]; "
        "s = importlib.util.spec_from_file_location('isolated_canonical_admission', p); "
        "m = importlib.util.module_from_spec(s); "
        "sys.modules[s.name] = m; "
        "s.loader.exec_module(m); "
        "assert m.emit_attestation.__file__ and m._eda_pin.__file__"
    )
    got = subprocess.run(
        [sys.executable, "-I", "-c", loader, str(target)],
        cwd=tmp_path, text=True, capture_output=True)
    assert got.returncode == 0, got.stderr


def _project(root: Path) -> Path:
    (root / "input").mkdir(parents=True)
    (root / "input" / "spec.md").write_text("counter specification\n")
    (root / "phase1" / "input_doc").mkdir(parents=True)
    (root / "phase1" / "input_doc" / "brief.md").write_text("brief\n")
    (root / "phase1" / "generated_docs").mkdir(parents=True)
    (root / "phase1" / "generated_docs" / "L1.json").write_text('{"layer": 1}\n')
    (root / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (root / "phase2" / "stage1" / "rtl" / "core.v").write_text(
        "module core(input a, output y); assign y = a; endmodule\n")
    (root / "phase2" / "stage2" / "constraints").mkdir(parents=True)
    (root / "phase2" / "stage2" / "constraints" / "core.sdc").write_text(
        "create_clock -period 10 [get_ports a]\n")
    return root


def _admit(root: Path, **changes):
    cfg = {"top_name": "chip_top", "util": 0.3}
    cfg.update(changes.pop("config", {}))
    return cra.admit(root, "phase2", container_image=changes.pop(
        "image", "sha256:" + "a" * 64), config=cfg,
        program_paths=changes.pop("programs", [PROGRAMS / "design_one_shot_runner.py"]))


def test_same_identity_is_refused_after_persistent_reload(tmp_path):
    project = _project(tmp_path / "proj")
    first = _admit(project)
    assert first.admitted and first.reason == "ADMITTED"
    # A new Python-level caller has no in-memory state to consult.  The JSONL
    # ledger must still refuse the exact same P2 work.
    second = _admit(project)
    assert not second.admitted
    assert second.reason == "DUPLICATE_NO_NEW_EVIDENCE"


def test_canonical_program_paths_bind_dispatch_and_frontend_contracts():
    paths = cra.canonical_program_paths(PROGRAMS)
    names = {path.name for path in paths}
    assert {
        "vibe_ic_one_shot_runner.py",
        "design_one_shot_runner.py", "phase3_one_shot_runner.py",
        "execution_policy.py", "execution_modes.py",
        "execution_frontend_providers.py", "execution_frontend_worker.py",
        "librelane_contract.py",
    }.issubset(names)


def test_frontdoor_source_fix_reopens_checkpoint_operation(tmp_path):
    project = _project(tmp_path / "proj")
    programs = tmp_path / "programs"
    programs.mkdir()
    frontdoor = programs / "vibe_ic_one_shot_runner.py"
    frontdoor.write_text("def main(): return 1\n")
    paths = cra.canonical_program_paths(programs)
    assert _admit(project, programs=paths).admitted
    assert not _admit(project, programs=paths).admitted
    frontdoor.write_text("def main(): return 0\n")
    assert _admit(project, programs=paths).admitted


def test_canonical_authored_rtl_change_reopens_phase2_admission(tmp_path):
    project = _project(tmp_path / "proj")
    assert _admit(project).admitted
    assert not _admit(project).admitted
    rtl = project / "phase2" / "stage1" / "rtl" / "core.v"
    rtl.write_text("module core(input a, output y); assign y = ~a; endmodule\n")
    reopened = _admit(project)
    assert reopened.admitted
    assert reopened.reason == "ADMITTED"


def test_librelane_switch_change_reopens_phase2_but_reports_do_not(tmp_path):
    project = _project(tmp_path / "proj")
    switch = project / "phase3" / "librelane_switch.json"
    switch.parent.mkdir(parents=True)
    switch.write_text(json.dumps({"image": "repo@sha256:" + "a" * 64}) + "\n")

    first = _admit(project)
    assert first.admitted

    reports = project / "reports"
    reports.mkdir()
    (reports / "regenerated.json").write_text('{"status":"new"}\n')
    report_only = _admit(project)
    assert not report_only.admitted
    assert report_only.reason == "DUPLICATE_NO_NEW_EVIDENCE"
    assert report_only.identity_sha256 == first.identity_sha256

    switch.write_text(json.dumps({"image": "repo@sha256:" + "b" * 64}) + "\n")
    changed = _admit(project)
    assert changed.admitted
    assert changed.identity_sha256 != first.identity_sha256


def test_substantive_identity_changes_reopen_but_runtime_ledger_does_not(tmp_path):
    project = _project(tmp_path / "proj")
    assert _admit(project).admitted

    # The admission ledger changes only runtime bookkeeping; it is intentionally
    # not part of the design-input digest and cannot buy a fresh run.
    before = did.scan_inputs(project)
    (project / cra.STATE_DIR / "runtime.json").write_text(
        json.dumps({"last_poll": "changed"}) + "\n")
    after = did.scan_inputs(project)
    assert before.stats == after.stats

    # A real source edit changes the source identity and reopens admission.
    (project / "input" / "spec.md").write_text("counter specification v2\n")
    assert _admit(project).admitted

    # The generated L-doc receipt is not an output loophole: changing it is a
    # different Phase-1 contract and must reopen the downstream span.
    (project / "phase1" / "generated_docs" / "L1.json").write_text('{"layer": 1, "v": 2}\n')
    assert _admit(project).admitted

    # A tool-image or dispatch-contract change is also substantive evidence.
    assert _admit(project, image="sha256:" + "b" * 64).admitted
    assert _admit(project, config={"util": 0.4}).admitted


def test_corrupt_ledger_fails_closed(tmp_path):
    project = _project(tmp_path / "proj")
    path = cra.ledger_path(project)
    path.parent.mkdir(parents=True)
    path.write_text("not json\n")
    got = _admit(project)
    assert not got.admitted
    assert got.reason == "ADMISSION_LEDGER_CORRUPT"


def test_unavailable_ledger_lock_fails_closed(tmp_path, monkeypatch):
    project = _project(tmp_path / "proj")
    monkeypatch.setattr(cra.fcntl, "flock", lambda *_: (_ for _ in ()).throw(OSError("busy")))
    got = _admit(project)
    assert not got.admitted
    assert got.reason == "ADMISSION_LEDGER_LOCK_UNAVAILABLE"


def test_delegated_child_only_accepts_exact_parent_identity(tmp_path, monkeypatch):
    project = _project(tmp_path / "proj")
    first = _admit(project)
    assert first.admitted
    monkeypatch.setenv(cra.DELEGATION_ENV, first.identity_sha256)
    delegated = _admit(project)
    assert delegated.admitted
    assert delegated.reason == "DELEGATED_PARENT_ADMISSION"
    monkeypatch.setenv(cra.DELEGATION_ENV, "different-run")
    refused = _admit(project)
    assert not refused.admitted
    assert refused.reason == "DUPLICATE_NO_NEW_EVIDENCE"


def test_phase3_reopens_only_when_its_consumed_phase2_input_moves(tmp_path):
    project = _project(tmp_path / "proj")
    netlist = project / "phase2" / "stage2" / "synth" / "netlist.v"
    netlist.parent.mkdir(parents=True)
    netlist.write_text("module chip_top; endmodule\n")
    kw = {"container_image": "sha256:" + "c" * 64,
          "config": {"top_name": "chip_top", "util": 0.3},
          "program_paths": [PROGRAMS / "phase3_one_shot_runner.py"]}
    assert cra.admit(project, "phase3", **kw).admitted
    assert not cra.admit(project, "phase3", **kw).admitted
    netlist.write_text("module chip_top; wire changed; endmodule\n")
    assert cra.admit(project, "phase3", **kw).admitted


def _load_runner(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, PROGRAMS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve postponed annotations through sys.modules during
    # import, exactly as normal import machinery would.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_direct_phase_runners_refuse_before_expensive_dispatch(tmp_path, monkeypatch,
                                                                capsys):
    """Integration seam: both bypassable CLIs obey a negative admission."""
    import execution_policy as policy
    # The CLIs bootstrap before admission. Restore that in-process metadata
    # on teardown so a later caller does not inherit this fixture's project.
    monkeypatch.setattr(policy, '_ordinary_runtime', None)
    project = _project(tmp_path / "proj")
    refused = cra.Admission(False, "DUPLICATE_NO_NEW_EVIDENCE", "x", {}, "control")

    design = _load_runner("design_one_shot_runner.py", "_test_direct_phase2")
    monkeypatch.setattr(design._runner_lock, "acquire_or_reenter", lambda *_: object())
    monkeypatch.setattr(design._canonical_admission, "admit_span", lambda *a, **k: refused)
    monkeypatch.setattr(sys, "argv", ["design_one_shot_runner.py", str(project)])
    assert design.main() == 2
    assert "canonical Phase-2 admission" in capsys.readouterr().err

    # Phase 3 refuses an UNDECLARED delivery before it asks admission (#2376,
    # `_delivery_admission_refusal`), so without a declaration this arm was
    # measuring that gate and never reached the admission it is about -- the
    # same missing input 71fa6cea0 supplied to two other `main()` fixture
    # families. The delivery gate stays enabled; the input is supplied.
    _declare(project)
    phase3 = _load_runner("phase3_one_shot_runner.py", "_test_direct_phase3")
    monkeypatch.setattr(phase3._runner_lock, "acquire_or_reenter", lambda *_: object())
    # This fixture exercises admission itself; keep backend runtime binding
    # out of scope by making PDK discovery explicitly return no PDK.
    monkeypatch.setattr(phase3, "_detect_pdk", lambda *a: None)
    monkeypatch.setattr(phase3._canonical_admission, "admit_span", lambda *a, **k: refused)
    monkeypatch.setattr(sys, "argv", ["phase3_one_shot_runner.py", str(project)])
    assert phase3.main() == 2
    assert "canonical Phase-3 admission" in capsys.readouterr().err


_EXPERT_TB = ('import cocotb\n@cocotb.test()\nasync def test_value(dut):\n'
              '    assert int(dut.q.value) == 0\n'
              '    print("PROFESSIONAL_TB PASS")\n')


def _authored_professional_project(tmp_path):
    project = _project(tmp_path / "project")
    (project / "phase2/stage1/rtl/core.v").write_text(
        "module core(input clk, input d, output reg q); "
        "always @(posedge clk) q <= d; endmodule\n")
    (project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"fields": {"top_module": "core", "top_ports": [
            {"name": "clk", "dir": "input", "width": 1},
            {"name": "d", "dir": "input", "width": 1},
            {"name": "q", "dir": "output", "width": 1}],
            "clocks": [{"name": "clk", "period_ns": 10}]}}))
    hook = project / "phase2/stage1/sim_professional/core/expert_reference_tb.py"
    hook.parent.mkdir(parents=True)
    hook.write_text(_EXPERT_TB)
    return project, hook


def _recognized_hook(hook):
    import professional_tb_gen as producer
    assert producer._load_expert_reference_tb(hook.parent) == hook.read_text()


def test_unchanged_persistent_hook_remains_duplicate(tmp_path):
    project, hook = _authored_professional_project(tmp_path)
    _recognized_hook(hook)
    first = _admit(project)
    assert first.admitted
    ledger = cra.ledger_path(project).read_bytes()
    again = _admit(project)
    assert not again.admitted and again.identity_sha256 == first.identity_sha256
    assert cra.ledger_path(project).read_bytes() == ledger


def test_changed_recognized_persistent_hook_reopens_phase2(tmp_path):
    project, hook = _authored_professional_project(tmp_path)
    initial = _admit(project)
    ledger = cra.ledger_path(project).read_bytes()
    hook.write_text(_EXPERT_TB.replace("== 0", "== 1"))
    _recognized_hook(hook)
    changed = _admit(project)
    assert changed.admitted and changed.identity_sha256 != initial.identity_sha256
    assert cra.ledger_path(project).read_bytes().startswith(ledger)
    assert len(cra.ledger_path(project).read_text().splitlines()) == 2


def test_hook_reversal_with_changed_rtl_is_a_new_combination(tmp_path):
    project, hook = _authored_professional_project(tmp_path)
    _admit(project)
    hook.write_text(_EXPERT_TB.replace("== 0", "== 1"))
    _admit(project)
    rtl = project / "phase2/stage1/rtl/core.v"
    rtl.write_text(rtl.read_text().replace("q <= d", "q <= ~d"))
    changed_rtl = _admit(project)
    assert changed_rtl.admitted
    before = cra.ledger_path(project).read_bytes()
    hook.write_text(_EXPERT_TB)
    _recognized_hook(hook)
    reversed_hook = _admit(project)
    assert reversed_hook.admitted
    assert reversed_hook.identity_sha256 != changed_rtl.identity_sha256
    assert cra.ledger_path(project).read_bytes().startswith(before)


def test_exact_hook_reversal_reuses_prior_identity_without_erasing_history(tmp_path):
    project, hook = _authored_professional_project(tmp_path)
    initial = _admit(project)
    hook.write_text(_EXPERT_TB.replace("== 0", "== 1"))
    assert _admit(project).admitted
    before = cra.ledger_path(project).read_bytes()
    hook.write_text(_EXPERT_TB)
    same = _admit(project)
    assert not same.admitted and same.identity_sha256 == initial.identity_sha256
    assert cra.ledger_path(project).read_bytes() == before


def test_generated_professional_outputs_do_not_reopen_authored_hook_identity(tmp_path):
    import professional_tb_gen as producer
    project, hook = _authored_professional_project(tmp_path)
    first = _admit(project)
    generated = producer.generate(project)
    assert generated["reference_model_tier"] == "expert_filled", generated
    assert (hook.parent / "tb_core.py").read_text() == hook.read_text()
    for name in ("results.xml", "wave.vcd", "report.json", "tb_core.py"):
        (hook.parent / name).write_text("generated output rewrite\n")
    generated = producer.generate(project)
    assert generated["reference_model_tier"] == "expert_filled"
    assert hook.read_text() == _EXPERT_TB
    same = _admit(project)
    assert not same.admitted and same.identity_sha256 == first.identity_sha256


def test_phase3_span_does_not_reopen_for_phase2_professional_hook_only(tmp_path):
    project, hook = _authored_professional_project(tmp_path)
    kw = {"container_image": "sha256:" + "c" * 64,
          "config": {"top_name": "core"},
          "program_paths": cra.canonical_program_paths(PROGRAMS)}
    first = cra.admit(project, "phase3", **kw)
    assert first.admitted
    hook.write_text(_EXPERT_TB.replace("== 0", "== 1"))
    _recognized_hook(hook)
    same = cra.admit(project, "phase3", **kw)
    assert not same.admitted and same.identity_sha256 == first.identity_sha256


_CASE_TB = """`timescale 1ns/1ps
module register_case;
  reg clk = 0;
  reg d = 0;
  wire q;
  core dut(.clk(clk), .d(d), .q(q));
  always #5 clk = ~clk;
  initial begin
    d = 1'b0;
    @(posedge clk); #1;
    if (q !== 1'b0) $fatal(1, "register mismatch");
    $finish;
  end
endmodule
"""


def _authored_case_project(tmp_path):
    project = _project(tmp_path / "project")
    (project / "input/spec.md").write_text(
        "On each rising clock edge the one-bit register captures d into q. "
        "Verify both data values.\n")
    (project / "phase2/stage1/rtl/core.v").write_text(
        "module core(input clk, input d, output reg q); "
        "always @(posedge clk) q <= d; endmodule\n")
    (project / "phase1/generated_docs/L10_TEST_CASES.json").write_text(
        json.dumps({"test_cases": [
            {"name": "register_case", "kind": "functional"}]}))
    tb = project / "phase2/stage1/sim/tb/register_case.v"
    tb.parent.mkdir(parents=True)
    tb.write_text(_CASE_TB)
    return project, tb


def _case_admit(project):
    return _admit(project, programs=cra.canonical_program_paths(PROGRAMS),
                  config={"entry": 4, "exit": 4, "top_name": "core"})


def test_authored_case_stimulus_and_assertion_changed(tmp_path):
    import testbench_gen as producer
    project, tb = _authored_case_project(tmp_path)
    assert producer.authored_oracle_preserved(tb.parent, tb.stem, {}) == tb
    initial = _case_admit(project)
    assert initial.admitted
    before = cra.ledger_path(project).read_bytes()
    assert not _case_admit(project).admitted
    assert cra.ledger_path(project).read_bytes() == before
    tb.write_text(_CASE_TB.replace("1'b0", "1'b1"))
    assert producer.authored_oracle_preserved(tb.parent, tb.stem, {}) == tb
    changed = _case_admit(project)
    assert changed.admitted
    assert changed.identity_sha256 != initial.identity_sha256
    assert cra.ledger_path(project).read_bytes().startswith(before)
    assert not _case_admit(project).admitted


def test_authored_case_reverse_with_changed_rtl(tmp_path):
    project, tb = _authored_case_project(tmp_path)
    assert _case_admit(project).admitted
    tb.write_text(_CASE_TB.replace("1'b0", "1'b1"))
    _case_admit(project)
    rtl = project / "phase2/stage1/rtl/core.v"
    rtl.write_text(rtl.read_text().replace("q <= d", "q <= ~d"))
    changed_rtl = _case_admit(project)
    assert changed_rtl.admitted
    before = cra.ledger_path(project).read_bytes()
    tb.write_text(_CASE_TB)
    reversed_case = _case_admit(project)
    assert reversed_case.admitted
    assert reversed_case.identity_sha256 != changed_rtl.identity_sha256
    assert cra.ledger_path(project).read_bytes().startswith(before)


def test_authored_case_add_remove_and_exact_reversal(tmp_path):
    project, tb = _authored_case_project(tmp_path)
    initial = _case_admit(project)
    extra = tb.with_name("second_case.sv")
    extra.write_text(_CASE_TB.replace("register_case", "second_case"))
    assert _case_admit(project).admitted
    # Removal must change identity even with another authored TB remaining.
    tb.unlink()
    assert _case_admit(project).admitted
    extra.unlink()
    assert _case_admit(project).admitted
    tb.write_text(_CASE_TB)
    before = cra.ledger_path(project).read_bytes()
    restored = _case_admit(project)
    assert not restored.admitted
    assert restored.identity_sha256 == initial.identity_sha256
    assert cra.ledger_path(project).read_bytes() == before


def test_authored_case_generated_refresh_and_reports_remain_duplicate(tmp_path):
    import testbench_gen as producer
    project, tb = _authored_case_project(tmp_path)
    initial = _case_admit(project)
    before = cra.ledger_path(project).read_bytes()
    for marker in (producer.ORACLE_NONE_MARKER, producer.ORACLE_GENERATED_MARKER):
        generated = tb.with_name("generated_case.v")
        generated.write_text("// " + marker + "\n" +
                             _CASE_TB.replace("register_case", "generated_case"))
        assert producer.authored_oracle_preserved(
            generated.parent, generated.stem, {}) is None
        assert producer.is_unit_tb(generated)
        assert not _case_admit(project).admitted
        generated.write_text(generated.read_text().replace("1'b0", "1'b1"))
        assert not _case_admit(project).admitted
        generated.unlink()
    for name in ("results.xml", "wave.vcd", "report.json"):
        (tb.parent / name).write_text("generated output refresh\n")
    same = _case_admit(project)
    assert not same.admitted and same.identity_sha256 == initial.identity_sha256
    assert cra.ledger_path(project).read_bytes() == before


def test_authored_case_phase3_remains_duplicate(tmp_path):
    project, tb = _authored_case_project(tmp_path)
    kw = {"container_image": "sha256:" + "c" * 64,
          "config": {}, "program_paths": cra.canonical_program_paths(PROGRAMS)}
    initial = cra.admit(project, "phase3", **kw)
    tb.write_text(_CASE_TB.replace("1'b0", "1'b1"))
    same = cra.admit(project, "phase3", **kw)
    assert not same.admitted and same.identity_sha256 == initial.identity_sha256


def _full_stack_oracle(project, name="chip_top", generated=False):
    path = project / "phase2/stage1/sim_full_stack" / f"tb_{name}_oracle.v"
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = "// Auto-generated by oracle_tb_gen (#439)\n" if generated else ""
    path.write_text(prefix + "module tb; initial begin if (1 !== 1) $fatal; $finish; end endmodule\n")
    return path


def test_full_stack_oracle_author_handoff_reopens_then_deduplicates(tmp_path):
    project = _project(tmp_path / "proj")
    first = _admit(project)
    assert first.admitted
    oracle = _full_stack_oracle(project)
    current = _admit(project)
    assert current.admitted and current.identity_sha256 != first.identity_sha256
    assert not _admit(project).admitted
    oracle.touch()
    (oracle.parent / "results.json").write_text('{"changed": true}\n')
    assert not _admit(project).admitted
    oracle.write_text(oracle.read_text().replace("1 !== 1", "0 !== 1"))
    repaired = _admit(project)
    assert repaired.admitted and repaired.identity_sha256 != current.identity_sha256
    oracle.unlink()
    removed = _admit(project)
    assert removed.identity_sha256 != repaired.identity_sha256
    # This is the already-seen initial input, so removal cannot buy another run.
    assert removed.identity_sha256 == first.identity_sha256 and not removed.admitted


def test_full_stack_oracle_identity_follows_only_the_normal_selected_source(tmp_path):
    project = _project(tmp_path / "proj")
    selected = _full_stack_oracle(project, "alpha")
    later = _full_stack_oracle(project, "zeta")
    first = _admit(project)
    assert first.admitted
    later.write_text(later.read_text().replace("1 !== 1", "0 !== 1"))
    assert not _admit(project).admitted
    selected.write_text(selected.read_text().replace("1 !== 1", "0 !== 1"))
    assert _admit(project).admitted
    selected.unlink()
    assert _admit(project).admitted  # zeta is now the actual selected source


def test_full_stack_oracle_generated_outputs_do_not_buy_admission(tmp_path):
    project = _project(tmp_path / "proj")
    first = _admit(project)
    oracle = _full_stack_oracle(project, generated=True)
    assert not _admit(project).admitted
    oracle.write_text(oracle.read_text().replace("oracle_tb_gen (#439)", "arith_oracle_tb_gen (#745)"))
    assert not _admit(project).admitted
    oracle.write_text(oracle.read_text() + "// regenerated native report token\n")
    assert not _admit(project).admitted
    oracle.write_text("module tb; initial begin if (1 !== 1) $fatal; $finish; end endmodule\n")
    assert _admit(project).admitted


def test_full_stack_oracle_is_not_a_phase3_input(tmp_path):
    project = _project(tmp_path / "proj")
    kwargs = dict(container_image="sha256:" + "a"*64, config={"top_name": "chip_top"},
                  program_paths=[PROGRAMS / "canonical_run_admission.py"])
    first = cra.admit(project, "phase3", **kwargs)
    _full_stack_oracle(project)
    second = cra.admit(project, "phase3", **kwargs)
    assert first.admitted and not second.admitted
    assert first.identity_sha256 == second.identity_sha256
