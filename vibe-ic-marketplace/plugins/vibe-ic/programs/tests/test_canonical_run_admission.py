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
import ai_signed_judgement  # noqa: E402
import design_input_digest as did  # noqa: E402
from _delivery_declaration import declare_delivery as _declare  # noqa: E402
from _ai_judgement_fixture import sign as _sign_judgement  # noqa: E402


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


def _step1_review_project(root: Path) -> Path:
    project = _project(root)
    fallback = project / "phase2/stage1/fallback_skill.md"
    fallback.write_text("spec-to-rtl\n")
    assert ai_signed_judgement.check(project, "1")[0] is False
    return project


def test_current_verified_step1_judgement_reopens_phase2_once(tmp_path):
    project = _step1_review_project(tmp_path / "proj")
    first = _admit(project)
    assert first.admitted
    assert "current_consumer_evidence_bindings" not in first.identity

    _sign_judgement(project, "1")
    accepted, detail = ai_signed_judgement.check(project, "1")
    assert accepted and detail.startswith(
        "signed judgement bound to evidence sha256:")
    current = _admit(project)
    assert current.admitted and current.identity_sha256 != first.identity_sha256
    binding = current.identity["current_consumer_evidence_bindings"][
        "step1_signed_judgement"]
    receipt = project / binding["receipt_path"]
    assert binding["receipt_sha256"] == cra._sha256_bytes(receipt.read_bytes())
    assert binding["evidence_sha256"] == ai_signed_judgement.evidence_sha256(
        project, "1")
    assert binding["subject_count"] == len(binding["subjects"])
    assert {row["path"] for row in binding["subjects"]} == {
        path.relative_to(project).as_posix()
        for path in ai_signed_judgement.evidence(project, "1")}

    unchanged = _admit(project)
    assert not unchanged.admitted
    assert unchanged.reason == "DUPLICATE_NO_NEW_EVIDENCE"
    assert unchanged.identity_sha256 == current.identity_sha256

    unrelated = project / "reports/unrelated.json"
    unrelated.parent.mkdir(exist_ok=True)
    unrelated.write_text('{"changed": true}\n')
    report_only = _admit(project)
    assert not report_only.admitted
    assert report_only.identity_sha256 == current.identity_sha256


def test_invalid_step1_judgements_cannot_reopen_phase2(tmp_path):
    mutations = {
        "missing": None,
        "wrong-evidence": {"evidence_sha256": "0" * 64},
        "wrong-step": {"step_id": "3"},
        "unsigned": {"signed_by": ""},
        "malformed": "not-json",
        "foreign": {"signed_by": "foreign", "evidence_sha256": "f" * 64},
        "stale": {"evidence_sha256": "1" * 64},
    }
    for name, mutation in mutations.items():
        project = _step1_review_project(tmp_path / name)
        first = _admit(project)
        assert first.admitted
        receipt = project / "reports/audit/ai_judgements/1.json"
        if mutation is not None:
            _sign_judgement(project, "1")
            if mutation == "not-json":
                receipt.write_text("not-json\n")
            else:
                document = json.loads(receipt.read_text())
                document.update(mutation)
                receipt.write_text(json.dumps(document) + "\n")
        accepted, _detail = ai_signed_judgement.check(project, "1")
        assert not accepted, name
        refused = _admit(project)
        assert not refused.admitted, name
        assert refused.reason == "DUPLICATE_NO_NEW_EVIDENCE", name
        assert refused.identity_sha256 == first.identity_sha256, name
        if name == "stale":
            _sign_judgement(project, "1")
            current = _admit(project)
            assert current.admitted
            assert current.identity_sha256 != first.identity_sha256


def test_step1_binding_tracks_variable_complete_subject_population(tmp_path):
    ordinary = _step1_review_project(tmp_path / "ordinary")
    expanded = _step1_review_project(tmp_path / "expanded")
    extra = expanded / "phase2/stage1/rtl/helper.sv"
    extra.write_text("module helper(input logic a, output logic y); assign y = a; endmodule\n")
    _sign_judgement(ordinary, "1")
    _sign_judgement(expanded, "1")

    ordinary_binding = _admit(ordinary).identity[
        "current_consumer_evidence_bindings"]["step1_signed_judgement"]
    expanded_binding = _admit(expanded).identity[
        "current_consumer_evidence_bindings"]["step1_signed_judgement"]
    assert ordinary_binding["subject_count"] == len(
        ai_signed_judgement.evidence(ordinary, "1"))
    assert expanded_binding["subject_count"] == len(
        ai_signed_judgement.evidence(expanded, "1"))
    assert expanded_binding["subject_count"] == ordinary_binding["subject_count"] + 1
    assert "phase2/stage1/rtl/helper.sv" in {
        row["path"] for row in expanded_binding["subjects"]}
    assert expanded_binding["evidence_sha256"] != ordinary_binding["evidence_sha256"]


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
    # main() also installs a retained-tree callback on this shared module.
    # Its closure belongs to the CLI fixture, not a later publisher invocation.
    import _progress_run as progress
    monkeypatch.setattr(progress, 'run', progress.run)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    project = _project(tmp_path / "proj")
    refused = cra.Admission(False, "DUPLICATE_NO_NEW_EVIDENCE", "x", {}, "control")

    design = _load_runner("design_one_shot_runner.py", "_test_direct_phase2")
    monkeypatch.setattr(design._runner_lock, "acquire_or_reenter", lambda *_: object())
    monkeypatch.setattr(design._canonical_admission, "admit_span", lambda *a, **k: refused)
    monkeypatch.setattr(sys, "argv", ["design_one_shot_runner.py", str(project)])
    assert design.main() == 2
    assert "canonical Phase-2 admission" in capsys.readouterr().err
    # Cleanup must not weaken the active invocation's source guard.
    import pytest
    import runtime_program_tree
    with pytest.raises(runtime_program_tree.RuntimeTreeError,
                       match="LIVE_PLUGIN_PATH_AFTER_RETENTION"):
        design._RUNTIME_PROGRAM_TREE.verify_command(
            [sys.executable, str(PROGRAMS / 'serial_parallel_mul_synth.py')])

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


def test_phase2_local_runtime_condition_reopens_once(tmp_path, monkeypatch):
    import librelane_contract
    project = _project(tmp_path / 'proj')
    monkeypatch.setenv(librelane_contract.LOCAL_ATTESTATION_ENV, '/host/receipt')
    condition = {'auto_remove': False, 'network_mode': 'none', 'memory': 1024, 'memory_swap': 1024}
    monkeypatch.setattr(librelane_contract, 'local_image_attestation', lambda: condition.copy())
    args = (project, 'phase2', PROGRAMS, '')
    config = {'top_name': 'chip_top'}
    first = cra.admit_span(*args, config)
    assert first.admitted
    assert not cra.admit_span(*args, config).admitted
    condition['auto_remove'] = True
    changed = cra.admit_span(*args, config)
    assert changed.admitted
    assert not cra.admit_span(*args, config).admitted


def test_phase2_unattested_local_runtime_is_refused(tmp_path, monkeypatch):
    import librelane_contract
    project = _project(tmp_path / 'proj')
    monkeypatch.setenv(librelane_contract.LOCAL_ATTESTATION_ENV, '/host/bad-receipt')
    def reject():
        raise librelane_contract.Refusal('LL_LOCAL_IMAGE_UNATTESTED', 'mismatched CID')
    monkeypatch.setattr(librelane_contract, 'local_image_attestation', reject)
    result = cra.admit_span(project, 'phase2', PROGRAMS, '', {'top_name': 'chip_top'})
    assert not result.admitted
    assert result.reason == 'LOCAL_RUNTIME_UNATTESTED'
    assert not cra.ledger_path(project).exists()


def test_current_reset_judgement_reopens_only_once_and_stale_is_ignored(tmp_path, monkeypatch):
    import ai_signed_judgement as judgement
    project = _project(tmp_path / 'proj')
    receipt = project / 'reports/audit/ai_judgements/3.json'
    receipt.parent.mkdir(parents=True)
    binding = {'evidence_sha256': 'a' * 64, 'netlist_sha256': 'b' * 64}
    monkeypatch.setattr(judgement, 'reset_role_request', lambda _: binding.copy())
    monkeypatch.setattr(judgement, 'check', lambda *_: (True, 'current'))
    first = _admit(project)
    receipt.write_text(json.dumps(binding))
    second = _admit(project)
    assert first.admitted and second.admitted
    assert 'reset_role_signed_judgement' in second.identity['current_consumer_evidence_bindings']
    assert not _admit(project).admitted
    receipt.write_text(json.dumps({**binding, 'netlist_sha256': 'c' * 64}))
    assert not _admit(project).admitted
    monkeypatch.setattr(judgement, 'check', lambda *_: (False, 'unresolved'))
    receipt.write_text(json.dumps(binding))
    assert not _admit(project).admitted


def test_flow109_runtime_projection_source_reopens_only_once(tmp_path, monkeypatch):
    import shutil
    project = _project(tmp_path / 'project')
    programs = tmp_path / 'plugin/programs'
    for source in {*cra.canonical_program_paths(PROGRAMS), PROGRAMS / 'flow109.py'}:
        target = programs.parent / source.relative_to(PROGRAMS.parent)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    monkeypatch.delenv('VIBEIC_LIBRELANE_LOCAL_ATTESTATION', raising=False)
    monkeypatch.setattr(cra, 'image_identity', lambda _: 'sha256:' + 'a' * 64)
    args = (project, 'phase2', programs, '')
    config = {'entry_step': '2', 'exit_step': '2'}
    first = cra.admit_span(*args, config)
    assert first.admitted
    assert not cra.admit_span(*args, config).admitted
    source = programs / 'flow109.py'
    original = source.read_text()
    needle = '    if "requested_step" in window and isinstance(runtime_tool_uses, list):'
    assert needle in original
    source.write_text(original.replace(needle, needle.replace('if ', 'if False and ', 1)))
    changed = cra.admit_span(*args, config)
    assert changed.reason == 'ADMITTED'
    assert changed.identity_sha256 != first.identity_sha256
    assert not cra.admit_span(*args, config).admitted
    reports = project / 'reports'
    reports.mkdir(exist_ok=True)
    (reports / 'phase2.json').write_text('{"status":"NOT_MEASURED"}\n')
    assert not cra.admit_span(*args, config).admitted
    source.write_text(original)
    restored = cra.admit_span(*args, config)
    assert restored.identity_sha256 == first.identity_sha256
    assert restored.reason == 'DUPLICATE_NO_NEW_EVIDENCE'
