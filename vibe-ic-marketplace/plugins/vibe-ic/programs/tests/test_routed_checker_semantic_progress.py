"""The four routed receipt checkers prove finite input work, not activity."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import functools  # noqa: E402  (below the sys.path bootstrap, like the rest)

import _session_floor as _floor  # noqa: E402
import _routed_checker_progress as R
import _semantic_child_progress as S
import drc_vacuous_pass_check as DRC
import macro_obs_geometry_intersect_check as MACRO
import repo_hygiene_parallel as P
import step_internal_fail_bubble_up_check as BUBBLE
import tool_diagnostic_id_gate as TOOL


# ── the stall window is MEASURED on this host, not written down ────────────
#
# MEASURED on live main 7903c1972305 (2026-09-03, pinned image
# sha256:66c33ff2..., host load 34):
#
#     python3 -c "pass"                                     0.031 - 0.042 s
#     python3 -c "from _semantic_child_progress import ..."  0.100 - 0.105 s
#
# The forward-progress lease starts at SPAWN, so the first checkpoint cannot
# arrive before the interpreter has started AND that import has finished. The
# arm below hard-coded `stall_grace_s=0.09` — already SHORTER than the
# measured start on this host — and its child then slept a further 0.04 s
# before checkpointing. It was measuring the machine, and it failed on this
# one at load 23.8.
#
# `_session_floor` already landed this repair for four other files
# (`fc32402c88` / `0005a20b59`), and its docstring records the same shape:
# windows of 0.25-0.50 s "killed before pytest existed", flipping colour with
# host load. THIS FILE WAS NOT CONVERTED.
#
# ITS NUMBER IS NOT REUSED, AND THAT IS MEASURED TOO. `_session_floor`
# calibrates a PYTEST SESSION; the children here are bare interpreters. On the
# same host, same moment: `trivial_session_s()` = 1.515 s, so
# `stall_window(0.09)` = 3.031 s — a 30x over-estimate for this shape, and
# WORSE THAN WRONG: the kill-direction arm in this same file drives children
# that live 3 s, so a 3.03 s window would stop that arm from ever killing
# anything and the guard would silently stop saying no. The calibration below
# measures THIS file's child shape, and `FLOOR_MULTIPLE` is taken from
# `_session_floor` rather than re-typed.
_CHILD_PROBE = "from _semantic_child_progress import child_progress"


@functools.lru_cache(maxsize=None)
def _child_start_s() -> float:
    """Spawn-to-exit of a child of THIS file's shape, in seconds.

    The larger of two consecutive measurements, mirroring
    `_session_floor.trivial_session_s`: one lucky start must not set the floor
    for the whole file.
    """
    def once() -> float:
        started = time.monotonic()
        subprocess.run([sys.executable, "-c", _CHILD_PROBE],
                       cwd=str(Path(__file__).resolve().parent.parent),
                       env=_env(), capture_output=True)
        return time.monotonic() - started
    return max(once() for _ in range(2))


def _stall_window(nominal: float) -> float:
    """`nominal`, lifted to what THIS host's child start-up actually needs."""
    return max(float(nominal), _floor.FLOOR_MULTIPLE * _child_start_s())


def test_the_derived_stall_window_still_separates_the_two_directions():
    """PREMISE for every arm below, and the reason the lift is bounded.

    A window derived upward is only useful while it stays far below the life
    of the children the KILL arms drive (3 s of silence / chatter / a busy
    loop). If a host is so slow that the two collide, this says so instead of
    letting the kill arms pass for the wrong reason.
    """
    window = _stall_window(0.1)
    assert window >= 0.1
    assert window < 1.0, (
        f"the measured child start-up on this host lifts the stall window to "
        f"{window:.3f}s; the kill-direction arms drive children that live 3s, "
        f"and a window this close to that stops those arms discriminating. "
        f"child start = {_child_start_s():.3f}s")


PROGRAMS = Path(__file__).resolve().parents[1]
CHECKERS = (MACRO, DRC, BUBBLE, TOOL)


def _env() -> dict[str, str]:
    env = dict(os.environ)
    for key in S.ENV_KEYS:
        env.pop(key, None)
    old = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(PROGRAMS) + (os.pathsep + old if old else "")
    return env


def _commit(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.test"],
        check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "routed fixture"],
        check=True)


@pytest.fixture
def routed_cell(tmp_path: Path) -> Path:
    root = tmp_path / "benchmark-data"
    cell = root / "ic" / "demo" / "v1.0.0_pdkX"
    (cell / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (cell / "input" / "pdk").mkdir(parents=True)
    (cell / "reports" / "phase3").mkdir(parents=True)
    (cell / "reports" / "phase2").mkdir(parents=True)
    (cell / "reports" / "orchestrator").mkdir(parents=True)
    (cell / "phase3" / "stage3" / "pnr" / "routed.def").write_text(
        """VERSION 5.8 ;
UNITS DISTANCE MICRONS 1000 ;
COMPONENTS 1 ;
- u0 RAM + PLACED ( 1000 1000 ) N ;
END COMPONENTS
SPECIALNETS 1 ;
- VDD + ROUTED M1 100 ( 0 0 ) ( 500 0 ) ;
END SPECIALNETS
NETS 1 ;
END NETS
END DESIGN
""", encoding="utf-8")
    (cell / "input" / "pdk" / "ram.lef").write_text(
        """MACRO RAM
  SIZE 10 BY 10 ;
  OBS
    LAYER M1 ;
      RECT 2 2 4 4 ;
  END
END RAM
""", encoding="utf-8")
    (cell / "reports" / "phase3" / "drc_signoff.rpt").write_text(
        "DRC violations: 0\n2 shapes checked\n[WARNING ABC-0001] demo\n",
        encoding="utf-8")
    (cell / "reports" / "phase2" / "gate.json").write_text(
        '{"verdict":"PASS","pdk":"pdkX"}\n', encoding="utf-8")
    (cell / "reports" / "orchestrator" / "run.json").write_text(
        '{"verdict":"PASS","failed_gates":[]}\n', encoding="utf-8")
    (cell / "waivers.json").write_text(
        '{"_doc":"fixture","waived_steps":[]}\n', encoding="utf-8")
    _commit(root)
    return cell


def _argv(module, cell: Path) -> list[str]:
    return [sys.executable, str(Path(module.__file__)), str(cell)]


@pytest.mark.parametrize("module", CHECKERS,
                         ids=("macro", "drc", "bubble", "diagnostic"))
def test_real_checker_rc_and_output_are_identical_under_semantic_parent(
        routed_cell: Path, module):
    argv = _argv(module, routed_cell)
    ordinary = subprocess.run(
        argv, cwd=PROGRAMS, env=_env(), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True)
    units = module.semantic_progress_units(routed_cell)
    assert units[0].startswith("population:")
    assert units[-1] == "decision:computed"
    assert len(units) == len(set(units))
    rc, body, problem = P._run(
        argv, PROGRAMS, _env(), stall_grace_s=5,
        semantic_progress_scope=module.PROGRESS_SCOPE,
        semantic_progress_units=units)
    assert (rc, problem) == (ordinary.returncode, None), (rc, body, problem)
    assert body == ordinary.stdout


def test_macro_duplicate_master_keeps_historical_lef_order_under_semantics(
        routed_cell: Path):
    root = routed_cell.parents[2]
    routed = routed_cell / "phase3" / "stage3" / "pnr" / "routed.def"
    routed.write_text(
        """VERSION 5.8 ;
UNITS DISTANCE MICRONS 1000 ;
COMPONENTS 1 ;
- u0 RAM + PLACED ( 1000 1000 ) N ;
END COMPONENTS
SPECIALNETS 1 ;
- VDD + ROUTED M1 100 ( 0 4000 ) ( 10000 4000 ) ;
END SPECIALNETS
NETS 0 ;
END NETS
END DESIGN
""", encoding="utf-8")
    legacy = routed_cell / "input" / "pdk" / "ram.lef"
    legacy.write_text(
        """MACRO RAM
  SIZE 10 BY 10 ;
  OBS
    LAYER M1 ;
      RECT 2 2 4 4 ;
  END
END RAM
""", encoding="utf-8")
    appended = routed_cell / "aaa" / "override.lef"
    appended.parent.mkdir()
    appended.write_text(
        """MACRO RAM
  SIZE 10 BY 10 ;
  OBS
    LAYER M1 ;
      RECT 2 7 4 8 ;
  END
END RAM
""", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "duplicate macro master"],
        check=True)

    expected_order = [legacy, appended]
    assert MACRO._default_macro_lef_population(routed_cell) == expected_order
    argv = _argv(MACRO, routed_cell)
    ordinary = subprocess.run(
        argv, cwd=PROGRAMS, env=_env(), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True)
    units = MACRO.semantic_progress_units(routed_cell)
    rc, body, problem = P._run(
        argv, PROGRAMS, _env(), stall_grace_s=5,
        semantic_progress_scope=MACRO.PROGRESS_SCOPE,
        semantic_progress_units=units)
    assert (rc, problem) == (ordinary.returncode, None), (rc, body, problem)
    assert body == ordinary.stdout


def test_same_size_change_between_parent_plan_and_child_is_norecord(
        routed_cell: Path, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.02)
    units = DRC.semantic_progress_units(routed_cell)
    report = routed_cell / "reports" / "phase3" / "drc_signoff.rpt"
    original = report.read_bytes()
    replacement = original.replace(b"ABC-0001", b"XYZ-9999")
    assert len(replacement) == len(original)
    report.write_bytes(replacement)
    rc, body, problem = P._run(
        _argv(DRC, routed_cell), PROGRAMS, _env(), stall_grace_s=0.2,
        semantic_progress_scope=DRC.PROGRESS_SCOPE,
        semantic_progress_units=units)
    assert rc == 2, (rc, body, problem)
    assert problem and "SEMANTIC_PROGRESS_NORECORD" in problem
    assert "[PASS]" not in body


def test_untracked_relevant_input_refuses_the_parent_manifest(routed_cell: Path):
    planted = routed_cell / "reports" / "untracked.json"
    planted.write_text('{"verdict":"FAIL"}\n', encoding="utf-8")
    with pytest.raises(S.ProgressProtocolError, match="Git index and working tree"):
        BUBBLE.semantic_progress_units(routed_cell)


def test_tracked_symlink_input_refuses_before_launch(tmp_path: Path):
    root = tmp_path / "benchmark-data"
    cell = root / "ic" / "demo" / "v1.0.0_pdkX"
    reports = cell / "reports" / "phase3"
    reports.mkdir(parents=True)
    target = reports / "target.txt"
    target.write_text("DRC violations: 0\n", encoding="utf-8")
    (reports / "drc.rpt").symlink_to("target.txt")
    _commit(root)
    with pytest.raises(S.ProgressProtocolError, match="non-regular mode|symlink"):
        DRC.semantic_progress_units(cell)


def test_git_population_failure_is_norecord_evidence_not_empty(
        routed_cell: Path, monkeypatch):
    real = R.subprocess.run

    def fail_git(argv, **kwargs):
        if argv[:2] == ["git", "-C"]:
            return subprocess.CompletedProcess(argv, 77, b"", b"index unavailable")
        return real(argv, **kwargs)

    monkeypatch.setattr(R.subprocess, "run", fail_git)
    with pytest.raises(S.ProgressProtocolError, match="returned 77"):
        MACRO.semantic_progress_units(routed_cell)


def test_ambient_git_index_override_cannot_replace_checkout_authority(
        routed_cell: Path, tmp_path: Path, monkeypatch):
    root = routed_cell.parents[2]
    canonical = R.IndexSnapshot(routed_cell).relative_paths
    alternate = tmp_path / "alternate.index"
    foreign = root / "foreign.def"
    foreign.write_text("END DESIGN\n", encoding="utf-8")
    alternate_env = dict(os.environ)
    alternate_env["GIT_INDEX_FILE"] = str(alternate)
    subprocess.run(
        ["git", "-C", str(root), "read-tree", "--empty"],
        check=True, env=alternate_env)
    subprocess.run(
        ["git", "-C", str(root), "add", "foreign.def"],
        check=True, env=alternate_env)
    foreign.unlink()

    monkeypatch.setenv("GIT_INDEX_FILE", str(alternate))
    observed = R.IndexSnapshot(routed_cell).relative_paths
    assert observed == canonical
    assert "foreign.def" not in observed


def test_ambient_path_cannot_replace_git_population_authority(
        routed_cell: Path, tmp_path: Path, monkeypatch):
    canonical = R.IndexSnapshot(routed_cell).relative_paths
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text("#!/bin/sh\nexit 91\n", encoding="utf-8")
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))

    assert R.IndexSnapshot(routed_cell).relative_paths == canonical


def test_tool_predecessor_owner_population_changes_manifest(
        routed_cell: Path):
    before = TOOL.semantic_progress_units(routed_cell)
    root = routed_cell.parents[2]
    predecessor = routed_cell.parent / "v0.9.0_pdkX"
    predecessor.mkdir()
    (predecessor / "marker.txt").write_text("tracked owner\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "add predecessor owner"],
        check=True)
    after = TOOL.semantic_progress_units(routed_cell)

    assert len(before) == len(after)
    assert before != after
    assert before[0].startswith("population:tool-diagnostic:design-index:")
    assert after[0].startswith("population:tool-diagnostic:design-index:")


def test_transient_hidden_tool_directory_cannot_change_cached_decision(
        routed_cell: Path, capsys):
    root = routed_cell.parents[2]
    previous = routed_cell.parent / "v0.9.0_pdkX"
    (previous / "reports" / "phase3").mkdir(parents=True)
    (previous / "reports" / "phase2").mkdir(parents=True)
    current_report = routed_cell / "reports" / "phase3" / "drc_signoff.rpt"
    (previous / "reports" / "phase3" / "drc_signoff.rpt").write_bytes(
        current_report.read_bytes())
    (previous / "reports" / "phase2" / "gate.json").write_text(
        '{"verdict":"PASS","pdk":"pdkX"}\n', encoding="utf-8")
    transient = routed_cell / "reports" / "transient"
    transient.mkdir()
    (transient / "new.log").write_text(
        "[ERROR ZZZ-9999] newly emitted\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "add diagnostic pair"],
        check=True)

    plan, owners, canonical_cell = TOOL._input_plan(routed_cell)

    class Recorder:
        def __init__(self):
            self.units = []

        def checkpoint(self, unit):
            self.units.append(unit)

    recorder = Recorder()
    plan.materialize(recorder)
    acceptance = Path(TOOL.__file__).with_name(
        "tool_diagnostic_id_acceptance.json")
    args = SimpleNamespace(
        cell_dir=str(routed_cell), acceptance=str(acceptance), json=None,
        census_only=False, previous=None, emit_metrics=None, today=None)
    hidden = routed_cell / "reports" / "transient.hidden"
    TOOL._ACTIVE_INPUT_PLAN = plan
    TOOL._ACTIVE_OWNER_PATHS = owners
    TOOL._ACTIVE_CELL_ROOT = canonical_cell
    try:
        present_rc = TOOL._main_parsed(args)
        present_output = capsys.readouterr()
        transient.rename(hidden)
        hidden_rc = TOOL._main_parsed(args)
        hidden_output = capsys.readouterr()
        hidden.rename(transient)
        fresh, _, _ = TOOL._input_plan(routed_cell)
        assert fresh.units == plan.units
        plan.checkpoint_decision(fresh_plan=fresh)
    finally:
        if hidden.exists() and not transient.exists():
            hidden.rename(transient)
        TOOL._ACTIVE_INPUT_PLAN = None
        TOOL._ACTIVE_OWNER_PATHS = None
        TOOL._ACTIVE_CELL_ROOT = None

    assert present_rc == hidden_rc == 1
    assert hidden_output == present_output
    assert recorder.units[-1] == "decision:computed"


def test_malformed_gds_cannot_fall_back_to_a_path_reopening_parser(
        routed_cell: Path):
    root = routed_cell.parents[2]
    bad_gds = routed_cell / "phase3" / "stage3" / "pnr" / "broken.gds.gz"
    bad_gds.write_bytes(b"not a gzip stream")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "add malformed GDS"],
        check=True)
    units = DRC.semantic_progress_units(routed_cell)
    rc, body, problem = P._run(
        _argv(DRC, routed_cell), PROGRAMS, _env(), stall_grace_s=1,
        semantic_progress_scope=DRC.PROGRESS_SCOPE,
        semantic_progress_units=units)
    assert rc == 2, (rc, body, problem)
    assert problem and "SEMANTIC_PROGRESS_NORECORD" in problem
    assert "decision:computed" not in problem


def test_cross_checkout_acceptance_inode_is_not_normalised_into_progress(
        tmp_path: Path, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.01)
    plans = []
    for checkout_name in ("base-programs", "candidate-programs"):
        programs = tmp_path / checkout_name
        programs.mkdir()
        acceptance = programs / "tool_diagnostic_id_acceptance.json"
        acceptance.write_text('{"schema":1,"accepted":[]}\n',
                              encoding="utf-8")
        _commit(programs)
        snapshot = R.IndexSnapshot(programs)
        tracked = snapshot.select(
            lambda relative: relative == acceptance.name, [acceptance],
            population="cross-checkout acceptance")
        plans.append(R.FiniteInputPlan(
            [snapshot.population_unit(
                "tool-diagnostic:acceptance-index")],
            R.planned_reads("acceptance", tracked)))
    base_units, candidate_units = plans[0].units, plans[1].units
    assert len(base_units) == len(candidate_units)
    assert base_units != candidate_units, (
        "separate checkout inodes were accidentally normalised away")
    source = f"""
import time
from _semantic_child_progress import child_progress
units = {candidate_units!r}
with child_progress({TOOL.PROGRESS_SCOPE!r}) as progress:
    for unit in units:
        progress.checkpoint(unit)
        time.sleep(.02)
"""
    rc, output, problem = P._run(
        [sys.executable, "-c", source], tmp_path, _env(),
        stall_grace_s=0.2,
        semantic_progress_scope=TOOL.PROGRESS_SCOPE,
        semantic_progress_units=base_units)
    assert rc == 2, (rc, output, problem)
    assert problem and "SEMANTIC_PROGRESS_NORECORD" in problem
    assert "outcome=aborted" in problem


def test_slow_exact_checker_manifest_relays_past_one_stall_window(
        routed_cell: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.01)
    units = MACRO.semantic_progress_units(routed_cell)
    observed = []
    # THE RATIO IS WHAT THIS ARM ASSERTS, so the cadence scales WITH the
    # window and keeps it: the child checkpointed every 0.04 s against a
    # 0.09 s window, i.e. it renewed the lease at 4/9 of it, twice over.
    window = _stall_window(0.09)
    step = window * (0.04 / 0.09)
    source = f"""
import time
from _semantic_child_progress import child_progress
units = {units!r}
with child_progress({MACRO.PROGRESS_SCOPE!r}) as progress:
    for unit in units:
        time.sleep({step!r})
        progress.checkpoint(unit)
"""
    started = time.monotonic()
    rc, body, problem = P._run(
        [sys.executable, "-c", source], tmp_path, _env(),
        stall_grace_s=window,
        semantic_progress_scope=MACRO.PROGRESS_SCOPE,
        semantic_progress_units=units,
        domain_progress_callback=lambda *event: observed.append(event))
    elapsed = time.monotonic() - started
    assert elapsed > window
    assert (rc, problem) == (0, None), (rc, body, problem)
    assert observed == [
        (MACRO.PROGRESS_SCOPE, completed, len(units))
        for completed in range(1, len(units) + 1)]


@pytest.mark.parametrize("body", [
    "import time; time.sleep(3)",
    "import time\nwhile True:\n print('chat', flush=True); time.sleep(.005)",
    "import time\nend=time.monotonic()+3\nwhile time.monotonic()<end: pass",
])
def test_silent_chatty_and_busy_activity_cannot_renew_checker_manifest(
        routed_cell: Path, tmp_path: Path, monkeypatch, body: str):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.01)
    units = MACRO.semantic_progress_units(routed_cell)
    rc, output, problem = P._run(
        [sys.executable, "-c", body], tmp_path, _env(),
        # THE SAME DERIVED WINDOW as the relay arm. If the kill direction kept
        # a hard-coded window while the relay direction was lifted, the pair
        # would stop being comparable and only the half that must SURVIVE
        # would have been made robust — which is how a guard stops saying no.
        stall_grace_s=_stall_window(0.1),
        semantic_progress_scope=MACRO.PROGRESS_SCOPE,
        semantic_progress_units=units)
    assert rc == 2, (rc, output, problem)
    assert problem and "SEMANTIC_PROGRESS_NORECORD" in problem
    assert "outcome=stalled" in problem


def test_forged_nonce_cannot_renew_checker_manifest(
        routed_cell: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.01)
    units = MACRO.semantic_progress_units(routed_cell)
    source = f"""
import json,os,time
path = os.environ[{S.ENV_PATH!r}]
row = {{'schema': 1, 'nonce': '0' * 64, 'pid': os.getpid(),
       'seq': 0, 'state': 'start', 'scope': {MACRO.PROGRESS_SCOPE!r},
       'total': {len(units)}}}
with open(path, 'a', encoding='utf-8') as stream:
    stream.write(json.dumps(row, sort_keys=True, separators=(',', ':'))+'\\n')
    stream.flush()
time.sleep(3)
"""
    rc, output, problem = P._run(
        [sys.executable, "-c", source], tmp_path, _env(),
        stall_grace_s=0.12,
        semantic_progress_scope=MACRO.PROGRESS_SCOPE,
        semantic_progress_units=units)
    assert rc == 2, (rc, output, problem)
    assert problem and "SEMANTIC_PROGRESS_NORECORD" in problem
    assert "outcome=aborted" in problem


@pytest.mark.parametrize("mode", ["out-of-order", "duplicate", "no-terminal"])
def test_malformed_order_duplicate_and_missing_terminal_are_norecord(
        routed_cell: Path, tmp_path: Path, monkeypatch, mode: str):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.01)
    units = MACRO.semantic_progress_units(routed_cell)
    if mode == "out-of-order":
        statements = f"progress.checkpoint({units[1]!r}); time.sleep(3)"
    elif mode == "duplicate":
        statements = (
            f"progress.checkpoint({units[0]!r}); "
            f"progress.checkpoint({units[0]!r})")
    else:
        statements = (
            "\n".join(f"progress.checkpoint({unit!r})" for unit in units)
            + "\nos._exit(0)")
    source = f"""
import os,time
from _semantic_child_progress import child_progress
progress = child_progress({MACRO.PROGRESS_SCOPE!r})
progress.__enter__()
{statements}
"""
    rc, output, problem = P._run(
        [sys.executable, "-c", source], tmp_path, _env(),
        stall_grace_s=0.12,
        semantic_progress_scope=MACRO.PROGRESS_SCOPE,
        semantic_progress_units=units)
    assert rc == 2, (rc, output, problem)
    assert problem and "SEMANTIC_PROGRESS_NORECORD" in problem
