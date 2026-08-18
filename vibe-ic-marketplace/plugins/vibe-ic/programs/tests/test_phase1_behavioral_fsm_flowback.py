#!/usr/bin/env python3
"""Regression tests for the plain-Phase-1 behavioral-FSM flow-back.

The semantic recognizer is tested in its family suite.  These tests pin the
production runner boundary: plain prose can reach that recognizer, while an
incomplete spec, ambiguous top, non-behavioral registry result, or authored RTL
still DEFERs without touching the project.
"""
import errno
import json
import os
from pathlib import Path
import shutil
import sys

import pytest


HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as runner  # noqa: E402
import canonical_primitive_synth as canonical_primitive  # noqa: E402
import spec_artifact_registry as registry  # noqa: E402
import rtl_provenance  # noqa: E402

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
_PROD_RTL_PROV = runner._rtl_prov
from _hostpaths import require_repo  # noqa: E402


COMPLETE_DIRECTIONAL_FALL = (
    HERE / "fixtures" / "real_benchmark" /
    "directional_bump_fall_moore_prompt.md").read_text()

CANONICAL_PULSE = (
    "Module name:\n    pulse_detect\n"
    "Pulse detection: when data_in changes from 0 to 1 to 0 this is a pulse.\n"
    "Input ports:\n clk: Clock.\n rst_n: Reset.\n"
    " data_in: One-bit input.\n"
    "Output ports:\n data_out: pulse indicator.\n")


@pytest.fixture(autouse=True)
def _isolated_runner_session(monkeypatch):
    """Each unit case models one runner process and leaves no atexit target."""
    monkeypatch.setattr(runner, "_RTL_SESSION_OWNED", False)
    monkeypatch.setattr(runner, "_RTL_SESSION_PROJECT", None)


def _project(tmp_path, text=COMPLETE_DIRECTIONAL_FALL, source="input_doc"):
    source_dir = tmp_path / "phase1" / source
    source_dir.mkdir(parents=True)
    (source_dir / "design.md").write_text(text)
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


def _assert_flowback_refusal(project, reason, finding=None):
    result = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    actual_status = result.status if result is not None else "SILENT_NONE"
    assert actual_status == "BLOCKED"
    assert result.extras["source_provenance"] == "refused"
    assert result.extras["source_refusal"]["reason"] == reason
    assert result.extras["write_performed"] is False
    if finding is not None:
        assert result.extras["finding"] == finding
    assert not (project / "phase2" / "stage1" / "rtl").exists()
    return result


def _read_only_transaction_pair(tmp_path, nested=False):
    """Return held original/stage trees whose changed top preserves 0555."""
    project = tmp_path / "project"
    top = project / "phase2"
    target_dir = top
    if nested:
        target_dir = top / "locked" / "deeper"
    target_dir.mkdir(parents=True)
    (target_dir / "state.txt").write_text("old canonical\n")
    if nested:
        (top / "locked" / "deeper").chmod(0o555)
        (top / "locked").chmod(0o555)
    top.chmod(0o555)

    binding = runner._Phase1ProjectBinding.open(project)
    stage_parent = tmp_path / "stage"
    stage_parent.mkdir()
    stage_project = stage_parent / "project"
    baseline = runner._phase1_snapshot_to_stage(binding, stage_project)
    stage_binding = runner._Phase1ProjectBinding.open(stage_project)

    stage_top = stage_project / "phase2"
    stage_target = stage_top
    stage_top.chmod(0o755)
    if nested:
        (stage_top / "locked").chmod(0o755)
        stage_target = stage_top / "locked" / "deeper"
        stage_target.chmod(0o755)
    (stage_target / "state.txt").write_text("new staged\n")
    (stage_target / "added.txt").write_text("new file\n")
    if nested:
        stage_target.chmod(0o555)
        (stage_top / "locked").chmod(0o555)
    stage_top.chmod(0o555)
    final = runner._phase1_tree_manifest_fd(
        stage_binding.project_fd, project)
    return project, binding, stage_binding, baseline, final


def _unlock_test_tree(*roots):
    for root in roots:
        if not root.exists() or root.is_symlink():
            continue
        for path in [root, *root.rglob("*")]:
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o755)


@pytest.mark.parametrize("source", ["input_doc", "input_prompt"])
def test_plain_phase1_prose_emits_behavioral_fsm(tmp_path, source):
    project = _project(tmp_path, source=source)

    result = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert result is not None and result.status == "PASS"
    assert result.extras == {
        "deterministic_generator": "spec_artifact_registry",
        "artifact_type": "behavioral_fsm",
        "module": "TopModule",
        "program_first": True,
        "spec_source": "phase1_plain_prose",
        "spec_sources": [f"phase1/{source}/design.md"],
        "rtl_provenance": "generated",
    }
    out = project / "phase2" / "stage1" / "rtl" / "TopModule.v"
    assert result.output_files == [str(out)]
    rtl = out.read_text()
    assert "module TopModule(" in rtl
    assert "S_WALK_LEFT" in rtl and "S_FALL_RIGHT" in rtl
    assert "always @(posedge clk or posedge areset)" in rtl


def test_step_rtl_gen_calls_phase1_flowback_before_class_fallback(tmp_path):
    project = _project(tmp_path)

    result = runner.step_rtl_gen(project, "deliberately_unregistered_class")

    assert result.status == "PASS"
    assert result.extras["artifact_type"] == "behavioral_fsm"
    assert (project / "phase2" / "stage1" / "rtl" / "TopModule.v").is_file()


def test_step_behavioral_classify_is_bound_across_live_root_swap_restore(
        tmp_path, monkeypatch):
    """An ABA live-root swap cannot steer classify or receive flow-back writes."""
    project = _project(tmp_path / "project")
    displaced = tmp_path / "project.displaced"
    seen = []
    real_classify = _PROD_RTL_PROV.classify

    def _classify_while_live_root_is_replaced(candidate):
        candidate = Path(candidate)
        seen.append(candidate)
        assert candidate != project
        project.rename(displaced)
        foreign_rtl = project / "phase2" / "stage1" / "rtl"
        foreign_rtl.mkdir(parents=True)
        (foreign_rtl / "foreign.v").write_text(
            "module foreign; endmodule\n")
        try:
            return real_classify(candidate)
        finally:
            shutil.rmtree(project)
            displaced.rename(project)

    monkeypatch.setattr(
        _PROD_RTL_PROV, "classify", _classify_while_live_root_is_replaced)

    result = runner.step_rtl_gen(
        project, "deliberately_unregistered_class")

    assert result.status == "PASS"
    assert len(seen) == 1
    assert (project / "phase2" / "stage1" / "rtl" /
            "TopModule.v").is_file()
    assert not (project / "phase2" / "stage1" / "rtl" /
                "foreign.v").exists()
    assert not displaced.exists()


@pytest.mark.parametrize("nested", [False, True])
def test_held_transaction_finalizes_changed_0555_tree_without_hidden_residue(
        tmp_path, nested):
    pair = _read_only_transaction_pair(tmp_path, nested=nested)
    project, binding, stage_binding, baseline, final = pair
    try:
        transaction = runner._phase1_commit_staged_tree(
            binding, stage_binding, baseline, final)
        binding.require_current()
        transaction.finalize()

        target = project / "phase2"
        if nested:
            target /= "locked/deeper"
        assert (target / "state.txt").read_text() == "new staged\n"
        assert (target / "added.txt").read_text() == "new file\n"
        assert (project / "phase2").stat().st_mode & 0o777 == 0o555
        if nested:
            assert target.stat().st_mode & 0o777 == 0o555
        assert not any(p.name.startswith(".vibeic-rtl-txn.")
                       for p in project.iterdir())
    finally:
        stage_binding.close()
        binding.close()
        _unlock_test_tree(project, tmp_path / "stage")


def test_rollback_restores_old_before_retrying_0555_new_cleanup(
        tmp_path, monkeypatch):
    pair = _read_only_transaction_pair(tmp_path, nested=True)
    project, binding, stage_binding, baseline, final = pair
    real_remove = runner._phase1_remove_owned_entry_fd
    injected = False
    # OBSERVE HERE, ASSERT IN THE TEST BODY.  `_remove_entry` swallows
    # FileNotFoundError as "already gone" and retries every other exception,
    # so an `assert` raised INSIDE this spy is absorbed by production code and
    # the test still passes.  Re-introducing the destroy-new-before-restore-old
    # ordering this test is named for therefore shipped green: the spy's read
    # of the not-yet-restored old tree raised FileNotFoundError, production
    # read that as success, and every remaining assertion still held.
    observed = []

    def _fail_new_cleanup_once(parent_fd, name):
        nonlocal injected
        if name.startswith("new.") and not injected:
            injected = True
            old = project / "phase2" / "locked" / "deeper" / "state.txt"
            try:
                observed.append(old.read_text())
            except OSError as exc:
                observed.append(f"OLD-TREE-NOT-RESTORED: {exc!r}")
            raise OSError("injected rolled-new cleanup failure")
        return real_remove(parent_fd, name)

    monkeypatch.setattr(
        runner, "_phase1_remove_owned_entry_fd", _fail_new_cleanup_once)
    try:
        transaction = runner._phase1_commit_staged_tree(
            binding, stage_binding, baseline, final)
        errors = transaction.rollback()

        assert injected
        assert observed == ["old canonical\n"], (
            "rollback destroyed staged-new work before the old canonical tree "
            f"was restored; the spy saw {observed}")
        assert errors == []
        old = project / "phase2" / "locked" / "deeper"
        assert (old / "state.txt").read_text() == "old canonical\n"
        assert not (old / "added.txt").exists()
        assert not any(p.name.startswith(".vibeic-rtl-txn.")
                       for p in project.iterdir())
    finally:
        stage_binding.close()
        binding.close()
        _unlock_test_tree(project, tmp_path / "stage")


def test_root_loss_at_final_acceptance_rolls_back_with_old_backup_intact(
        tmp_path):
    pair = _read_only_transaction_pair(tmp_path, nested=True)
    project, binding, stage_binding, baseline, final = pair
    displaced = tmp_path / "project.displaced"
    transaction = None
    try:
        transaction = runner._phase1_commit_staged_tree(
            binding, stage_binding, baseline, final)
        project.rename(displaced)
        project.mkdir()
        with pytest.raises(runner._Phase1RtlOutputRefused):
            binding.require_current()

        errors = transaction.rollback()
        transaction = None
        assert errors == []
        old = displaced / "phase2" / "locked" / "deeper"
        assert (old / "state.txt").read_text() == "old canonical\n"
        assert not (old / "added.txt").exists()
        assert not any(p.name.startswith(".vibeic-rtl-txn.")
                       for p in displaced.iterdir())
        assert not list(project.iterdir())
    finally:
        if transaction is not None:
            transaction.rollback()
        stage_binding.close()
        binding.close()
        _unlock_test_tree(project, displaced, tmp_path / "stage")


def test_final_commit_binding_check_keeps_backup_until_rollback(
        tmp_path, monkeypatch):
    pair = _read_only_transaction_pair(tmp_path, nested=True)
    project, binding, stage_binding, baseline, final = pair
    real_require = binding.require_current
    calls = 0

    def _fail_last_pre_return_check():
        nonlocal calls
        calls += 1
        if calls == 4:
            raise runner._Phase1RtlOutputRefused(
                "INJECTED_FINAL_BINDING_LOSS", project,
                "injected at the final pre-return binding check")
        return real_require()

    monkeypatch.setattr(binding, "require_current", _fail_last_pre_return_check)
    try:
        with pytest.raises(runner._Phase1RtlOutputRefused) as raised:
            runner._phase1_commit_staged_tree(
                binding, stage_binding, baseline, final)

        assert calls == 4
        assert raised.value.reason == "INJECTED_FINAL_BINDING_LOSS"
        old = project / "phase2" / "locked" / "deeper"
        assert (old / "state.txt").read_text() == "old canonical\n"
        assert not (old / "added.txt").exists()
        assert not any(p.name.startswith(".vibeic-rtl-txn.")
                       for p in project.iterdir())
    finally:
        stage_binding.close()
        binding.close()
        _unlock_test_tree(project, tmp_path / "stage")


def test_partial_prepared_copy_failure_removes_registered_container(
        tmp_path, monkeypatch):
    pair = _read_only_transaction_pair(tmp_path, nested=True)
    project, binding, stage_binding, baseline, final = pair
    real_copy = runner._phase1_copy_entry_fd
    injected = False

    def _copy_then_raise(src_parent_fd, src_name, dst_parent_fd, dst_name,
                         project_label):
        nonlocal injected
        real_copy(src_parent_fd, src_name, dst_parent_fd, dst_name,
                  project_label)
        if (src_parent_fd == stage_binding.project_fd
                and dst_name.startswith("new.") and not injected):
            injected = True
            raise OSError("injected after prepared subtree copy")

    monkeypatch.setattr(runner, "_phase1_copy_entry_fd", _copy_then_raise)
    try:
        with pytest.raises(runner._Phase1RtlOutputRefused) as raised:
            runner._phase1_commit_staged_tree(
                binding, stage_binding, baseline, final)

        assert injected
        assert raised.value.reason == "RTL_TRANSACTION_COMMIT_REFUSED"
        old = project / "phase2" / "locked" / "deeper"
        assert (old / "state.txt").read_text() == "old canonical\n"
        assert not (old / "added.txt").exists()
        assert not any(p.name.startswith(".vibeic-rtl-txn.")
                       for p in project.iterdir())
    finally:
        stage_binding.close()
        binding.close()
        _unlock_test_tree(project, tmp_path / "stage")


def test_step_root_replaced_after_publish_rolls_back_before_refusal(
        tmp_path, monkeypatch):
    project = _project(tmp_path / "project")
    displaced = tmp_path / "project.displaced"
    real_commit = runner._phase1_commit_staged_tree

    def _commit_then_replace(*args, **kwargs):
        transaction = real_commit(*args, **kwargs)
        project.rename(displaced)
        project.mkdir()
        return transaction

    monkeypatch.setattr(
        runner, "_phase1_commit_staged_tree", _commit_then_replace)

    result = runner.step_rtl_gen(
        project, "deliberately_unregistered_class")

    assert result.status == "BLOCKED"
    assert result.extras["output_refusal"]["reason"] == (
        "PROJECT_BOUNDARY_REPLACED_DURING_PUBLICATION")
    assert not (displaced / "phase2").exists()
    assert not any(p.name.startswith(".vibeic-rtl-txn.")
                   for p in displaced.iterdir())
    assert not list(project.iterdir())


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

        assert result.status == "BLOCKED"
        assert result.extras["output_refusal"]["reason"] == (
            "PROJECT_SNAPSHOT_OPEN_REFUSED")
        assert phase2.stat().st_mode & 0o777 == 0o000
        assert not any(p.name.startswith(".vibeic-rtl-txn.")
                       for p in project.iterdir())
    finally:
        phase2.chmod(0o755)
    assert sentinel.read_text() == "original\n"
    assert sorted(p.name for p in stage1.iterdir()) == ["sentinel.txt"]


def test_finalize_retries_cleanup_without_downgrading_committed_success(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    stage1 = project / "phase2" / "stage1"
    stage1.mkdir(parents=True)
    (stage1 / "sentinel.txt").write_text("original\n")
    real_remove = runner._phase1_remove_owned_entry_fd
    injected = False

    def _fail_backup_cleanup_once(parent_fd, name):
        nonlocal injected
        if name.startswith("old.") and not injected:
            injected = True
            raise OSError("injected finalize cleanup failure")
        return real_remove(parent_fd, name)

    monkeypatch.setattr(
        runner, "_phase1_remove_owned_entry_fd", _fail_backup_cleanup_once)

    result = runner.step_rtl_gen(
        project, "deliberately_unregistered_class")

    assert injected
    assert result.status == "PASS"
    assert "transaction_cleanup_warning" not in result.extras
    assert (project / "phase2" / "stage1" / "rtl" /
            "TopModule.v").is_file()
    assert not any(p.name.startswith(".vibeic-rtl-txn.")
                   for p in project.iterdir())


@pytest.mark.parametrize("locked_mode", [0o000, 0o444])
def test_finalize_removes_backup_with_nontraversable_nested_modes(
        tmp_path, locked_mode):
    pair = _read_only_transaction_pair(tmp_path, nested=True)
    project, binding, stage_binding, baseline, final = pair
    transaction = None
    try:
        transaction = runner._phase1_commit_staged_tree(
            binding, stage_binding, baseline, final)
        container = next(
            p for p in project.iterdir()
            if p.name.startswith(".vibeic-rtl-txn."))
        old = container / "old.0"
        directories = [old, *(p for p in old.rglob("*") if p.is_dir())]
        for directory in reversed(directories):
            directory.chmod(locked_mode)

        assert transaction.finalize() is None
        transaction = None
        assert not any(p.name.startswith(".vibeic-rtl-txn.")
                       for p in project.iterdir())
        target = project / "phase2" / "locked" / "deeper"
        assert (target / "state.txt").read_text() == "new staged\n"
    finally:
        if transaction is not None:
            transaction.rollback()
        stage_binding.close()
        binding.close()
        _unlock_test_tree(project, tmp_path / "stage")


def test_irreversible_finalize_residue_is_warning_not_false_blocked(
        tmp_path, monkeypatch):
    project = _project(tmp_path)

    monkeypatch.setattr(
        runner._Phase1StagedTreeTransaction, "_drain",
        lambda self: "injected persistent cleanup residue")

    result = runner.step_rtl_gen(
        project, "deliberately_unregistered_class")

    assert result.status == "PASS"
    assert result.extras["transaction_cleanup_warning"] == (
        "RTL_TRANSACTION_DRAIN_CLEANUP_FAILED: "
        "injected persistent cleanup residue")
    assert (project / "phase2" / "stage1" / "rtl" /
            "TopModule.v").is_file()
    assert not any(p.name.startswith(".vibeic-rtl-txn.")
                   for p in project.iterdir())


def test_alias_cleanup_error_after_drain_is_named_pass_warning(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    real_commit = runner._phase1_commit_staged_tree
    captured = []

    def _capture_transaction(*args, **kwargs):
        transaction = real_commit(*args, **kwargs)
        captured.append(transaction)
        return transaction

    def _fail_alias_cleanup(_transaction):
        raise OSError("injected post-drain alias cleanup failure")

    monkeypatch.setattr(
        runner, "_phase1_commit_staged_tree", _capture_transaction)
    monkeypatch.setattr(
        runner._Phase1StagedTreeTransaction, "_remove_container_aliases",
        _fail_alias_cleanup)

    result = runner.step_rtl_gen(
        project, "deliberately_unregistered_class")

    assert result.status == "PASS"
    assert result.extras["transaction_cleanup_warning"] == (
        "RTL_TRANSACTION_ALIAS_CLEANUP_FAILED: "
        "injected post-drain alias cleanup failure")
    assert (project / "phase2" / "stage1" / "rtl" /
            "TopModule.v").is_file()
    transaction = captured[-1]
    assert transaction.closed
    assert transaction.container_fd == -1
    residue = [
        p for p in project.iterdir()
        if p.name.startswith(".vibeic-rtl-txn.")]
    # The injected operation is the only reason this already-drained empty
    # container cannot be unlinked. Production retries remain covered above.
    assert len(residue) == 1
    assert not list(residue[0].iterdir())
    residue[0].rmdir()


def test_rollback_is_exception_total_and_releases_the_held_container(
        tmp_path, monkeypatch):
    """rollback() is the OTHER half of finalize()'s irreversible pair.

    finalize() was made exception-total because destroying rollback authority
    and then raising reports a committed success as BLOCKED.  rollback() has
    exactly the same shape and was left unhardened: its caller's whole contract
    is to RECEIVE the error list, and it calls this from inside an `except`
    block.  A raise there skipped `_close()`, leaked the held container
    descriptor, and escaped as a raw exception.
    """
    pair = _read_only_transaction_pair(tmp_path, nested=True)
    project, binding, stage_binding, baseline, final = pair
    try:
        transaction = runner._phase1_commit_staged_tree(
            binding, stage_binding, baseline, final)

        def _explode(_transaction):
            raise OSError("injected alias cleanup failure during rollback")

        monkeypatch.setattr(
            runner._Phase1StagedTreeTransaction, "_remove_container_aliases",
            _explode)

        errors = transaction.rollback()

        assert any("RTL_TRANSACTION_ALIAS_CLEANUP_FAILED" in e
                   for e in errors), errors
        assert any("injected alias cleanup failure during rollback" in e
                   for e in errors), errors
        assert transaction.closed
        assert transaction.container_fd == -1
        old = project / "phase2" / "locked" / "deeper"
        assert (old / "state.txt").read_text() == "old canonical\n"
        assert not (old / "added.txt").exists()
    finally:
        stage_binding.close()
        binding.close()
        _unlock_test_tree(project, tmp_path / "stage")


def test_a_failing_rollback_is_not_re_entered_from_the_finally(
        tmp_path, monkeypatch):
    """Ownership is released BEFORE rollback runs, not after.

    `transaction = None` used to be assigned after `transaction.rollback()`,
    so a rollback that failed part-way left itself named and the `finally`
    rolled the SAME half-rolled-back transaction back a second time.
    """
    project = _project(tmp_path)
    calls = []
    real_rollback = runner._Phase1StagedTreeTransaction.rollback

    def _counting_rollback(self):
        calls.append(1)
        real_rollback(self)
        raise OSError("injected rollback defect")

    def _fail_acceptance(*_args, **_kwargs):
        raise OSError("injected acceptance failure")

    monkeypatch.setattr(
        runner._Phase1StagedTreeTransaction, "rollback", _counting_rollback)
    monkeypatch.setattr(
        runner, "_phase1_cleanup_isolated_stage", _fail_acceptance)

    with pytest.raises(OSError):
        runner.step_rtl_gen(project, "deliberately_unregistered_class")

    assert len(calls) == 1, (
        f"rollback ran {len(calls)}x — the `finally` re-entered it on a "
        f"transaction that had already been rolled back")


def test_regular_file_copy_contains_write_side_oserror_like_the_dir_branch(
        tmp_path, monkeypatch):
    """The two branches of _phase1_copy_entry_fd must fail the same way.

    The directory branch wraps its whole body in `except OSError -> refusal`.
    The regular-file branch wrapped only the `open()`, so a WRITE-side failure
    (ENOSPC, EDQUOT, EROFS) escaped `step_rtl_gen` as a raw OSError — and
    `step_rtl_gen` catches `_Phase1RtlOutputRefused` and nothing else, so the
    caller got an exception where the contract promises a StepResult.
    """
    source = tmp_path / "src"
    source.mkdir()
    (source / "payload.txt").write_text("bytes\n")
    destination = tmp_path / "dst"
    destination.mkdir()

    def _no_space(_fd, _payload):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(runner, "_phase1_write_held_inode", _no_space)
    src_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY)
    try:
        dst_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with pytest.raises(runner._Phase1RtlOutputRefused) as caught:
                runner._phase1_copy_entry_fd(
                    src_fd, "payload.txt", dst_fd, "payload.txt",
                    Path("project"))
        finally:
            os.close(dst_fd)
    finally:
        os.close(src_fd)
    assert caught.value.reason == "PROJECT_SNAPSHOT_COPY_REFUSED"
    assert "No space left on device" in caught.value.detail


def test_alias_cleanup_that_succeeds_on_the_final_attempt_is_not_failed(
        tmp_path, monkeypatch):
    """The last pass was never re-read, so a success was reported as failure.

    The loop only re-scanned at the TOP of an attempt.  A third attempt that
    actually removed every alias still fell through and returned `last` — an
    exception from an EARLIER pass, about a name that no longer exists.
    """
    pair = _read_only_transaction_pair(tmp_path, nested=True)
    project, binding, stage_binding, baseline, final = pair
    transaction = None
    try:
        transaction = runner._phase1_commit_staged_tree(
            binding, stage_binding, baseline, final)
        assert transaction._drain() is None
        real_rmdir = os.rmdir
        attempts = []

        def _fail_the_first_two(name, dir_fd=None):
            attempts.append(name)
            if len(attempts) <= 2:
                raise OSError(errno.ENOTEMPTY, "Directory not empty")
            return real_rmdir(name, dir_fd=dir_fd)

        monkeypatch.setattr(os, "rmdir", _fail_the_first_two)

        assert transaction._remove_container_aliases() is None
        assert len(attempts) == 3
        monkeypatch.undo()
        assert not any(p.name.startswith(".vibeic-rtl-txn.")
                       for p in project.iterdir())
    finally:
        if transaction is not None:
            transaction._close()
        stage_binding.close()
        binding.close()
        _unlock_test_tree(project, tmp_path / "stage")


def test_returned_alias_error_is_reported_not_only_a_raised_one(
        tmp_path, monkeypatch):
    """The production failure mode is a RETURNED string, not an exception.

    `_remove_container_aliases` signals failure by RETURNING `str(last)` after
    its retries (ENOTEMPTY on an imperfect drain, a foreign file inside the
    container). The existing seam test injects a RAISE, which exercises only
    the new inner `except`; a regression that dropped the returned string would
    orphan a `.vibeic-rtl-txn.*` container in the canonical project with PASS
    and no warning, and nothing would notice. The symmetric drain case IS
    covered, so this closes a one-sided gap.
    """
    project = _project(tmp_path)
    monkeypatch.setattr(
        runner._Phase1StagedTreeTransaction, "_remove_container_aliases",
        lambda _self: "injected returned alias residue")

    result = runner.step_rtl_gen(
        project, "deliberately_unregistered_class")

    assert result.status == "PASS"
    assert result.extras["transaction_cleanup_warning"] == (
        "RTL_TRANSACTION_ALIAS_CLEANUP_FAILED: injected returned alias residue")
    assert (project / "phase2" / "stage1" / "rtl" / "TopModule.v").is_file()
    for residue in [p for p in project.iterdir()
                    if p.name.startswith(".vibeic-rtl-txn.")]:
        shutil.rmtree(residue, ignore_errors=True)


def test_both_cleanup_warnings_are_reported_not_only_the_first(
        tmp_path, monkeypatch):
    """`"; ".join(warnings)` must actually carry both halves.

    Replacing it with `warnings[0]` kept every suite green, so the second
    warning was free to disappear.
    """
    project = _project(tmp_path)
    monkeypatch.setattr(
        runner._Phase1StagedTreeTransaction, "_drain",
        lambda _self: "injected drain residue")
    monkeypatch.setattr(
        runner._Phase1StagedTreeTransaction, "_remove_container_aliases",
        lambda _self: "injected alias residue")

    result = runner.step_rtl_gen(
        project, "deliberately_unregistered_class")

    assert result.status == "PASS"
    assert result.extras["transaction_cleanup_warning"] == (
        "RTL_TRANSACTION_DRAIN_CLEANUP_FAILED: injected drain residue; "
        "RTL_TRANSACTION_ALIAS_CLEANUP_FAILED: injected alias residue")
    for residue in [p for p in project.iterdir()
                    if p.name.startswith(".vibeic-rtl-txn.")]:
        shutil.rmtree(residue, ignore_errors=True)


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
    project = _project(tmp_path)
    first = runner.step_rtl_gen(project, "deliberately_unregistered_class")
    assert first.status == "PASS"

    second = runner.step_rtl_gen(project, "deliberately_unregistered_class")

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
    assert result.status == "BLOCKED"
    assert result.extras["output_refusal"]["reason"] == (
        "RTL_TRANSACTION_STAGE_CLEANUP_REFUSED")
    assert not (project / "phase2").exists()
    assert not any(p.name.startswith(".vibeic-rtl-txn.")
                   for p in project.iterdir())


def test_incomplete_directional_semantics_defer_without_writing(tmp_path):
    incomplete = COMPLETE_DIRECTIONAL_FALL.replace(
        "Being bumped in the same cycle as ground\n"
        "disappears does not affect the walking direction. ",
        "")
    project = _project(tmp_path, incomplete)

    assert runner._try_phase1_behavioral_fsm_rtl(project, 0.0) is None
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_conflicting_declared_module_names_defer(tmp_path):
    project = _project(
        tmp_path, COMPLETE_DIRECTIONAL_FALL + "\nModule name: OtherTop\n")

    assert runner._try_phase1_behavioral_fsm_rtl(project, 0.0) is None
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_authored_rtl_guard_never_overwrites(tmp_path):
    project = _project(tmp_path)
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    authored = rtl_dir / "authored.sv"
    authored.write_text("module authored; endmodule\n")

    assert runner._try_phase1_behavioral_fsm_rtl(project, 0.0) is None
    assert authored.read_text() == "module authored; endmodule\n"
    assert sorted(p.name for p in rtl_dir.iterdir()) == ["authored.sv"]


@pytest.mark.parametrize("suffix", [".vhd", ".vhdl"])
def test_authored_vhdl_guard_never_adds_competing_verilog(tmp_path, suffix):
    project = _project(tmp_path)
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    authored = rtl_dir / f"authored{suffix}"
    authored.write_text("entity authored is end entity;\n")

    assert runner._try_phase1_behavioral_fsm_rtl(project, 0.0) is None
    assert authored.read_text() == "entity authored is end entity;\n"
    assert not (rtl_dir / "TopModule.v").exists()


@pytest.mark.parametrize("suffix", [".vhd", ".vhdl"])
def test_force_regen_preserves_vhdl_before_emitting_verilog(tmp_path, suffix):
    project = _project(tmp_path)
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    authored = rtl_dir / f"authored{suffix}"
    authored.write_text("entity authored is end entity;\n")

    result = runner._try_phase1_behavioral_fsm_rtl(
        project, 0.0, force_regen=True)

    assert result is not None and result.status == "PASS"
    assert not authored.exists()
    assert (rtl_dir / "TopModule.v").is_file()
    backups = list((project / "phase2" / "stage1").glob(
        "rtl.authored_backup.*"))
    assert len(backups) == 1
    assert (backups[0] / f"authored{suffix}").read_text() == (
        "entity authored is end entity;\n")


def test_non_behavioral_registry_result_is_not_a_broad_plain_prose_path(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setattr(
        registry, "generate",
        lambda _text, top: ("truth_table", f"module {top}; endmodule\n"))

    assert runner._try_phase1_behavioral_fsm_rtl(project, 0.0) is None
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_ordinary_grammar_nonmatch_is_not_a_provenance_blocker(tmp_path):
    project = _project(
        tmp_path, "Module name: TopModule\nordinary unmatched prose\n")

    direct = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    routed = runner.step_rtl_gen(project, "deliberately_unregistered_class")

    assert direct is None
    assert routed.status == "WAIVED"
    assert routed.extras.get("finding") is None
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_generated_ldoc_cannot_complete_incomplete_raw_prose(tmp_path):
    interface_only = COMPLETE_DIRECTIONAL_FALL.split(
        "Create a Moore state machine", 1)[0] + COMPLETE_DIRECTIONAL_FALL.split(
            "module TopModule", 1)[1]
    project = _project(tmp_path, interface_only)
    generated = project / "phase1" / "generated_docs"
    generated.mkdir(parents=True)
    (generated / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"summary": COMPLETE_DIRECTIONAL_FALL}))

    assert runner._try_phase1_behavioral_fsm_rtl(project, 0.0) is None
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_symlinked_plain_source_cannot_relabel_generated_l9_as_program_first(
        tmp_path):
    """An L9-derived prose file is not operator input through a symlink alias."""
    project = _project(tmp_path)
    generated = project / "phase1" / "generated_docs"
    generated.mkdir(parents=True)
    l9_generated = generated / "L9_AI_GENERATED.md"
    l9_generated.write_text(COMPLETE_DIRECTIONAL_FALL)
    source = project / "phase1" / "input_doc" / "design.md"
    source.unlink()
    source.symlink_to(l9_generated)

    _assert_gather_refusal(project, "SOURCE_OUT_OF_ROOT")
    _assert_flowback_refusal(project, "SOURCE_OUT_OF_ROOT")


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

    assert result.status == "BLOCKED"
    assert result.extras["finding"] == (
        "PHASE1_OPERATOR_PROSE_PROVENANCE_REFUSED")
    assert result.extras["source_refusal"]["reason"] == "SOURCE_OUT_OF_ROOT"
    assert result.extras["write_performed"] is False
    assert external.read_bytes() == before
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_valid_canonical_dispatch_reuses_one_immutable_operator_read(
        tmp_path, monkeypatch):
    project = _project(tmp_path, CANONICAL_PULSE)
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
    project = _project(tmp_path / "project", CANONICAL_PULSE)
    displaced = tmp_path / "project.displaced"
    real_emit = canonical_primitive.emit_rtl

    def _emit_then_replace(shape):
        rtl = real_emit(shape)
        project.rename(displaced)
        project.mkdir()
        return rtl

    monkeypatch.setattr(canonical_primitive, "emit_rtl", _emit_then_replace)

    result = runner.step_rtl_gen(
        project, "deliberately_unregistered_class")

    assert result.status == "BLOCKED"
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
    assert result.status == "BLOCKED"
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


def test_in_root_symlinked_file_is_a_named_source_refusal(tmp_path):
    project = _project(tmp_path / "project")
    source_dir = project / "phase1" / "input_doc"
    source = source_dir / "design.md"
    trusted = source_dir / "trusted.md"
    trusted.write_text(source.read_text())
    source.unlink()
    source.symlink_to(trusted)

    _assert_gather_refusal(project, "SOURCE_ENTRY_SYMLINK")
    _assert_flowback_refusal(project, "SOURCE_ENTRY_SYMLINK")


@pytest.mark.parametrize("link_kind", ["out_of_root", "broken"])
def test_out_of_root_and_broken_source_symlinks_fail_closed(
        tmp_path, link_kind):
    project = _project(tmp_path / "project")
    source_dir = project / "phase1" / "input_doc"
    target = tmp_path / (
        "external_L9.md" if link_kind == "out_of_root" else "missing_L9.md")
    if link_kind == "out_of_root":
        target.write_text(COMPLETE_DIRECTIONAL_FALL)
    (source_dir / f"{link_kind}.md").symlink_to(target)

    reason = ("SOURCE_OUT_OF_ROOT" if link_kind == "out_of_root"
              else "SOURCE_BROKEN_LINK")
    _assert_gather_refusal(project, reason)
    _assert_flowback_refusal(project, reason)


def test_invalid_utf8_operator_prose_is_named_parse_refusal(tmp_path):
    project = _project(tmp_path)
    source = project / "phase1" / "input_doc" / "design.md"
    source.write_bytes(b"module TopModule(\n\xff\xfe\n")

    _assert_gather_refusal(
        project, "SOURCE_TEXT_PARSE_FAILED",
        "PHASE1_OPERATOR_PROSE_PARSE_REFUSED")
    result = runner.step_rtl_gen(project, "deliberately_unregistered_class")
    assert result.status == "BLOCKED"
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

    assert first.status == second.status == "BLOCKED"
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
    assert result.status == "BLOCKED"
    assert result.extras["finding"] == "PHASE1_OPERATOR_PROSE_READ_REFUSED"
    assert result.extras["source_refusal"]["reason"] == "SOURCE_READ_FAILED"
    assert result.extras["write_performed"] is False
    assert not (project / "phase2" / "stage1" / "rtl").exists()


def test_provenance_stamp_makes_second_process_idempotent(tmp_path):
    project = _project(tmp_path)
    first = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert first is not None and first.status == "PASS"
    assert rtl_provenance.classify(project)[0] == rtl_provenance.GENERATED

    # Model a fresh interpreter: only the on-disk provenance proof survives.
    runner._RTL_SESSION_OWNED = False
    runner._RTL_SESSION_PROJECT = None
    second = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert second is not None and second.status == "PASS"
    assert second.extras["idempotent"] is True
    assert second.extras["rtl_provenance"] == rtl_provenance.GENERATED


def test_success_claims_session_with_non_capturing_atexit_callback(
        tmp_path, monkeypatch):
    registered = []
    monkeypatch.setattr(runner.atexit, "register", registered.append)
    project = _project(tmp_path)

    result = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert result is not None and result.status == "PASS"
    assert registered == [runner._finalize_rtl_provenance]
    assert runner._RTL_SESSION_OWNED is True
    assert runner._RTL_SESSION_PROJECT == project


def test_runner_owned_later_file_is_included_by_exit_stamp(tmp_path):
    """Aliases/wrappers added after generation remain generated next run."""
    project = _project(tmp_path)
    result = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert result is not None and result.status == "PASS"

    rtl_dir = project / "phase2" / "stage1" / "rtl"
    (rtl_dir / "runner_alias.v").write_text(
        "module runner_alias; endmodule\n")
    assert rtl_provenance.classify(project)[0] == rtl_provenance.AUTHORED

    runner._finalize_rtl_provenance()

    verdict, _why, evidence = rtl_provenance.classify(project)
    assert verdict == rtl_provenance.GENERATED
    assert evidence["file_count"] == 2
    assert set(rtl_provenance.load_ledger(project)["files"]) == {
        "TopModule.v", "runner_alias.v"}


def test_deleted_generated_primary_is_restored_with_owned_alias(tmp_path):
    """The rtl_provenance deletion contract applies at the flow-back boundary.

    With one unmodified runner-owned alias left behind, classify() is GENERATED
    and names TopModule.v as removed.  The flow-back must restore that exact
    primary without requiring the destructive override flag.
    """
    real_prompt = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "real_benchmark",
        "directional_bump_fall_moore_prompt.md").read_text()
    project = _project(tmp_path, real_prompt)
    first = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert first is not None and first.status == "PASS"
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    primary = rtl_dir / "TopModule.v"
    expected_primary = primary.read_text()
    alias = rtl_dir / "runner_alias.v"
    alias_text = "module runner_alias; endmodule\n"
    alias.write_text(alias_text)
    runner._finalize_rtl_provenance()

    runner._RTL_SESSION_OWNED = False
    runner._RTL_SESSION_PROJECT = None
    primary.unlink()
    verdict, _why, evidence = rtl_provenance.classify(project)
    assert verdict == rtl_provenance.GENERATED
    assert evidence["removed"] == ["TopModule.v"]

    restored = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert restored is not None
    assert restored.status == "PASS"
    assert restored.extras["restored_missing_primary"] is True
    assert restored.extras["rtl_provenance"] == rtl_provenance.GENERATED
    assert primary.read_text() == expected_primary
    assert alias.read_text() == alias_text
    assert rtl_provenance.classify(project)[0] == rtl_provenance.GENERATED
    assert not list((project / "phase2" / "stage1").glob(
        "rtl.authored_backup.*"))


def test_deleted_sole_generated_primary_is_digest_bound_and_restored(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    first = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert first is not None and first.status == "PASS"
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    primary = rtl_dir / "TopModule.v"
    expected = primary.read_bytes()
    primary.unlink()

    runner._RTL_SESSION_OWNED = False
    runner._RTL_SESSION_PROJECT = None
    verdict, _why, evidence = rtl_provenance.classify(project)
    assert verdict == rtl_provenance.GENERATED
    assert evidence["file_count"] == 0
    assert evidence["removed"] == ["TopModule.v"]

    real_load_ledger = _PROD_RTL_PROV.load_ledger
    ledger_reads = 0

    def _load_ledger_once(path):
        nonlocal ledger_reads
        ledger_reads += 1
        return real_load_ledger(path)

    monkeypatch.setattr(_PROD_RTL_PROV, "load_ledger", _load_ledger_once)

    restored = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert restored is not None and restored.status == "PASS"
    assert restored.extras["restored_missing_primary"] is True
    assert ledger_reads == 1
    assert primary.read_bytes() == expected
    assert rtl_provenance.classify(project)[0] == rtl_provenance.GENERATED


def test_deleted_sole_primary_with_source_drift_is_not_regenerated(
        tmp_path):
    project = _project(tmp_path)
    first = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert first is not None and first.status == "PASS"
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    primary = rtl_dir / "TopModule.v"
    ledger_before = rtl_provenance.ledger_path(project).read_bytes()
    primary.unlink()
    source = project / "phase1" / "input_doc" / "design.md"
    source.write_text(COMPLETE_DIRECTIONAL_FALL.replace(
        "bump_left", "hit_left"))

    runner._RTL_SESSION_OWNED = False
    runner._RTL_SESSION_PROJECT = None
    assert rtl_provenance.classify(project)[0] == rtl_provenance.GENERATED
    held = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert held is not None and held.status == "WAIVED"
    assert held.extras["preserved"] is True
    assert not primary.exists() and not primary.is_symlink()
    assert rtl_provenance.ledger_path(project).read_bytes() == ledger_before


def test_deleted_sole_primary_with_invalid_ledger_never_becomes_fresh_empty(
        tmp_path):
    project = _project(tmp_path)
    first = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert first is not None and first.status == "PASS"
    primary = project / "phase2" / "stage1" / "rtl" / "TopModule.v"
    primary.unlink()
    rtl_provenance.ledger_path(project).write_text("{ corrupt ledger")
    source = project / "phase1" / "input_doc" / "design.md"
    source.write_text(COMPLETE_DIRECTIONAL_FALL.replace(
        "bump_left", "hit_left"))

    runner._RTL_SESSION_OWNED = False
    runner._RTL_SESSION_PROJECT = None
    assert rtl_provenance.classify(project)[0] == rtl_provenance.UNKNOWN
    held = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert held is None
    assert not primary.exists() and not primary.is_symlink()


@pytest.mark.parametrize("target_exists", [False, True])
def test_primary_symlink_never_reads_as_idempotent_or_writes_external_target(
        tmp_path, target_exists):
    project = _project(tmp_path / "project")
    first = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert first is not None and first.status == "PASS"
    primary = project / "phase2" / "stage1" / "rtl" / "TopModule.v"
    generated = primary.read_bytes()
    primary.unlink()
    external_dir = tmp_path / "external"
    external_dir.mkdir()
    target = external_dir / "foreign.v"
    if target_exists:
        # Byte-identical foreign content must not make a symlinked output look
        # like an idempotent runner-owned regular file.
        target.write_bytes(generated)
    primary.symlink_to(target)
    before = target.read_bytes() if target_exists else None

    runner._RTL_SESSION_OWNED = False
    runner._RTL_SESSION_PROJECT = None
    result = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert result is not None and result.status == "BLOCKED"
    assert result.extras["finding"] == (
        "PHASE1_RTL_OUTPUT_PROVENANCE_REFUSED")
    expected_reason = ("RTL_OUTPUT_SYMLINK" if target_exists
                       else "RTL_OUTPUT_BROKEN_SYMLINK")
    assert result.extras["output_refusal"]["reason"] == expected_reason
    assert result.extras["write_performed"] is False
    assert primary.is_symlink()
    if target_exists:
        assert target.read_bytes() == before
    else:
        assert not target.exists()


@pytest.mark.parametrize("ancestor", ["phase2", "stage1", "rtl"])
@pytest.mark.parametrize("target_exists", [False, True])
def test_every_output_ancestor_symlink_is_a_no_write_refusal(
        tmp_path, ancestor, target_exists):
    project = _project(tmp_path / "project")
    phase2 = project / "phase2"
    stage1 = phase2 / "stage1"
    rtl_dir = stage1 / "rtl"
    external = tmp_path / f"external_{ancestor}"
    if target_exists:
        external.mkdir()
    if ancestor == "phase2":
        phase2.symlink_to(external, target_is_directory=True)
    elif ancestor == "stage1":
        phase2.mkdir()
        stage1.symlink_to(external, target_is_directory=True)
    else:
        stage1.mkdir(parents=True)
        rtl_dir.symlink_to(external, target_is_directory=True)

    result = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert result is not None and result.status == "BLOCKED"
    reason = result.extras["output_refusal"]["reason"]
    assert reason == ("RTL_ANCESTOR_SYMLINK" if target_exists
                      else "RTL_ANCESTOR_BROKEN_SYMLINK")
    assert result.extras["write_performed"] is False
    assert not (external / "stage1" / "rtl" / "TopModule.v").exists()
    assert not (external / "rtl" / "TopModule.v").exists()
    assert not (external / "TopModule.v").exists()


def test_no_clobber_publication_loses_race_without_touching_foreign_file(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    primary = project / "phase2" / "stage1" / "rtl" / "TopModule.v"
    foreign = "module TopModule; // raced foreign work\nendmodule\n"
    real_link = runner.os.link

    def _racing_link(*args, **kwargs):
        primary.write_text(foreign)
        return real_link(*args, **kwargs)

    monkeypatch.setattr(runner.os, "link", _racing_link)
    result = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert result is not None and result.status == "BLOCKED"
    assert result.extras["output_refusal"]["reason"] == (
        "RTL_OUTPUT_ALREADY_EXISTS")
    assert result.extras["write_performed"] is False
    assert primary.read_text() == foreign
    assert not list(primary.parent.glob(".TopModule.v.tmp.*"))


def test_temp_name_substitution_cannot_change_fd_bound_published_bytes(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    primary = rtl_dir / "TopModule.v"
    real_open = runner.os.open
    real_link = runner.os.link
    substituted = []
    foreign = b"foreign bytes substituted at the cleanup-only temp name\n"

    def _without_o_tmpfile(path, flags, *args, **kwargs):
        tmpfile = getattr(runner.os, "O_TMPFILE", 0)
        if tmpfile and flags & tmpfile == tmpfile:
            raise OSError(runner.errno.EOPNOTSUPP, "forced named fallback")
        return real_open(path, flags, *args, **kwargs)

    def _substitute_before_link(source, destination, *args, **kwargs):
        if destination == "TopModule.v" and not substituted:
            candidates = list(rtl_dir.glob(".TopModule.v.tmp.*"))
            assert len(candidates) == 1
            cleanup_name = candidates[0]
            held_alias = rtl_dir / ".renamed-held-output-inode"
            cleanup_name.rename(held_alias)
            cleanup_name.write_bytes(foreign)
            substituted.append((cleanup_name, held_alias))
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(runner.os, "open", _without_o_tmpfile)
    monkeypatch.setattr(runner.os, "link", _substitute_before_link)

    result = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert result is not None and result.status == "PASS"
    assert substituted
    cleanup_name, held_alias = substituted[0]
    assert cleanup_name.read_bytes() == foreign
    assert not held_alias.exists()
    assert "module TopModule(" in primary.read_text()
    ledger = json.loads(rtl_provenance.ledger_path(project).read_text())
    assert ledger["files"] == {
        "TopModule.v": rtl_provenance.sha256_file(primary)}
    generated_digest = rtl_provenance.sha256_file(primary)
    assert not [
        path for path in rtl_dir.iterdir()
        if path != primary and path.is_file()
        and rtl_provenance.sha256_file(path) == generated_digest
    ]


@pytest.mark.parametrize("ancestor", ["phase2", "stage1", "rtl"])
def test_ancestor_replacement_after_output_publish_rolls_back_held_tree(
        tmp_path, monkeypatch, ancestor):
    project = _project(tmp_path)
    phase2 = project / "phase2"
    stage1 = phase2 / "stage1"
    rtl_dir = stage1 / "rtl"
    external = tmp_path / f"external_{ancestor}"
    external.mkdir()
    real_stamp = runner._stamp_phase1_rtl_publication
    displaced = []

    def _replace_ancestor_then_stamp(publication, generator):
        live = {"phase2": phase2, "stage1": stage1, "rtl": rtl_dir}[ancestor]
        moved = live.with_name(live.name + ".displaced")
        live.rename(moved)
        live.symlink_to(external, target_is_directory=True)
        displaced.append(moved)
        return real_stamp(publication, generator)

    monkeypatch.setattr(
        runner, "_stamp_phase1_rtl_publication",
        _replace_ancestor_then_stamp)

    result = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert result is not None and result.status == "BLOCKED"
    assert result.extras["output_refusal"]["reason"] == (
        "RTL_ANCESTOR_REPLACED_DURING_PUBLICATION")
    assert result.extras["write_performed"] is False
    assert displaced and not list(external.rglob("*"))
    assert not list(displaced[0].rglob("TopModule.v"))
    assert not list(displaced[0].rglob(rtl_provenance.LEDGER_NAME))


@pytest.mark.parametrize(
    "replacement",
    ["directory", "missing", "external_symlink", "broken_symlink", "file"],
)
def test_project_root_replacement_after_output_publish_is_blocked_and_rolled_back(
        tmp_path, monkeypatch, replacement):
    project = _project(tmp_path / "project")
    displaced = tmp_path / "project.displaced"
    external = tmp_path / "external"
    external.mkdir()
    real_stamp = runner._stamp_phase1_rtl_publication

    def _replace_project_then_stamp(publication, generator):
        project.rename(displaced)
        if replacement == "directory":
            project.mkdir()
        elif replacement == "external_symlink":
            project.symlink_to(external, target_is_directory=True)
        elif replacement == "broken_symlink":
            project.symlink_to(
                tmp_path / "missing-external", target_is_directory=True)
        elif replacement == "file":
            project.write_text("foreign replacement\n")
        return real_stamp(publication, generator)

    monkeypatch.setattr(
        runner, "_stamp_phase1_rtl_publication",
        _replace_project_then_stamp)

    result = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert result is not None and result.status == "BLOCKED"
    assert result.extras["output_refusal"]["reason"] == (
        "PROJECT_BOUNDARY_REPLACED_DURING_PUBLICATION")
    assert result.extras["write_performed"] is False
    assert result.output_files == []
    assert not list(external.rglob("*"))
    assert not list(displaced.rglob("TopModule.v"))
    assert not list(displaced.rglob(rtl_provenance.LEDGER_NAME))
    if replacement == "directory":
        assert not list(project.rglob("*"))
    elif replacement == "missing":
        assert not project.exists() and not project.is_symlink()
    elif replacement == "external_symlink":
        assert project.is_symlink() and project.resolve() == external
    elif replacement == "broken_symlink":
        assert project.is_symlink()
        assert not (tmp_path / "missing-external").exists()
    elif replacement == "file":
        assert project.read_text() == "foreign replacement\n"


@pytest.mark.parametrize(
    "replacement",
    ["directory", "missing", "external_symlink", "broken_symlink", "file"],
)
def test_project_root_replaced_before_publisher_cannot_become_new_baseline(
        tmp_path, monkeypatch, replacement):
    project = _project(tmp_path / "project")
    displaced = tmp_path / "project.displaced"
    external = tmp_path / "external"
    external.mkdir()
    real_publish = runner._publish_phase1_rtl_no_clobber

    def _replace_project_then_publish(*args, **kwargs):
        project.rename(displaced)
        if replacement == "directory":
            project.mkdir()
        elif replacement == "external_symlink":
            project.symlink_to(external, target_is_directory=True)
        elif replacement == "broken_symlink":
            project.symlink_to(
                tmp_path / "missing-external", target_is_directory=True)
        elif replacement == "file":
            project.write_text("foreign replacement\n")
        return real_publish(*args, **kwargs)

    monkeypatch.setattr(
        runner, "_publish_phase1_rtl_no_clobber",
        _replace_project_then_publish)

    result = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert result is not None and result.status == "BLOCKED"
    assert result.extras["output_refusal"]["reason"] == (
        "PROJECT_BOUNDARY_REPLACED_DURING_PUBLICATION")
    assert result.extras["write_performed"] is False
    assert result.output_files == []
    assert not list(external.rglob("*"))
    assert not (displaced / "phase2").exists()
    if replacement == "directory":
        assert not list(project.rglob("*"))
    elif replacement == "missing":
        assert not project.exists() and not project.is_symlink()
    elif replacement == "external_symlink":
        assert project.is_symlink() and project.resolve() == external
    elif replacement == "broken_symlink":
        assert project.is_symlink()
        assert not (tmp_path / "missing-external").exists()
    elif replacement == "file":
        assert project.read_text() == "foreign replacement\n"


def test_deleted_primary_is_not_restored_over_foreign_alias_edit(tmp_path):
    project = _project(tmp_path)
    first = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert first is not None and first.status == "PASS"
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    alias = rtl_dir / "runner_alias.v"
    alias.write_text("module runner_alias; endmodule\n")
    runner._finalize_rtl_provenance()

    runner._RTL_SESSION_OWNED = False
    runner._RTL_SESSION_PROJECT = None
    (rtl_dir / "TopModule.v").unlink()
    foreign = "module runner_alias; // foreign edit\nendmodule\n"
    alias.write_text(foreign)
    assert rtl_provenance.classify(project)[0] == rtl_provenance.AUTHORED

    assert runner._try_phase1_behavioral_fsm_rtl(project, 0.0) is None
    assert not (rtl_dir / "TopModule.v").exists()
    assert alias.read_text() == foreign


def test_deleted_primary_with_stale_digest_requires_force(tmp_path):
    project = _project(tmp_path)
    first = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert first is not None and first.status == "PASS"
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    alias = rtl_dir / "runner_alias.v"
    alias_text = "module runner_alias; endmodule\n"
    alias.write_text(alias_text)
    runner._finalize_rtl_provenance()

    runner._RTL_SESSION_OWNED = False
    runner._RTL_SESSION_PROJECT = None
    (rtl_dir / "TopModule.v").unlink()
    source = project / "phase1" / "input_doc" / "design.md"
    source.write_text(COMPLETE_DIRECTIONAL_FALL.replace(
        "bump_left", "hit_left"))
    assert rtl_provenance.classify(project)[0] == rtl_provenance.GENERATED

    held = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert held is not None and held.status == "WAIVED"
    assert held.extras["preserved"] is True
    assert held.extras["override_flag"] == "--force-rtl-regen"
    assert not (rtl_dir / "TopModule.v").exists()
    assert alias.read_text() == alias_text


def test_eco_reentry_keeps_deterministic_path_before_exit_stamp(tmp_path):
    """An alias added mid-run is runner-owned, not a reason to defer to AI."""
    project = _project(tmp_path)
    first = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert first is not None and first.status == "PASS"

    rtl_dir = project / "phase2" / "stage1" / "rtl"
    alias = rtl_dir / "runner_alias.v"
    alias.write_text("module runner_alias; endmodule\n")
    assert rtl_provenance.classify(project)[0] == rtl_provenance.AUTHORED

    second = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)

    assert second is not None and second.status == "PASS"
    assert second.extras["rtl_provenance"] == "session_owned"
    assert second.extras["idempotent"] is True
    assert alias.is_file()


def test_force_regen_updates_changed_generator_owned_rtl(tmp_path):
    project = _project(tmp_path)
    first = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert first is not None and first.status == "PASS"
    source = project / "phase1" / "input_doc" / "design.md"
    source.write_text(COMPLETE_DIRECTIONAL_FALL.replace("bump_left", "hit_left"))

    held = runner._try_phase1_behavioral_fsm_rtl(project, 0.0)
    assert held is not None and held.status == "WAIVED"
    forced = runner._try_phase1_behavioral_fsm_rtl(
        project, 0.0, force_regen=True)
    assert forced is not None and forced.status == "PASS"
    rtl = (project / "phase2" / "stage1" / "rtl" / "TopModule.v").read_text()
    assert "hit_left" in rtl and "bump_left" not in rtl
    assert list((project / "phase2" / "stage1").glob("rtl.authored_backup.*"))
