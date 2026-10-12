"""Tests for step_output_collector + the dashboard per-step folder routes.

step_output_collector retains timestamped independent copies and manifests.
The canonical phaseN tree remains in place; earlier evidence is never pruned. Nested by phase then stage (owner directive) so a
step's place in the flow is visible from its path, not just a flat peer
list. The web route serving those folders is path-traversal guarded.
"""
from __future__ import annotations

import json
import hashlib
import os
import sys
from pathlib import Path

import pytest

PROG = Path(os.environ.get('VIBEIC_OUTPUT_RETENTION_PROGRAMS',
                           str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(PROG))
import step_output_collector as SOC  # noqa: E402
import flow_dashboard_data as FDD  # noqa: E402


def test_supported_python_without_file_digest_retains_exact_output(tmp_path, monkeypatch):
    """Python 3.10 must retain output without the 3.11-only helper."""
    monkeypatch.delattr(hashlib, 'file_digest', raising=False)
    path = tmp_path / 'phase2/stage1/rtl/counter.v'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'abc')
    expected = 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
    assert SOC._sha(path) == expected
    attempt = SOC.begin_step(tmp_path, '1')
    retained = SOC.finish_step(tmp_path, attempt, verdict='FAIL')
    folder = tmp_path / retained['storage_root'] / retained['folder']
    assert (folder / path.name).read_bytes() == b'abc'
    assert SOC.latest_pass(tmp_path, '1') is None
    assert path.read_bytes() == b'abc'


def test_portable_output_hash_covers_empty_and_multiple_chunks(tmp_path, monkeypatch):
    monkeypatch.delattr(hashlib, 'file_digest', raising=False)
    path = tmp_path / 'output.bin'
    for data in (b'', bytes(range(256)) * 8201):
        path.write_bytes(data)
        assert SOC._sha(path) == hashlib.sha256(data).hexdigest()


def test_sequential_child_does_not_interrupt_its_live_parent(tmp_path):
    import _progress_run as pr
    parent = SOC.begin_step(tmp_path, '1')
    folder = tmp_path / parent['storage_root'] / parent['folder']
    inherited = os.environ.get(SOC._ACTIVE_LOCAL_ENV)
    code = ('import sys; from pathlib import Path; '
            f'sys.path.insert(0, {str(PROG)!r}); '
            'import step_output_collector as soc; '
            f'p=Path({str(tmp_path)!r}); '
            'child=soc.begin_step(p,"2"); '
            'soc.finish_step(p,child,verdict="FAIL")')
    with SOC.active_steps(tmp_path, [parent]):
        child = pr.run([sys.executable, '-c', code], capture_output=True, text=True)
        assert child.returncode == 0, child.stderr
        assert not (folder / 'outputs.json').exists()
        SOC.finish_step(tmp_path, parent, verdict='FAIL')
    assert os.environ.get(SOC._ACTIVE_LOCAL_ENV) == inherited
    assert json.loads((folder / 'outputs.json').read_text())['status'] == 'FAIL'
    # A genuinely unfinished previous top-level call must still recover.
    abandoned = SOC.begin_step(tmp_path, '1')
    SOC.begin_step(tmp_path, '2')
    recovered = tmp_path / abandoned['storage_root'] / abandoned['folder'] / 'outputs.json'
    assert json.loads(recovered.read_text())['status'] == 'INTERRUPTED'


@pytest.mark.parametrize('step', FDD._load_flow()[1], ids=lambda s: str(s['id']))
def test_every_canonical_step_keeps_all_declared_previous_bytes(tmp_path, step):
    """All 70 declarations; synthetic file transport, not native IC execution."""
    specs = list(step.get('required_outputs') or [])
    specs += [row['path'] for row in step.get('program_outputs', []) if row.get('path')]
    expected = {}
    for spec in specs:
        for alternative in spec.split(' OR '):
            for label in ('first', 'second') if '*' in alternative else ('first',):
                relative = alternative.strip().replace('**', 'nested/deep').replace('*', label)
                path = tmp_path / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                expected[relative] = ('old ' + relative).encode()
                path.write_bytes(expected[relative])
    attempt = SOC.begin_step(tmp_path, str(step['id']))
    folder = tmp_path / attempt['storage_root'] / attempt['folder']
    before = json.loads((folder / 'before/outputs.json').read_text())
    assert before['capture_errors'] == []
    assert {row['rel'] for row in before['outputs']} == set(expected)
    for row in before['outputs']:
        assert (folder / 'before' / row['snapshot']).read_bytes() == expected[row['rel']]
    # An unsuccessful retry must retain the old evidence without inventing PASS.
    for relative in expected:
        (tmp_path / relative).unlink()
    result = SOC.finish_step(tmp_path, attempt, verdict='NOT_MEASURED')
    assert result['canonical_pass'] is False
    assert SOC.latest_pass(tmp_path, str(step['id'])) is None
    for row in before['outputs']:
        assert (folder / 'before' / row['snapshot']).read_bytes() == expected[row['rel']]


def test_retention_resolves_every_match_without_the_dashboard_display_cap(tmp_path):
    paths = ['rtl/a.v', 'rtl/b.v', 'rtl/a.sv', 'directory/deep/output.txt']
    paths += [f'extra/{i}.json' for i in range(FDD._OUTPUTS_CAP + 2)]
    for relative in paths:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
    specs = ['rtl/*.v OR rtl/*.sv', 'directory'] + paths[4:]
    display, present, total = FDD._resolve_outputs(tmp_path, specs)
    retained, retained_present, retained_total = FDD._resolve_outputs(
        tmp_path, specs, retain_all=True)
    assert len(display) == FDD._OUTPUTS_CAP
    assert {row['rel'] for row in retained} == set(paths)
    assert (retained_present, retained_total) == (present, total)


def test_supplemental_output_is_preserved_without_satisfying_required_outputs(tmp_path):
    def row():
        return next(s for p in FDD.collect(tmp_path, live=False)['phases']
                    for s in p['steps'] if s['id'] == 'M2')
    original = row()
    path = tmp_path / 'reports/analog/mixed_signal/power_domain_producer_audit.json'
    path.parent.mkdir(parents=True)
    path.write_text('{"evidence":"supplement only"}')
    current = row()
    assert current['status'] == original['status']
    assert current['status'] != 'pass'
    assert not any(o['exists'] for o in current['outputs'])
    assert path in [Path(o['abs']) for o in current.get('retention_outputs', []) if o['exists']]


def _mk_project(tmp: Path) -> Path:
    # a real flow-step output: step 1 (Spec-to-RTL) → phase2/stage1/rtl/*
    rtl = tmp / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "spm.v").write_text("module spm; endmodule\n")
    return tmp


def test_materialize_creates_steps_tree(tmp_path):
    _mk_project(tmp_path)
    res = SOC.materialize(tmp_path)
    assert res["n_steps"] > 0
    steps_root = tmp_path / "steps"
    assert (steps_root / "index.json").is_file()
    idx = json.loads((steps_root / "index.json").read_text())
    assert isinstance(idx.get("steps"), list) and idx["steps"]


def test_authored_rtl_is_copied_into_its_step_version(tmp_path):
    _mk_project(tmp_path)
    SOC.materialize(tmp_path)
    # find the step folder that captured spm.v — nested 3 levels deep now:
    # steps/<phase>/<stage>/<id>_<slug>/spm.v
    hits = list((tmp_path / "steps").glob("*/*/*/spm.v"))
    assert hits, "spm.v should be symlinked under steps/<phase>/<stage>/<id>_<slug>/"
    link = hits[0]
    assert link.is_file() and not link.is_symlink()
    original = tmp_path / "phase2/stage1/rtl/spm.v"
    expected = original.read_bytes()
    original.write_text("new retry content\n")
    assert link.read_bytes() == expected
    # manifest present + well-formed, and carries the phase/stage that
    # produced this exact nesting
    man = json.loads((link.parent / "outputs.json").read_text())
    assert man["id"] and man["outputs"]
    assert man["phase"] and man["stage"]
    assert link.parent.relative_to(tmp_path / "steps") == Path(man["folder"])


def test_folder_is_nested_phase_then_stage(tmp_path):
    """The owner directive this collector implements: a step's directory
    encodes WHERE in the flow it sits, not just a flat peer list."""
    _mk_project(tmp_path)
    SOC.materialize(tmp_path)
    idx = json.loads((tmp_path / "steps/index.json").read_text())
    step1 = next(s for s in idx["steps"] if s["id"] == "1")
    assert step1["folder"].startswith(f"{step1['phase']}/{step1['stage']}/1_spec_to_rtl_")
    import re
    assert re.search(r"_\d{8}T\d{6}_\d{6}Z$", step1["folder"])
    assert (tmp_path / "steps" / step1["folder"]).is_dir()


def test_two_steps_in_different_stages_do_not_collide(tmp_path):
    """DIRECTION 1: nesting must not accidentally MERGE unrelated steps just
    because a flat id/slug happened to be unique before — every step gets
    its own leaf directory regardless of how many share a phase or stage."""
    _mk_project(tmp_path)
    SOC.materialize(tmp_path)
    idx = json.loads((tmp_path / "steps/index.json").read_text())
    folders = [s["folder"] for s in idx["steps"]]
    assert len(folders) == len(set(folders)), "duplicate step folder paths"


def test_canonical_tree_is_not_moved(tmp_path):
    _mk_project(tmp_path)
    SOC.materialize(tmp_path)
    # the original file stays exactly where inter-step contracts expect it
    assert (tmp_path / "phase2/stage1/rtl/spm.v").is_file()
    assert not (tmp_path / "phase2/stage1/rtl/spm.v").is_symlink()


def test_idempotent(tmp_path):
    _mk_project(tmp_path)
    a = SOC.materialize(tmp_path)
    b = SOC.materialize(tmp_path)   # second run must not error or duplicate
    assert a["n_steps"] == b["n_steps"]


def test_observation_does_not_invent_executed_pass(tmp_path):
    _mk_project(tmp_path)
    SOC.materialize(tmp_path)
    assert not (tmp_path / 'steps/latest_pass.json').exists()
    assert SOC.latest_pass(tmp_path, '1') is None


def test_pass_fail_pass_keeps_all_bytes_logs_and_pass_selection(tmp_path):
    _mk_project(tmp_path)
    source = next((tmp_path / 'phase2/stage1/rtl').glob('*.v'))
    log = tmp_path / 'reports/native.log'
    log.parent.mkdir()
    saved = []
    for outcome, content in [('PASS', b'first accepted result'),
                             ('FAIL', b'failed retry result'),
                             ('PASS', b'last accepted result')]:
        attempt = SOC.begin_step(tmp_path, '1')
        source.write_bytes(content)
        log.write_bytes(content + b' log')
        record = SOC.finish_step(tmp_path, attempt, verdict=outcome,
                                 result={'verdict': outcome}, canonical_pass=outcome == 'PASS')
        folder = tmp_path / 'steps' / record['folder']
        saved.append((folder, content))
        assert (folder / source.name).read_bytes() == content
        assert (folder / 'files/reports/native.log').read_bytes() == content + b' log'
        chosen = SOC.latest_pass(tmp_path, '1')
        expected = saved[0][0] if outcome == 'FAIL' else folder
        assert tmp_path / 'steps' / chosen['folder'] == expected
        for old, old_bytes in saved:
            assert (old / source.name).read_bytes() == old_bytes
            assert (old / 'files/reports/native.log').read_bytes() == old_bytes + b' log'
    assert len({str(folder) for folder, _ in saved}) == 3


def test_component_pass_never_replaces_complete_step_pass(tmp_path):
    _mk_project(tmp_path)
    attempt = SOC.begin_step(tmp_path, '1')
    SOC.finish_step(tmp_path, attempt, verdict='PASS', result={'tool_rc': 0})
    assert SOC.latest_pass(tmp_path, '1') is None


def test_changed_input_marks_pass_as_historical(tmp_path):
    _mk_project(tmp_path)
    spec = tmp_path / 'input/spec.json'
    spec.parent.mkdir()
    spec.write_text('{"width": 8}')
    attempt = SOC.begin_step(tmp_path, '1', {'input/spec.json': SOC._sha(spec)})
    SOC.finish_step(tmp_path, attempt, verdict='PASS', canonical_pass=True)
    assert SOC.latest_pass(tmp_path, '1')['current_inputs'] is True
    spec.write_text('{"width": 16}')
    historical = SOC.latest_pass(tmp_path, '1')
    assert historical['status'] == 'PASS' and historical['current_inputs'] is False


def test_interrupted_attempt_is_saved_before_a_retry_overwrites_it(tmp_path):
    _mk_project(tmp_path)
    source = next((tmp_path / 'phase2/stage1/rtl').glob('*.v'))
    first = SOC.begin_step(tmp_path, '1')
    SOC.finish_step(tmp_path, first, verdict='PASS', canonical_pass=True)
    interrupted = SOC.begin_step(tmp_path, '1')
    source.write_bytes(b'partial output before process died')
    retry = SOC.begin_step(tmp_path, '1')
    partial = tmp_path / 'steps' / interrupted['folder']
    assert json.loads((partial / 'outputs.json').read_text())['status'] == 'INTERRUPTED'
    source.write_bytes(b'new retry output')
    assert (partial / source.name).read_bytes() == b'partial output before process died'
    assert SOC.latest_pass(tmp_path, '1')['folder'] == first['folder']
    SOC.finish_step(tmp_path, retry, verdict='FAIL')


def test_view_refresh_cannot_rewrite_an_executed_version(tmp_path):
    _mk_project(tmp_path)
    attempt = SOC.begin_step(tmp_path, '1')
    SOC.finish_step(tmp_path, attempt, verdict='FAIL', result={'detail': 'measured failure'})
    folder = tmp_path / 'steps' / attempt['folder']
    original = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    SOC.materialize(tmp_path, only_steps={'1'})
    for name, content in original.items():
        assert (folder / name).read_bytes() == content
    assert SOC.latest_pass(tmp_path, '1') is None


def test_web_stepfile_path_traversal_guarded(tmp_path):
    _mk_project(tmp_path)
    SOC.materialize(tmp_path)
    import flow_dashboard_web as W
    # a legitimate file inside a step folder resolves. `folder` is now a
    # multi-segment relative path (phase/stage/id_slug) — the dashboard's own
    # `_steps_root(project) / folder` must nest on that string with no
    # change on its side (Path's "/" already handles embedded "/"), which is
    # exactly what this test is pinning.
    idx = json.loads((tmp_path / "steps/index.json").read_text())
    folder = next(s["folder"] for s in idx["steps"]
                  if (tmp_path / "steps" / s["folder"] / "spm.v").exists())
    ok = W._step_file_response(str(tmp_path), folder, "spm.v")
    assert ok is not None and b"module spm" in ok[0]
    # traversal attempts are rejected
    assert W._step_file_response(str(tmp_path), "..", "x") is None
    assert W._step_file_response(str(tmp_path), folder, "../../etc/passwd") is None
    assert W._step_file_response(str(tmp_path), folder, "nope.xyz") is None
    # traversal THROUGH the now-multi-segment folder itself must still be
    # rejected — a nested folder string is more surface for ".." to hide in
    assert W._step_file_response(str(tmp_path), folder + "/../../..", "spm.v") is None


def test_migrating_from_a_prior_flat_layout_retains_its_bytes(tmp_path):
    """A run materialized under the OLD flat `<id>_<slug>/` scheme, then
    re-materialized under this nested one, must not leave the old folder
    sitting next to the new tree forever — it would look like a second,
    increasingly stale copy of the same step's outputs."""
    _mk_project(tmp_path)
    steps_root = tmp_path / "steps"
    old_folder = steps_root / "1_spec_to_rtl"
    old_folder.mkdir(parents=True)
    (old_folder / "spm.v").symlink_to(tmp_path / "phase2/stage1/rtl/spm.v")
    (old_folder / "outputs.json").write_text(json.dumps(
        {"id": "1", "name": "Spec-to-RTL", "status": "pass",
         "folder": "1_spec_to_rtl", "outputs": []}))
    (steps_root / "index.json").write_text(json.dumps({"steps": [
        {"id": "1", "name": "Spec-to-RTL", "status": "pass",
         "folder": "1_spec_to_rtl", "n_outputs": 0}]}))

    SOC.materialize(tmp_path)

    assert old_folder.is_dir()
    assert (old_folder / "spm.v").is_file() and not (old_folder / "spm.v").is_symlink()
    original = tmp_path / "phase2/stage1/rtl/spm.v"
    saved = (old_folder / "spm.v").read_bytes()
    original.write_text("retry changed the working file\n")
    assert (old_folder / "spm.v").read_bytes() == saved
    idx = json.loads((steps_root / "index.json").read_text())
    step1 = next(s for s in idx["steps"] if s["id"] == "1")
    assert "/" in step1["folder"], "the new run must be nested"
    assert (steps_root / step1["folder"] / "spm.v").is_file()
    assert not (steps_root / step1["folder"] / "spm.v").is_symlink()


def test_refresh_keeps_older_phase_and_stage_directories(tmp_path):
    """DIRECTION 1 sibling: pruning a stale leaf must not leave an empty
    phase/ or stage/ directory behind as debris, but must also not remove
    anything ABOVE `steps/` itself."""
    _mk_project(tmp_path)
    steps_root = tmp_path / "steps"
    stale = steps_root / "phaseX" / "stageY" / "1_old_name"
    stale.mkdir(parents=True)
    (steps_root / "index.json").write_text(json.dumps({"steps": [
        {"id": "1", "name": "Old Name", "status": "pass",
         "folder": "phaseX/stageY/1_old_name", "n_outputs": 0}]}))

    SOC.materialize(tmp_path)

    assert stale.is_dir()
    assert (steps_root / "phaseX/stageY").is_dir()
    assert steps_root.is_dir(), "must never remove steps/ itself"


# ── gatekeeper, at land time ───────────────────────────────────────────────
def test_prune_never_escapes_steps_root(tmp_path):
    """THE LOAD-BEARING CASE. `_prune_stale_folders` reads its folder list from
    a PRIOR index.json — a file on disk, not a value the call computed — and it
    DELETES.

    Measured before the guard: a list entry of `../../OUTSIDE` made
    `steps_root / rel` resolve outside the project, and the loop unlinked a
    symlink and an `outputs.json` in an unrelated directory and then rmdir'd
    it. The unlink is bounded to symlinks and `outputs.json`, but bounded
    damage is still damage, and deletion code does not get to assume its input
    is well formed.
    """
    import step_output_collector as C

    outside = tmp_path / "OUTSIDE"
    outside.mkdir()
    (tmp_path / "real.txt").write_text("x")
    (outside / "link").symlink_to(tmp_path / "real.txt")
    (outside / "outputs.json").write_text("{}")

    steps_root = tmp_path / "proj" / "steps"
    steps_root.mkdir(parents=True)

    C._prune_stale_folders(steps_root, ["../../OUTSIDE"], set())

    assert outside.is_dir(), "an escaping entry deleted a directory outside the project"
    assert sorted(p.name for p in outside.iterdir()) == ["link", "outputs.json"]


def test_history_retention_keeps_a_stale_folder_and_manifest(tmp_path):
    """The paired half, and the one that keeps the guard from being a way to
    disable the feature: a stale folder INSIDE steps_root must still go, and
    its now-empty phase/stage parents with it. That is the flat-to-nested
    migration this change exists to make survivable."""
    import step_output_collector as C

    steps_root = tmp_path / "steps"
    stale = steps_root / "phase1" / "stage1" / "01_old_name"
    stale.mkdir(parents=True)
    (tmp_path / "target.txt").write_text("x")
    (stale / "artifact.v").symlink_to(tmp_path / "target.txt")
    (stale / "outputs.json").write_text("{}")

    C._prune_stale_folders(steps_root, ["phase1/stage1/01_old_name"], set())

    assert stale.is_dir()
    assert (stale / "artifact.v").is_file()
    assert (stale / "outputs.json").read_text() == "{}"
    assert (steps_root / "phase1/stage1").is_dir()
    assert (tmp_path / "target.txt").is_file(), "the symlink TARGET was deleted"


def test_prune_keeps_a_folder_the_current_run_still_produces(tmp_path):
    """A folder in both the prior and the current set is not stale."""
    import step_output_collector as C

    steps_root = tmp_path / "steps"
    keep = steps_root / "phase2" / "stage1" / "07_rtl"
    keep.mkdir(parents=True)
    (keep / "outputs.json").write_text("{}")

    C._prune_stale_folders(steps_root, ["phase2/stage1/07_rtl"],
                           {"phase2/stage1/07_rtl"})
    assert keep.is_dir() and (keep / "outputs.json").is_file()
