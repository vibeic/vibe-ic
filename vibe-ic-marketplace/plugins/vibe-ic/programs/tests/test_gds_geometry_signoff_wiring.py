"""Pins the landing of the KLayout-fork GDS-geometry sign-off capability.

Two things are pinned, and they fail for different reasons:

  * WIRING — the flow must actually be able to REACH the programs. A capability
    that exists but no flow step invokes is indistinguishable from one that was
    never built; that is exactly the state these programs were rescued from.
  * HONEST DEGRADATION — when the checker cannot run, the gate must emit a
    NAMED, DISCLOSED skip (rc 2 + the `VACUOUS_PASS:` sentinel), never rc 0. A
    step that passes because the checker did not run is a false PASS.

The tests that need real geometry drive the actual KLayout engine (no mocks) and
skip cleanly where no KLayout runner exists, so CI without the EDA container
stays green without ever asserting a fake pass. Fixtures are SYNTHETIC and their
antenna ratios are HAND-COMPUTED — no PDK or foundry data is involved.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
FLOW_YAML = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
ANTENNA_GATE = PROGRAMS / "gds_antenna_deck_check.py"
FILL_GATE = PROGRAMS / "metal_fill_emit.py"

sys.path.insert(0, str(PROGRAMS))
import _klayout_launch as klaunch  # noqa: E402

# The antenna fixture is a poly gate of area 1.0 um^2 joined to a met1 wire
# 0.5 um wide and L um long, so ratio = 0.5*L. These are the hand-computed
# values the engine must reproduce exactly.
VIOLATION_LEN_UM, VIOLATION_RATIO = 100.0, 50.0
CLEAN_LEN_UM, CLEAN_RATIO = 20.0, 10.0
DECK_LIMIT = 40.0


# ---------------------------------------------------------------------------
# WIRING — reachable from the flow
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def flow():
    return yaml.safe_load(FLOW_YAML.read_text())


def _step(flow, step_id):
    for s in flow["steps"]:
        if s.get("id") == step_id:
            return s
    raise AssertionError(f"step {step_id} missing from the flow")


def _gate_commands(gate):
    """Every program command reachable under a gate spec, at any nesting."""
    out = []
    if isinstance(gate, dict):
        for key, val in gate.items():
            if key in ("program_exit_zero", "optional_program_exit_zero"):
                out.append(val["command"] if isinstance(val, dict) else val)
            else:
                out.extend(_gate_commands(val))
    elif isinstance(gate, list):
        for item in gate:
            out.extend(_gate_commands(item))
    return out


def test_programs_exist():
    assert ANTENNA_GATE.is_file()
    assert FILL_GATE.is_file()


def test_engines_are_vendored():
    """A clean install must reach the capability with no container re-image."""
    for sub, name in (("gds_antenna", "antenna_check.py"),
                      ("gds_antenna", "xcheck_router.py"),
                      ("metal_fill", "metal_fill.py")):
        assert klaunch.find_engine(sub, name) is not None, \
            f"{sub}/{name} not resolvable"


def test_antenna_deck_is_wired_into_the_antenna_step(flow):
    cmds = _gate_commands(_step(flow, 26)["gate"])
    assert any(c.startswith("gds_antenna_deck_check") for c in cmds), \
        "Step 26 does not invoke the GDS-geometry antenna deck"


def test_router_report_check_is_preserved(flow):
    """The geometry deck ADDS an opinion; it must not have replaced a gate."""
    cmds = _gate_commands(_step(flow, 26)["gate"])
    assert any(c.startswith("antenna_report_check") for c in cmds), \
        "the router-report antenna gate was dropped from Step 26"


def test_density_fill_is_wired_into_the_metal_fill_step(flow):
    cmds = _gate_commands(_step(flow, 34)["gate"])
    fill = [c for c in cmds if c.startswith("metal_fill_emit")]
    assert fill, "Step 34 does not invoke the density-fill verdict"
    assert all("--verify-only" in c for c in fill), \
        "the Step-34 gate must VERIFY, never re-run the fill during an audit"


def test_existing_fill_gates_are_preserved(flow):
    cmds = _gate_commands(_step(flow, 34)["gate"])
    assert any(c.startswith("metal_fill_density_check") for c in cmds)
    assert any(c.startswith("spare_cell_preservation_check") for c in cmds)


def test_runner_invokes_the_density_fill_at_streamout():
    """The fill is an EMITTER: the runner must call it, and before sign-off."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert "def _density_metal_fill(" in src
    assert "metal_fill_emit.py" in src
    # Called on BOTH streamout paths (Magic returns early; KLayout falls through)
    assert src.count("_density_metal_fill(project, top, pdk, gds_out, container)") == 2, \
        "density fill must run on both the Magic and the KLayout streamout path"


def test_report_names_cannot_be_swallowed_by_sibling_checkers():
    """`antenna_report_check` rglobs `*antenna*.json` and
    `metal_layer_density_check` rglobs `*metal*density*.json` across the WHOLE
    project. Either would consume this capability's files as if they were its
    own input — the deck config would be read as a router antenna report that
    carries no violation count, hard-FAILing the sibling gate on any project
    that adopted the deck. CONFIG paths are as exposed as report paths."""
    import gds_antenna_deck_check as adc
    import metal_fill_emit as mfe
    antenna_names = ((adc._RAW_REPORT_NAME, adc._MATERIALISED_CFG_NAME)
                     + adc._CFG_GLOBS)
    for name in antenna_names:
        assert "antenna" not in name, f"{name} collides with *antenna*.json"
    fill_names = (mfe._REPORT_REL, mfe._MATERIALISED_CFG_NAME) + mfe._CFG_GLOBS
    for name in fill_names:
        assert not ("metal" in name and "density" in name), \
            f"{name} collides with *metal*density*.json"


def test_flow_condition_paths_match_the_programs_discovery_paths(flow):
    """A condition path the program does not itself discover would gate the
    gate on a file it then ignores — the capability would look wired and never
    actually run."""
    import gds_antenna_deck_check as adc
    import metal_fill_emit as mfe
    for step_id, mod in ((26, adc), (34, mfe)):
        gate = _step(flow, step_id)["gate"]
        conds = set()
        for item in gate["all_of"]:
            spec = item.get("optional_program_exit_zero")
            if isinstance(spec, dict) and mod.__name__ in spec["command"]:
                conds.update(spec["condition_files_exist"])
        assert conds, f"step {step_id} has no condition for {mod.__name__}"
        assert conds <= set(mod._CFG_GLOBS), \
            f"step {step_id} gates on paths {mod.__name__} never looks for"


# ---------------------------------------------------------------------------
# HONEST DEGRADATION — never a PASS the checker did not earn
# ---------------------------------------------------------------------------
def _run(prog, *args, env=None):
    """Run a gate WITH ITS CWD INSIDE THE SUBJECT, never inside this checkout.

    Every call here passes the project directory as the gate's first argument,
    and several pass a RELATIVE `--json`. The two gates in this file disagree
    about what such a path is relative to: `gds_antenna_ratio_check` resolves it
    against the project (which is why `_verdict` reads `proj/out.json` and
    passes), while `antenna_report_check` resolves it against the CURRENT
    WORKING DIRECTORY. With no `cwd=`, that directory is `programs/`, so
    `--json reports/phase3/antenna.json` wrote into THIS REPOSITORY —
    `programs/reports/phase3/antenna.json`, a tracked file whose only reason to
    exist was this accident, and which nothing reads.

    It went unnoticed for as long as the bytes it produced happened to equal the
    bytes already committed there; the first change to any gate's verdict
    document made `suite_write_guard` fail with
    `WROTE INTO THE TREE — 1 path(s)`. Anchoring cwd to the subject fixes every
    call in this file at once, and is the reason a new one cannot reintroduce
    it. The gates' disagreement about relative `--json` is NOT fixed here: the
    flow always invokes them with `.` as the project and the project as cwd, so
    the two resolutions coincide there, and changing one of them is a separate
    change with its own blast radius.
    """
    full = dict(os.environ, **(env or {}))
    subject = Path(str(args[0])) if args else None
    cwd = str(subject) if subject is not None and subject.is_dir() else None
    return subprocess.run([sys.executable, str(prog), *map(str, args)],
                          capture_output=True, text=True, env=full, timeout=60,
                          cwd=cwd)


@pytest.mark.parametrize("prog", [ANTENNA_GATE, FILL_GATE])
def test_absent_checker_is_a_disclosed_skip_not_a_pass(prog, tmp_path):
    """The load-bearing negative: with the checker forced absent, a project
    that DOES violate must NOT come back rc 0."""
    (tmp_path / "signoff").mkdir()
    (tmp_path / "signoff" / "gate_oxide_deck.json").write_text("{}")
    (tmp_path / "signoff" / "cmp_fill_targets.json").write_text("{}")
    gds = tmp_path / "phase3" / "stage4" / "gds"
    gds.mkdir(parents=True)
    (gds / "top.gds").write_bytes(b"\x00" * 64)
    cp = _run(prog, tmp_path, env={"VIBEIC_KLAYOUT_FORCE_ABSENT": "1"})
    assert cp.returncode == 2, f"expected disclosed skip, got rc={cp.returncode}"
    assert "VACUOUS_PASS:" in cp.stdout
    assert "did NOT run" in cp.stdout
    # The reason must NAME what was missing, not just say "skipped".
    assert "KLayout" in cp.stdout


@pytest.mark.parametrize("prog", [ANTENNA_GATE, FILL_GATE])
def test_strict_turns_a_disclosed_skip_into_a_failure(prog, tmp_path):
    (tmp_path / "signoff").mkdir()
    (tmp_path / "signoff" / "gate_oxide_deck.json").write_text("{}")
    (tmp_path / "signoff" / "cmp_fill_targets.json").write_text("{}")
    gds = tmp_path / "phase3" / "stage4" / "gds"
    gds.mkdir(parents=True)
    (gds / "top.gds").write_bytes(b"\x00" * 64)
    cp = _run(prog, tmp_path, "--strict",
              env={"VIBEIC_KLAYOUT_FORCE_ABSENT": "1"})
    assert cp.returncode == 1


def test_undeclared_deck_is_named_in_the_skip_reason(tmp_path):
    cp = _run(ANTENNA_GATE, tmp_path)
    assert cp.returncode == 2
    assert "no antenna deck config declared" in cp.stdout


def test_fill_verify_only_without_a_prior_emit_is_disclosed(tmp_path):
    cp = _run(FILL_GATE, tmp_path, "--verify-only")
    assert cp.returncode == 2
    assert "has not run on this project" in cp.stdout


def test_flow_compliance_forwards_an_optional_gates_disclosed_skip():
    """An OPTIONAL gate signals the disclosed-skip tier by EXIT CODE, at which
    point `_check_program_exit_zero` has already replaced the snippet with the
    `__VACUOUS_HINT__:` marker — so the stdout-token test can no longer see it
    and the disclosure was being downgraded to a bare pass."""
    src = (PROGRAMS / "flow_compliance_check.py").read_text()
    optional = src.split("if \"optional_program_exit_zero\" in gate:", 1)[1]
    optional = optional.split("# `all_of`", 1)[0]
    assert "out.startswith(_VACUOUS_HINT_PREFIX)" in optional


# ---------------------------------------------------------------------------
# REAL GEOMETRY — needs a KLayout runner AND a path it can reach
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def runner():
    r = klaunch.find_runner()
    if r is None:
        pytest.skip("no KLayout runner (host or EDA container)")
    return r


def _tree_unreachable_reason(runner):
    """Why can this runner not drive the vendored engines from THIS tree?

    Returns a reason string, or None when the tree is reachable.

    The scratch dir is not the only path that must be inside the runner's
    mounts — the ENGINE SCRIPTS must be too. A container runner opens them by
    HOST path, so a tree it does not cover fails with

        ERROR: Unable to open file: /tmp/.../metal_fill/gen_fixtures.py (errno=2)

    on the SCRIPT, before the output path is ever consulted. That matters
    because it makes the failure un-rescuable by scratch-dir choice: picking a
    covered scratch (e.g. under $HOME, the sole mount of `vibeic-eda`) converts
    seven honest skips into seven FALSE FAILURES, which is strictly worse than
    not running them. Diagnose the tree, do not re-home the output.
    """
    if not runner.covers(PROGRAMS):
        return (
            f"the KLayout runner covers no path containing this tree, so it "
            f"cannot read the vendored engines under {PROGRAMS} (a container "
            f"opens them by host path). This is a property of WHERE THIS TREE "
            f"SITS, not of the host: the same runner passes these tests from a "
            f"covered checkout. Re-run from a covered path — choosing a "
            f"different scratch dir cannot fix it.")
    return None


@pytest.fixture(scope="module")
def workdir(runner, tmp_path_factory):
    """A scratch dir the runner can actually see.

    pytest's tmp_path lives under /tmp, which the EDA container does not bind
    mount, so container runs would fail on an unreachable path. Fall back to a
    dir beside the plugin — which is inside the mounted tree only when the
    CHECKOUT is, so the tree itself is checked first and named as the cause.
    """
    reason = _tree_unreachable_reason(runner)
    if reason:
        pytest.skip(reason)
    cand = tmp_path_factory.mktemp("geomsignoff")
    if runner.covers(cand):
        return cand
    local = PLUGIN.parent.parent / "scratch_geom_signoff_tests"
    local.mkdir(parents=True, exist_ok=True)
    if not runner.covers(local):
        pytest.skip("no scratch dir reachable by the KLayout runner")
    return local


class _FakeRunner:
    """Covers exactly the prefixes it is given. No container required."""

    def __init__(self, covered):
        self._covered = [str(Path(p)) for p in covered]

    def covers(self, host_path):
        return any(str(Path(host_path)).startswith(c) for c in self._covered)


def test_a_tree_outside_every_mount_is_named_as_the_cause():
    reason = _tree_unreachable_reason(_FakeRunner([]))
    assert reason is not None
    assert str(PROGRAMS) in reason, "the reason must name the unreachable tree"
    assert "WHERE THIS TREE SITS" in reason


def test_a_covered_tree_is_not_reported_unreachable():
    assert _tree_unreachable_reason(_FakeRunner([PROGRAMS])) is None


def test_a_covered_scratch_does_not_rescue_an_unreachable_tree():
    """The trap this guard exists for, measured 2026-08-13 on 8HD-9.

    `vibeic-eda` binds exactly one path, $HOME. A worktree under /tmp is
    therefore uncovered while $HOME is covered — so "find a scratch dir the
    runner covers" succeeds and the seven geometry tests then FAIL on the
    unreadable engine script instead of skipping. Same host, same commit:
    26 passed from a covered checkout, 19 passed + 7 skipped from /tmp.
    """
    runner = _FakeRunner([Path.home()])
    if runner.covers(PROGRAMS):
        pytest.skip("this tree is inside $HOME, so it is not the trap case")
    assert runner.covers(Path.home() / ".cache"), "premise: scratch IS covered"
    assert _tree_unreachable_reason(runner) is not None, \
        "a covered scratch must not be mistaken for a reachable tree"


def _antenna_project(runner, workdir, name, met1_len, met2_len=0.0,
                     diode=False, diode_offnet=False, deck="antenna_config"):
    proj = workdir / name
    if proj.exists():
        import shutil
        shutil.rmtree(proj)
    (proj / "phase3" / "stage4" / "gds").mkdir(parents=True)
    (proj / "signoff").mkdir(parents=True)
    (proj / "signoff" / "gate_oxide_deck.json").write_text(
        (PROGRAMS / "gds_antenna" / f"{deck}.example.json").read_text())
    gen = PROGRAMS / "gds_antenna" / "gen_fixtures.py"
    env = {"ANT_OUT": str(proj / "phase3" / "stage4" / "gds" / "top.gds"),
           "ANT_LEN": str(met1_len), "ANT_MET2_LEN": str(met2_len),
           "ANT_DIODE": "1" if diode else "0",
           "ANT_DIODE_OFFNET": "1" if diode_offnet else "0"}
    rc, out, err = runner.run(gen, env, path_keys=("ANT_OUT",), timeout=60)
    gds = proj / "phase3" / "stage4" / "gds" / "top.gds"
    assert gds.is_file() and gds.stat().st_size > 0, \
        f"fixture generation failed: rc={rc} {err[-400:]}"
    return proj


ROUTER_CLEAN_RPT = """OpenROAD v2.0 check_antennas
[INFO ANT-0002] Checking antenna rules on the routed database.
[INFO ANT-0003] Extracted antenna model from the final routed netlist
                (all metal layers present; upper-metal relief credited).
[INFO ANT] Found 0 net violations.
[INFO ANT] Found 0 pin violations.
antenna clean: YES
[INFO ANT-0009] antenna check completed.
"""


def _verdict(proj):
    return json.loads((proj / "out.json").read_text())


def test_violation_is_flagged_with_the_hand_computed_ratio(runner, workdir):
    proj = _antenna_project(runner, workdir, "viol", VIOLATION_LEN_UM)
    cp = _run(ANTENNA_GATE, proj, "--json", "out.json")
    assert cp.returncode == 1
    res = _verdict(proj)
    assert res["verdict"] == "FAIL"
    assert res["violations"] == 1
    assert res["worst_ratio"] == pytest.approx(VIOLATION_RATIO)
    assert VIOLATION_RATIO > DECK_LIMIT


def test_clean_design_passes_with_zero_violations(runner, workdir):
    """The check cannot invent a violation."""
    proj = _antenna_project(runner, workdir, "clean", CLEAN_LEN_UM)
    cp = _run(ANTENNA_GATE, proj, "--json", "out.json")
    assert cp.returncode == 0
    res = _verdict(proj)
    assert res["verdict"] == "PASS"
    assert res["violations"] == 0
    assert res["worst_ratio"] == pytest.approx(CLEAN_RATIO)


def test_geometry_deck_catches_what_the_router_report_path_misses(runner,
                                                                  workdir):
    """THE POINT OF THE SECOND OPINION.

    A met1 antenna carrying an upper-metal jumper: the router's final-netlist
    model sees the jumper and reports the net clean, so the existing
    router-report gate PASSES. The geometry deck rebuilds connectivity per etch
    STAGE — at the met1 etch the met2 jumper does not exist yet — and flags the
    violation. The cross-check turns the clean/dirty split into a hard FAIL
    instead of averaging the two counts.
    """
    proj = _antenna_project(runner, workdir, "staged", VIOLATION_LEN_UM,
                            met2_len=200.0)
    (proj / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (proj / "reports" / "phase3" / "antenna.rpt").write_text(ROUTER_CLEAN_RPT)

    router = _run(PROGRAMS / "antenna_report_check.py", proj,
                  "--json", "reports/phase3/antenna.json")
    assert router.returncode == 0, \
        "precondition: the router-report path must find this design clean"

    cp = _run(ANTENNA_GATE, proj, "--json", "out.json")
    assert cp.returncode == 1, "the geometry deck missed what the router missed"
    res = _verdict(proj)
    assert res["cross_check"]["verdict"] == "DISAGREE"
    assert "MISMATCH" in res["cross_check"]["detail"]


def test_cross_check_agrees_on_a_genuinely_clean_design(runner, workdir):
    """The cross-check must not manufacture a disagreement either."""
    proj = _antenna_project(runner, workdir, "agree", CLEAN_LEN_UM)
    (proj / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (proj / "reports" / "phase3" / "antenna.rpt").write_text(ROUTER_CLEAN_RPT)
    cp = _run(ANTENNA_GATE, proj, "--json", "out.json")
    assert cp.returncode == 0
    assert _verdict(proj)["cross_check"]["verdict"] == "AGREE"


def test_diode_on_the_net_relieves_the_antenna(runner, workdir):
    proj = _antenna_project(runner, workdir, "diode_on", VIOLATION_LEN_UM,
                            diode=True, deck="antenna_config_diode")
    cp = _run(ANTENNA_GATE, proj, "--json", "out.json")
    assert cp.returncode == 0
    assert _verdict(proj)["deck"]["diode_recognition"]["relieved_nets"] == 1


def test_diode_off_the_net_does_not_relieve(runner, workdir):
    """Relief is CONNECTIVITY-based: a diode elsewhere on the die is not a fix."""
    proj = _antenna_project(runner, workdir, "diode_off", VIOLATION_LEN_UM,
                            diode_offnet=True, deck="antenna_config_diode")
    cp = _run(ANTENNA_GATE, proj, "--json", "out.json")
    assert cp.returncode == 1
    res = _verdict(proj)
    assert res["deck"]["diode_recognition"]["relieved_nets"] == 0
    assert res["worst_ratio"] == pytest.approx(VIOLATION_RATIO)
    # and it says WHERE a diode would actually help
    assert res["deck"]["diode_recognition"]["insertion_sites"] >= 1


def test_density_fill_raises_a_sparse_layer_to_target(runner, workdir):
    proj = workdir / "fill"
    if proj.exists():
        import shutil
        shutil.rmtree(proj)
    (proj / "phase3" / "stage4" / "gds").mkdir(parents=True)
    (proj / "signoff").mkdir(parents=True)
    cfg = json.loads(
        (PROGRAMS / "metal_fill" / "fill_config.example.json").read_text())
    (proj / "signoff" / "cmp_fill_targets.json").write_text(json.dumps(cfg))
    gen = PROGRAMS / "metal_fill" / "gen_fixtures.py"
    gds = proj / "phase3" / "stage4" / "gds" / "top.gds"
    runner.run(gen, {"FILL_OUT": str(gds)}, path_keys=("FILL_OUT",), timeout=60)
    assert gds.is_file()
    before = gds.stat().st_size

    cp = _run(FILL_GATE, proj, "--in-place", "--json", "out.json")
    assert cp.returncode == 0, cp.stdout[-800:]
    res = _verdict(proj)
    assert res["verdict"] == "PASS"
    layer = res["layers"][0]
    target = cfg["layers"][0]["target"]
    assert layer["worst_window_before"] < target, \
        "precondition: the fixture layer must start BELOW the target"
    assert layer["worst_window_after"] >= target
    assert layer["reached"] is True
    assert not layer["over_max"], "fill must not overshoot the density ceiling"
    assert gds.stat().st_size > before, "the filled GDS was never written back"

    # --verify-only re-reports without re-filling
    size_after = gds.stat().st_size
    again = _run(FILL_GATE, proj, "--verify-only")
    assert again.returncode == 0
    assert gds.stat().st_size == size_after, "an audit mutated the GDS"


# ---------------------------------------------------------------------------
# $VIBEIC_KLAYOUT_TOOLS — the documented route by which a NEWER fork engine
# overrides the vendored copy.
#
# `test_engines_are_vendored` above calls find_engine with NO env var set, so it
# validates the vendored FALLBACK and never the override. The override itself
# had never been exercised, and it was broken: the KLayout fork names its engine
# directories with hyphens (`metal-fill/`, `gds-antenna/`, and likewise
# `mp-color/`, `perc-latchup/`, ...) while every caller here passes the
# underscored plugin spelling (`metal_fill`, `gds_antenna`). Pointing the
# variable at a fork checkout — which is exactly what the fork's
# plugin-wiring/README.md instructs — resolved to nothing and fell through to
# the vendored copy SILENTLY, so a maintainer who set it believed the fork
# engine was running when it was not.
# ---------------------------------------------------------------------------

def _fork_shaped_tools_root(root: Path) -> Path:
    """A tree with the fork's OWN directory spelling (hyphens)."""
    for fork_dir, name in (("metal-fill", "metal_fill.py"),
                           ("gds-antenna", "antenna_check.py"),
                           ("gds-antenna", "xcheck_router.py")):
        d = root / fork_dir
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text("# fork engine\n", encoding="utf-8")
    return root


def test_env_override_reaches_the_forks_own_directory_spelling(tmp_path, monkeypatch):
    """The documented override must resolve against a real fork checkout."""
    root = _fork_shaped_tools_root(tmp_path / "klayout-fork")
    monkeypatch.setenv("VIBEIC_KLAYOUT_TOOLS", str(root))
    for sub, fork_dir, name in (("metal_fill", "metal-fill", "metal_fill.py"),
                                ("gds_antenna", "gds-antenna", "antenna_check.py"),
                                ("gds_antenna", "gds-antenna", "xcheck_router.py")):
        got = klaunch.find_engine(sub, name)
        assert got == root / fork_dir / name, (
            f"$VIBEIC_KLAYOUT_TOOLS did not reach {fork_dir}/{name}; "
            f"find_engine returned {got}")


def test_env_override_still_prefers_the_underscored_spelling(tmp_path, monkeypatch):
    """A tools root that already uses the plugin spelling keeps working, and
    wins over the hyphenated one when both are present."""
    root = _fork_shaped_tools_root(tmp_path / "both")
    (root / "metal_fill").mkdir(parents=True)
    (root / "metal_fill" / "metal_fill.py").write_text("# exact\n", encoding="utf-8")
    monkeypatch.setenv("VIBEIC_KLAYOUT_TOOLS", str(root))
    assert klaunch.find_engine("metal_fill", "metal_fill.py") == \
        root / "metal_fill" / "metal_fill.py"


def test_env_override_that_resolves_to_nothing_is_not_silent(tmp_path, monkeypatch, capsys):
    """Falling through to the vendored copy is legitimate; doing it silently is
    not — that is what made the spelling mismatch survive."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("VIBEIC_KLAYOUT_TOOLS", str(empty))
    got = klaunch.find_engine("metal_fill", "metal_fill.py")
    assert got is not None and str(empty) not in str(got), \
        "precondition: this root carries no engine, so the vendored copy is used"
    err = capsys.readouterr().err
    assert "VIBEIC_KLAYOUT_TOOLS" in err and "metal_fill.py" in err, \
        ("the override was set, resolved to nothing and said nothing; a silent "
         f"fall-through is the defect. stderr was: {err!r}")
