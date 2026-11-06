#!/usr/bin/env python3
"""Regression tests for the plain-Phase-1 behavioral-FSM flow-back.

The semantic recognizer is tested in its family suite.  These tests pin the
production runner boundary: plain prose can reach that recognizer, while an
incomplete spec, ambiguous top, non-behavioral registry result, or authored RTL
still DEFERs without touching the project.
"""
import json
from pathlib import Path
import shutil
import sys

import pytest


HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as runner  # noqa: E402
import canonical_primitive_synth as canonical_primitive  # noqa: E402

# BIND TO WHAT PRODUCTION CONSULTS, NOT TO WHAT THIS FILE IMPORTED.
# `design_one_shot_runner` does `import rtl_provenance as _rtl_prov` at its
# own import time, and `tests/test_rtl_provenance.py` REPLACES the
# `sys.modules["rtl_provenance"]` entry with a freshly-executed module
# object. Whenever that file is imported AFTER the runner and BEFORE this
# one -- e.g. `pytest test_902_sim_toolchain_provenance.py
# test_rtl_provenance.py test_phase1_behavioral_fsm_flowback.py`, a
# legitimate order -- the name bound above is a DIFFERENT object from the
# one the runner calls. Tests that monkeypatch the module then patch
# something production never consults: the spy is never called, the
# production path still returns PASS, and the test fails on its own
# counter while the code under test is correct. The full alphabetical
# suite happens to import this file first, which is the only reason that
# was invisible.
from _prose_handoff_assertions import assert_program_candidate  # noqa: E402


COMPLETE_DIRECTIONAL_FALL = (
    HERE / "fixtures" / "real_benchmark" /
    "directional_bump_fall_moore_prompt.md").read_text()

CANONICAL_PULSE = (
    "Module name:\n    pulse_detect\n"
    "Pulse detection: when data_in changes from 0 to 1 to 0 this is a pulse.\n"
    "Input ports:\n clk: Clock.\n rst_n: Reset.\n"
    " data_in: One-bit input.\n"
    "Output ports:\n data_out: pulse indicator.\n")

_ACCOUNTED_OPERATOR_SPEC = """
Implement a module named TopModule.
 - input  a
 - input  b
 - output q

The module should implement the function shown in the Karnaugh map below.

       a
  b   0   1
  0 | 0 | 1 |
  1 | 1 | 0 |
"""


_PULSE_UNACCOUNTED_SPANS = [
    (0, 101), (102, 127), (129, 142), (144, 167), (168, 209),
]


def _project(tmp_path, text=COMPLETE_DIRECTIONAL_FALL, source="input_doc"):
    source_dir = tmp_path / "phase1" / source
    source_dir.mkdir(parents=True)
    (source_dir / "design.md").write_text(text)
    return tmp_path


def _canonical_project(tmp_path):
    """Use the canonical consumer's generated-L-doc source, not free prose."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L2_FRS.json").write_text(json.dumps({
        "description": "Module name: pulse_detect. Pulse detection: data_in changes from 0 to 1 to 0.",
        "interface": "clk (input), rst_n (input), data_in (input), data_out (output)",
    }))
    return tmp_path


def _publication_project(tmp_path):
    """A consumed typed arithmetic contract reaches the same step transaction."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "TopModule", "frs_sections": [{"content":
            "serial-parallel multiplier: p = (x * y) mod 2^N; synchronous active-high reset"}],
    }))
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "TopModule",
        "top_ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "rst", "direction": "input", "width": 1},
            {"name": "x", "direction": "input", "width": "size-1:0",
             "width_symbolic": "size-1:0", "msb": "size-1", "lsb": "0"},
            {"name": "y", "direction": "input", "width": 1},
            {"name": "p", "direction": "output", "width": 1},
        ],
    }))
    return tmp_path


def _assert_gather_refusal(project, reason, finding=None):
    gathered = runner._gather_phase1_plain_spec_text(project)
    if isinstance(gathered, tuple):
        text, sources = gathered
        refusal = None
    else:
        text, sources, refusal = (
            gathered.text, gathered.sources, gathered.refusal)
    assert text == ""
    assert tuple(sources) == ()
    actual_reason = (refusal or {}).get("reason", "SILENT_EMPTY")
    assert actual_reason == reason
    if finding is not None:
        actual_finding = (refusal or {}).get("finding", "SILENT_EMPTY")
        assert actual_finding == finding
    return gathered


def test_step_rtl_gen_calls_phase1_flowback_before_class_fallback(tmp_path):
    project = _project(tmp_path)

    result = runner.step_rtl_gen(project, "deliberately_unregistered_class")

    assert_program_candidate(result, COMPLETE_DIRECTIONAL_FALL)
    assert result.extras['deterministic_generator'] == 'spec_artifact_registry'
    assert Path(result.output_files[0]).is_file()


def test_unreadable_project_directory_is_named_blocked_without_writes(
        tmp_path):
    project = _project(tmp_path)
    phase2 = project / "phase2"
    stage1 = phase2 / "stage1"
    stage1.mkdir(parents=True)
    sentinel = stage1 / "sentinel.txt"
    sentinel.write_text("original\n")
    phase2.chmod(0o000)
    try:
        result = runner.step_rtl_gen(
            project, "digital_arithmetic_primitive")

        assert result.status == "NOT_MEASURED"
        assert result.extras["output_refusal"]["reason"] == (
            "PROJECT_SNAPSHOT_OPEN_REFUSED")
        assert phase2.stat().st_mode & 0o777 == 0o000
        assert not any(p.name.startswith(".vibeic-rtl-txn.")
                       for p in project.iterdir())
    finally:
        phase2.chmod(0o755)
    assert sentinel.read_text() == "original\n"
    assert sorted(p.name for p in stage1.iterdir()) == ["sentinel.txt"]


def test_finalize_on_an_already_closed_transaction_is_a_silent_no_op(
        tmp_path):
    """The `if self.closed` guard is load-bearing on the no-delta path.

    A run with no changed tops builds a pre-closed transaction whose
    container_fd is -1. Without the guard, finalize() would _drain() on fd -1,
    the retry loop would turn EBADF into a string, and every idempotent run of
    step_rtl_gen would gain a bogus cleanup warning while still reporting PASS.
    That branch is hit on ordinary no-change runs; deleting the guard left the
    whole suite green.
    """
    project = _publication_project(tmp_path)
    first = runner.step_rtl_gen(project, "digital_arithmetic_primitive")
    assert first.status == "PASS"

    second = runner.step_rtl_gen(project, "digital_arithmetic_primitive")

    assert second.status == "PASS"
    assert "transaction_cleanup_warning" not in second.extras


def test_stage_temp_cleanup_failure_rolls_back_before_finalize(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    real_cleanup = runner.tempfile.TemporaryDirectory.cleanup
    injected = False

    def _fail_step_stage_cleanup_once(temporary):
        nonlocal injected
        if "vibeic-rtl-step-" in temporary.name and not injected:
            injected = True
            raise OSError("injected isolated-stage cleanup failure")
        return real_cleanup(temporary)

    monkeypatch.setattr(
        runner.tempfile.TemporaryDirectory, "cleanup",
        _fail_step_stage_cleanup_once)

    result = runner.step_rtl_gen(
        project, "deliberately_unregistered_class")

    assert injected
    assert result.status == "NOT_MEASURED"
    assert result.extras["output_refusal"]["reason"] == (
        "RTL_TRANSACTION_STAGE_CLEANUP_REFUSED")
    assert not (project / "phase2").exists()
    assert not any(p.name.startswith(".vibeic-rtl-txn.")
                   for p in project.iterdir())


def test_step_preflight_blocks_symlink_before_earlier_canonical_writer(
        tmp_path):
    """The canonical hook precedes behavioral flow-back in production order."""
    project = _project(tmp_path / "project")
    external = tmp_path / "external_canonical_generated.txt"
    external.write_text(CANONICAL_PULSE)
    source = project / "phase1" / "input_doc" / "design.md"
    source.unlink()
    source.symlink_to(external)
    before = external.read_bytes()

    result = runner.step_rtl_gen(project, "deliberately_unregistered_class")

    assert result.status == "NOT_MEASURED"
    assert result.extras["finding"] == (
        "PHASE1_OPERATOR_PROSE_PROVENANCE_REFUSED")
    assert result.extras["source_refusal"]["reason"] == "SOURCE_OUT_OF_ROOT"
    assert result.extras["write_performed"] is False
    assert external.read_bytes() == before
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_valid_canonical_dispatch_reuses_one_immutable_operator_read(
        tmp_path, monkeypatch):
    project = _project(_canonical_project(tmp_path), _ACCOUNTED_OPERATOR_SPEC)
    source = project / "phase1" / "input_doc" / "design.md"
    original_read_text = Path.read_text
    source_reads = 0

    def _read_text(path, *args, **kwargs):
        nonlocal source_reads
        if (path.name == source.name
                and path.parent.name == source.parent.name
                and path.parent.parent.name == source.parent.parent.name):
            source_reads += 1
            if source_reads > 1:
                raise OSError("operator prose was read after strict preflight")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read_text)
    result = runner.step_rtl_gen(project, "deliberately_unregistered_class")

    assert result.status == "PASS"
    assert result.extras["deterministic_generator"] == (
        "canonical_primitive_synth")
    assert source_reads == 1
    assert (project / "phase2" / "stage1" / "rtl" /
            "pulse_detect.v").is_file()


def test_canonical_writer_refuses_root_replaced_after_emit_before_write(
        tmp_path, monkeypatch):
    project = _canonical_project(tmp_path / "project")
    displaced = tmp_path / "project.displaced"
    real_emit = canonical_primitive.emit_rtl

    def _emit_then_replace(shape, desc_text=""):
        # follows canonical_primitive_synth.emit_rtl's call shape, which now
        # carries the description a CONTRACT-composed shape is composed from;
        # the assertions below are unchanged.
        rtl = real_emit(shape, desc_text)
        project.rename(displaced)
        project.mkdir()
        return rtl

    monkeypatch.setattr(canonical_primitive, "emit_rtl", _emit_then_replace)

    result = runner.step_rtl_gen(
        project, "deliberately_unregistered_class")

    assert result.status == "NOT_MEASURED"
    assert result.extras["output_refusal"]["reason"] == (
        "PROJECT_BOUNDARY_REPLACED_DURING_PUBLICATION")
    assert result.extras["write_performed"] is False
    assert result.output_files == []
    assert not list(project.rglob("*"))
    assert not (displaced / "phase2").exists()


def test_symlinked_phase1_ancestor_cannot_relabel_external_l9_as_program_first(
        tmp_path):
    project = _project(tmp_path / "project")
    shutil.rmtree(project / "phase1")
    generated_root = tmp_path / "external_generated_root"
    input_doc = generated_root / "input_doc"
    input_doc.mkdir(parents=True)
    (input_doc / "L9_AI_GENERATED.md").write_text(COMPLETE_DIRECTIONAL_FALL)
    (project / "phase1").symlink_to(generated_root, target_is_directory=True)

    _assert_gather_refusal(project, "SOURCE_ANCESTOR_SYMLINK")
    result = runner.step_rtl_gen(project, "deliberately_unregistered_class")
    assert result.status == "NOT_MEASURED"
    assert result.extras["finding"] == (
        "PHASE1_OPERATOR_PROSE_PROVENANCE_REFUSED")
    assert result.extras["source_refusal"]["reason"] == (
        "SOURCE_ANCESTOR_SYMLINK")
    assert result.extras["write_performed"] is False
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_symlinked_input_root_cannot_cross_the_source_boundary(tmp_path):
    project = _project(tmp_path / "project")
    shutil.rmtree(project / "phase1" / "input_doc")
    external = tmp_path / "external_input_doc"
    external.mkdir()
    (external / "design.md").write_text(COMPLETE_DIRECTIONAL_FALL)
    (project / "phase1" / "input_doc").symlink_to(
        external, target_is_directory=True)

    _assert_gather_refusal(project, "SOURCE_ANCESTOR_SYMLINK")


def test_symlinked_descendant_invalidates_the_whole_source_tree(tmp_path):
    project = _project(tmp_path / "project")
    external = tmp_path / "external_descendant"
    external.mkdir()
    (external / "L9_AI_GENERATED.md").write_text(COMPLETE_DIRECTIONAL_FALL)
    (project / "phase1" / "input_doc" / "nested").symlink_to(
        external, target_is_directory=True)

    _assert_gather_refusal(project, "SOURCE_OUT_OF_ROOT")


def test_invalid_utf8_operator_prose_is_named_parse_refusal(tmp_path):
    project = _project(tmp_path)
    source = project / "phase1" / "input_doc" / "design.md"
    source.write_bytes(b"module TopModule(\n\xff\xfe\n")

    _assert_gather_refusal(
        project, "SOURCE_TEXT_PARSE_FAILED",
        "PHASE1_OPERATOR_PROSE_PARSE_REFUSED")
    result = runner.step_rtl_gen(project, "deliberately_unregistered_class")
    assert result.status == "NOT_MEASURED"
    assert result.extras["finding"] == "PHASE1_OPERATOR_PROSE_PARSE_REFUSED"
    assert result.extras["source_refusal"]["reason"] == (
        "SOURCE_TEXT_PARSE_FAILED")
    assert result.extras["write_performed"] is False
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_source_refusal_is_repeatable_and_preserves_existing_rtl(tmp_path):
    project = _project(tmp_path)
    source = project / "phase1" / "input_doc" / "design.md"
    source.write_bytes(b"module TopModule(\n\xff\xfe\n")
    authored = project / "phase2" / "stage1" / "rtl" / "authored.sv"
    authored.parent.mkdir(parents=True)
    authored_bytes = b"module authored; // foreign work\nendmodule\n"
    authored.write_bytes(authored_bytes)
    before_entries = sorted(
        str(path.relative_to(project)) for path in project.rglob("*")
        if "__pycache__" not in path.parts)

    first = runner.step_rtl_gen(project, "deliberately_unregistered_class")
    second = runner.step_rtl_gen(project, "deliberately_unregistered_class")

    assert first.status == second.status == "NOT_MEASURED"
    assert first.extras["source_refusal"] == second.extras["source_refusal"]
    assert first.extras["write_performed"] is False
    assert second.extras["write_performed"] is False
    assert authored.read_bytes() == authored_bytes
    after_entries = sorted(
        str(path.relative_to(project)) for path in project.rglob("*")
        if "__pycache__" not in path.parts)
    assert after_entries == before_entries


def test_operator_prose_read_failure_is_named_and_retained(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    source = project / "phase1" / "input_doc" / "design.md"
    original_read_text = Path.read_text

    def _read_text(path, *args, **kwargs):
        if (path.name == source.name
                and path.parent.name == source.parent.name
                and path.parent.parent.name == source.parent.parent.name):
            raise OSError("injected operator-prose read failure")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read_text)
    _assert_gather_refusal(
        project, "SOURCE_READ_FAILED",
        "PHASE1_OPERATOR_PROSE_READ_REFUSED")
    result = runner.step_rtl_gen(project, "deliberately_unregistered_class")
    assert result.status == "NOT_MEASURED"
    assert result.extras["finding"] == "PHASE1_OPERATOR_PROSE_READ_REFUSED"
    assert result.extras["source_refusal"]["reason"] == "SOURCE_READ_FAILED"
    assert result.extras["write_performed"] is False
    assert not (project / "phase2" / "stage1" / "rtl").exists()
