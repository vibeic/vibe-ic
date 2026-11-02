"""tests/test_rtl_gen_preserves_authored_rtl.py

`step_rtl_gen` used to rename `rtl/` aside and regenerate on EVERY
invocation, and the next invocation `rmtree`'d that aside before making
its own. The aside therefore survived exactly ONE re-run: two front-door
re-runs destroyed hand-authored RTL beyond recovery, silently, with the
step still reporting PASS.

That is not an edge case — it is the path taken whenever an author was
REQUIRED. The measured sequence: the deterministic generator emits
non-compiling RTL; the RTL repair/retry loop returns FAIL_RTL_REPAIR_INERT (byte-identical
RTL across iterations, i.e. the repair loop cannot repair itself); an
agent authors the design from the design documents; the next front-door
run deletes that work.

These tests pin the PUBLIC behaviour of the front door:

  1. authored RTL present     -> a re-run PRESERVES it
  2. generator-produced RTL   -> a re-run REGENERATES as before (the
                                 regression this fix could cause)
  3. generator proven failed  -> the class's fallback author is REACHABLE

plus: the destructive path still exists but is EXPLICIT (an override
flag) and RECOVERABLE (a timestamped copy nothing reclaims).

Every fixture uses a synthetic class with a stub generator, so nothing
here depends on an IC class name, on ic_class.json, or on any particular
design. The guard is keyed on RTL provenance alone.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
PROGRAMS_DIR = PLUGIN_ROOT / "programs"
if str(PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(PROGRAMS_DIR))

import design_one_shot_runner as R  # noqa: E402

STUB_NAME = "_zz_test_authored_guard_stub_gen.py"

# A stub generator that emits exactly one file, so "did the generator
# run?" is observable from the file set alone.
STUB_SRC = (
    "import sys\n"
    "from pathlib import Path\n"
    "p = Path(sys.argv[1]) / 'phase2/stage1/rtl'\n"
    "p.mkdir(parents=True, exist_ok=True)\n"
    "(p / 'gen_top.v').write_text('module gen_top(); endmodule\\n')\n"
)
STUB_FAIL_SRC = "import sys\nsys.exit(3)\n"
STUB_PARTIAL_FAIL_SRC = (
    "import sys\n"
    "from pathlib import Path\n"
    "p = Path(sys.argv[1]) / 'phase2/stage1/rtl'\n"
    "p.mkdir(parents=True, exist_ok=True)\n"
    "(p / 'partial.v').write_text('module partial; endmodule\\n')\n"
    "sys.exit(3)\n"
)

CLASS_NAME = "example_guard_class"


#: Where the stub generator is written for the test in flight. Set by the
#: autouse fixture below, which hands out a fresh directory OUTSIDE the
#: checkout.
_STUB_DIR = None


@pytest.fixture(autouse=True)
def _stub_dir(tmp_path_factory):
    """The stub generator lives in a scratch directory, never in `programs/`.

    IT USED TO BE WRITTEN INTO THE CHECKOUT and unlinked at teardown. Run
    alone that is invisible. Under the landing harness, where several pytest
    sessions share one checkout, `suite_write_guard` snapshots
    `git status --porcelain` around each session and a path that merely EXISTS
    inside somebody else's window is reported against THEM: measured at
    a00192752, `programs/_zz_test_authored_guard_stub_gen.py` was blamed on
    `programs/tests/test_rtl_interface_recover.py`, which does not know this
    file exists, turning a fully green suite red.

    The dispatch is unchanged. `step_rtl_gen` resolves the generator by
    joining the plugin programs directory with the registered name, and
    `Path.__truediv__` with an ABSOLUTE right-hand side yields that absolute
    path — so registering the stub by its full path runs exactly the same
    bytes through exactly the same door, with nothing landing in a tree these
    tests do not own.
    """
    global _STUB_DIR
    _STUB_DIR = tmp_path_factory.mktemp("authored_rtl_guard_stub")
    yield _STUB_DIR
    _STUB_DIR = None


def _stub_path() -> Path:
    assert _STUB_DIR is not None, "the stub fixture did not run"
    return _STUB_DIR / STUB_NAME


def _install_class(monkeypatch, gen_src: str = STUB_SRC,
                   rtl_gen: str = None,
                   fallback_skill: str = "spec-to-rtl") -> None:
    """Register a synthetic class whose generator is a stub we control.

    Chip-AGNOSTIC by construction: no real IC class, no real generator,
    no ic_class.json involvement.
    """
    stub = _stub_path()
    stub.write_text(gen_src)

    config = {"name": CLASS_NAME, "rtl_gen": rtl_gen or str(stub),
              "fallback_skill": fallback_skill}
    monkeypatch.setattr(R, "_lookup_class", lambda c: dict(config))
    # The program-first structured-RTL dispatcher runs before the registry
    # and is not under test here.
    monkeypatch.setattr(R, "_try_deterministic_rtl_dispatch",
                        lambda p, t: None)
    monkeypatch.setattr(R, "_FORCE_RTL_REGEN", False, raising=False)
    monkeypatch.setattr(R, "_RTL_SESSION_OWNED", False, raising=False)
    monkeypatch.setattr(R, "_RTL_SESSION_PROJECT", None, raising=False)


def _rtl(project: Path) -> Path:
    return project / "phase2" / "stage1" / "rtl"


def _new_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    _rtl(project).mkdir(parents=True)
    return project


def _end_run_and_start_new():
    """Finish the current runner invocation and begin a fresh one.

    The runner stamps the provenance ledger as it exits, then a later
    front-door run starts with no session ownership. Reproducing that
    boundary is what makes these re-run tests real.
    """
    R._finalize_rtl_provenance()
    R._RTL_SESSION_OWNED = False
    R._RTL_SESSION_PROJECT = None


def _author_rtl(project: Path, n: int = 3) -> dict:
    """An agent authors RTL over the tree, as `spec-to-rtl` would."""
    rtl = _rtl(project)
    for p in list(rtl.iterdir()):
        if p.is_file():
            p.unlink()
    authored = {}
    for i in range(n):
        f = rtl / f"authored_{i}.v"
        f.write_text(
            f"// authored from the design documents\n"
            f"module authored_{i}(input wire clk);\nendmodule\n")
        authored[f.name] = f.read_text()
    return authored


def _names(d: Path) -> list:
    return sorted(p.name for p in d.iterdir() if p.is_file())


# ---------------------------------------------------------------------
# Fixture 1 - authored RTL present: a re-run must PRESERVE it.
# ---------------------------------------------------------------------

def test_rerun_preserves_authored_rtl(tmp_path, monkeypatch):
    _install_class(monkeypatch)
    project = _new_project(tmp_path)

    # Run 1: the generator produces RTL (which, in the measured case,
    # did not compile).
    assert R.step_rtl_gen(project, CLASS_NAME).status == "PASS"
    _end_run_and_start_new()

    # An agent authors the design over it.
    authored = _author_rtl(project)

    # Run 2: the front door is re-run.
    res = R.step_rtl_gen(project, CLASS_NAME)

    # Every authored byte is still there, unchanged.
    for name, body in authored.items():
        f = _rtl(project) / name
        assert f.is_file(), f"authored file {name} was destroyed by a re-run"
        assert f.read_text() == body, f"authored file {name} was overwritten"
    # And the generator's own output did NOT reappear over the top.
    assert not (_rtl(project) / "gen_top.v").exists()
    assert res.status == "PASS_WITH_WAIVERS"


def test_preserving_rerun_is_repeatable(tmp_path, monkeypatch):
    """The old aside survived one re-run and was reclaimed by the next.
    Preservation must hold across repeated re-runs, not just the first."""
    _install_class(monkeypatch)
    project = _new_project(tmp_path)
    R.step_rtl_gen(project, CLASS_NAME)
    _end_run_and_start_new()
    authored = _author_rtl(project)

    for i in range(3):
        R.step_rtl_gen(project, CLASS_NAME)
        _end_run_and_start_new()
        assert _names(_rtl(project)) == sorted(authored), (
            f"authored RTL lost on re-run {i + 1}")


def test_preserving_waive_routes_to_the_fallback_author(tmp_path,
                                                        monkeypatch):
    """A refusal must be actionable: it names the author to continue with."""
    _install_class(monkeypatch)
    project = _new_project(tmp_path)
    R.step_rtl_gen(project, CLASS_NAME)
    _end_run_and_start_new()
    _author_rtl(project)

    res = R.step_rtl_gen(project, CLASS_NAME)
    assert res.extras.get("fallback_skill") == "spec-to-rtl"
    assert res.extras.get("preserved") is True
    # The override is discoverable from the message itself.
    assert "--force-rtl-regen" in res.detail


def test_rtl_of_unknown_provenance_is_preserved(tmp_path, monkeypatch):
    """RTL with no provenance record is preserved, not clobbered.

    An absent ledger is not evidence the generator produced the tree, so
    the fail-safe direction is to keep it. This is the pre-existing
    project case: RTL authored before any ledger existed.
    """
    _install_class(monkeypatch)
    project = _new_project(tmp_path)
    authored = _author_rtl(project)   # never generated; no ledger at all

    res = R.step_rtl_gen(project, CLASS_NAME)

    assert res.status == "PASS_WITH_WAIVERS"
    assert _names(_rtl(project)) == sorted(authored)
    assert not (_rtl(project) / "gen_top.v").exists()


def test_modified_generated_file_is_treated_as_authored(tmp_path,
                                                        monkeypatch):
    """Hand-editing a generated file is authorship too."""
    _install_class(monkeypatch)
    project = _new_project(tmp_path)
    R.step_rtl_gen(project, CLASS_NAME)
    _end_run_and_start_new()

    edited = "module gen_top();\n  // hand-repaired by an engineer\nendmodule\n"
    (_rtl(project) / "gen_top.v").write_text(edited)

    res = R.step_rtl_gen(project, CLASS_NAME)

    assert res.status == "PASS_WITH_WAIVERS"
    assert (_rtl(project) / "gen_top.v").read_text() == edited


# ---------------------------------------------------------------------
# Fixture 2 - generator-produced RTL: a re-run must REGENERATE.
# This is the regression the fix could cause. Not optional.
# ---------------------------------------------------------------------

def test_rerun_regenerates_generator_produced_rtl(tmp_path, monkeypatch):
    _install_class(monkeypatch)
    project = _new_project(tmp_path)

    assert R.step_rtl_gen(project, CLASS_NAME).status == "PASS"
    _end_run_and_start_new()

    # Delete the generated file so re-emission is observable rather than
    # merely assumed from an unchanged directory listing.
    (_rtl(project) / "gen_top.v").unlink()

    res = R.step_rtl_gen(project, CLASS_NAME)

    assert res.status == "PASS"
    assert (_rtl(project) / "gen_top.v").is_file(), (
        "generator-produced RTL must still regenerate normally")


def test_repeated_regeneration_stays_pass(tmp_path, monkeypatch):
    """Back-to-back front-door runs over generator-produced RTL keep
    regenerating - the guard must never latch on the runner's own work."""
    _install_class(monkeypatch)
    project = _new_project(tmp_path)

    for i in range(4):
        res = R.step_rtl_gen(project, CLASS_NAME)
        assert res.status == "PASS", (
            f"run {i + 1} stopped regenerating generator-produced RTL: "
            f"{res.status} - {res.detail[:200]}")
        assert (_rtl(project) / "gen_top.v").is_file()
        _end_run_and_start_new()


def test_rtl_repair_retry_reinvocation_regenerates_within_a_run(tmp_path,
                                                        monkeypatch):
    """Intra-run churn is not authorship.

    The RTL repair/retry loop calls step_rtl_gen repeatedly inside ONE invocation. The
    guard protects against edits made between runs; if it fired inside a
    run it would break the repair loop.
    """
    _install_class(monkeypatch)
    project = _new_project(tmp_path)

    assert R.step_rtl_gen(project, CLASS_NAME).status == "PASS"
    # Same invocation - no _end_run_and_start_new().
    for _ in range(3):
        assert R.step_rtl_gen(project, CLASS_NAME).status == "PASS"


def test_runner_emitted_files_are_not_mistaken_for_authored(tmp_path,
                                                            monkeypatch):
    """The runner keeps writing into rtl/ after the generator (chip_top
    auto-emit, alias wrappers, hygiene --fix). Those are its own work and
    must not make the next run refuse to regenerate."""
    _install_class(monkeypatch)
    project = _new_project(tmp_path)

    assert R.step_rtl_gen(project, CLASS_NAME).status == "PASS"
    # A later runner step emits an alias wrapper, as the real flow does.
    (_rtl(project) / "chip_top.v").write_text(
        "module chip_top(); gen_top u(); endmodule\n")
    _end_run_and_start_new()

    res = R.step_rtl_gen(project, CLASS_NAME)

    assert res.status == "PASS", (
        "runner-emitted RTL was misread as authored, blocking regeneration")


# ---------------------------------------------------------------------
# Fixture 3 - generator proven failed: the fallback must be REACHABLE.
# ---------------------------------------------------------------------

def test_fallback_reachable_on_rtl_repair_inert(monkeypatch):
    """FAIL_RTL_REPAIR_INERT means the generator proved it cannot proceed.

    A class declaring BOTH a generator and a fallback_skill could never
    reach that fallback: dispatch consulted fallback_skill only when
    rtl_gen was null, i.e. when the generator was ABSENT - never when a
    declared generator had definitively failed.
    """
    _install_class(monkeypatch)

    note, skill = R._rtl_repair_inert_fallback(CLASS_NAME)

    assert skill == "spec-to-rtl"
    assert note, ("a generator that returned byte-identical RTL must "
                  "surface the class's fallback author")
    assert "spec-to-rtl" in note


def test_fallback_reachable_when_generator_fails(tmp_path, monkeypatch):
    """Same principle at the step level: a declared generator that runs
    and cannot deliver must route to the author."""
    _install_class(monkeypatch, gen_src=STUB_FAIL_SRC)
    project = _new_project(tmp_path)

    res = R.step_rtl_gen(project, CLASS_NAME)

    assert res.status == "FAIL"
    assert res.extras.get("fallback_skill") == "spec-to-rtl"
    assert "spec-to-rtl" in res.detail


def test_failed_generator_partial_output_is_discarded_transactionally(
        tmp_path, monkeypatch):
    _install_class(monkeypatch, gen_src=STUB_PARTIAL_FAIL_SRC)
    project = _new_project(tmp_path)

    res = R.step_rtl_gen(project, CLASS_NAME)

    assert res.status == "FAIL"
    assert not (_rtl(project) / "partial.v").exists()
    assert _names(_rtl(project)) == []
    assert not (project / "phase2" / "stage1" /
                "rtl.pre_gen_backup").exists()


def test_registered_generator_is_staged_and_never_adopts_replaced_root(
        tmp_path, monkeypatch):
    _install_class(monkeypatch)
    project = _new_project(tmp_path)
    displaced = tmp_path / "proj.displaced"
    generator_roots = []
    real_run = R._run

    def _run_after_live_root_replacement(cmd, *args, **kwargs):
        if len(cmd) >= 3 and Path(cmd[1]).name == STUB_NAME:
            candidate = Path(cmd[2])
            generator_roots.append(candidate)
            assert candidate != project
            project.rename(displaced)
            project.mkdir()
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(R, "_run", _run_after_live_root_replacement)

    res = R.step_rtl_gen(project, CLASS_NAME)

    assert res.status == "NOT_MEASURED"
    assert res.extras["output_refusal"]["reason"] == (
        "PROJECT_BOUNDARY_REPLACED_DURING_PUBLICATION")
    assert generator_roots and len(generator_roots) == 1
    assert not list(project.rglob("*"))
    assert not (_rtl(displaced) / "gen_top.v").exists()


def test_rtl_repair_inert_note_absent_when_class_declares_no_fallback(monkeypatch):
    """No fallback declared -> no invented handoff."""
    _install_class(monkeypatch, fallback_skill=None)

    note, skill = R._rtl_repair_inert_fallback(CLASS_NAME)

    assert skill is None
    assert note == ""


# ---------------------------------------------------------------------
# The destructive path: still available, but explicit AND recoverable.
# ---------------------------------------------------------------------

def test_override_regenerates_and_preserves_recoverably(tmp_path,
                                                        monkeypatch):
    _install_class(monkeypatch)
    project = _new_project(tmp_path)
    R.step_rtl_gen(project, CLASS_NAME)
    _end_run_and_start_new()
    authored = _author_rtl(project)

    res = R.step_rtl_gen(project, CLASS_NAME, force_regen=True)

    # It regenerated, as asked.
    assert res.status == "PASS"
    assert (_rtl(project) / "gen_top.v").is_file()
    # And the authored work is recoverable from a location the result names.
    kept = [d for d in (project / "phase2/stage1").glob(
        "rtl.authored_backup.*") if d.is_dir()]
    assert len(kept) == 1, "override must preserve the displaced RTL"
    for name, body in authored.items():
        assert (kept[0] / name).read_text() == body
    assert kept[0].name in res.detail, (
        "recovery must not depend on knowing where the copy went")


def test_override_preserve_dirs_are_never_reclaimed(tmp_path, monkeypatch):
    """The old aside was reclaimed by the next run - that is what made the
    loss permanent. Repeated overrides must accumulate, not overwrite."""
    _install_class(monkeypatch)
    project = _new_project(tmp_path)

    for i in range(2):
        R.step_rtl_gen(project, CLASS_NAME)
        _end_run_and_start_new()
        _author_rtl(project, n=2)
        R.step_rtl_gen(project, CLASS_NAME, force_regen=True)
        _end_run_and_start_new()

    kept = [d for d in (project / "phase2/stage1").glob(
        "rtl.authored_backup.*") if d.is_dir()]
    assert len(kept) == 2, (
        f"each override must keep its own copy; found {len(kept)}")


def test_override_is_off_by_default(tmp_path, monkeypatch):
    """Destruction is never a silent side-effect of the normal path."""
    _install_class(monkeypatch)
    project = _new_project(tmp_path)
    R.step_rtl_gen(project, CLASS_NAME)
    _end_run_and_start_new()
    authored = _author_rtl(project)

    R.step_rtl_gen(project, CLASS_NAME)          # no override

    assert _names(_rtl(project)) == sorted(authored)
    assert not list((project / "phase2/stage1").glob(
        "rtl.authored_backup.*")), (
        "the default path must not need a backup - it must not destroy")


def test_guard_ignores_ic_class_identity(tmp_path, monkeypatch):
    """The guard is keyed on provenance, never on the class name.

    Two different class names over identical on-disk state must produce
    identical decisions - so re-labelling ic_class.json can never be used
    to steer whether authored RTL survives.
    """
    outcomes = []
    for class_name in ("some_class_a", "some_class_b"):
        _install_class(monkeypatch)
        monkeypatch.setattr(
            R, "_lookup_class",
            lambda c: {"name": c, "rtl_gen": str(_stub_path()),
                       "fallback_skill": "spec-to-rtl"})
        project = _new_project(tmp_path / class_name)
        R.step_rtl_gen(project, class_name)
        _end_run_and_start_new()
        _author_rtl(project)
        outcomes.append(R.step_rtl_gen(project, class_name).status)

    assert outcomes == ["PASS_WITH_WAIVERS", "PASS_WITH_WAIVERS"], (
        "provenance decisions must not vary with the IC class label")


# Public, independently declared source inputs; no HDL tools or field captures.
_ORIGIN_INPUT = Path(__file__).parent / "data" / "origin_finalizer.json"
_ORIGIN_CASES = json.loads(_ORIGIN_INPUT.read_text())["producers"]
# The legacy sequence parameter still exercises every finalizer/consumer arm.
# Free-prose FSMs now hand off, so use a second neutral typed producer input.
_ORIGIN_CASES[1] = {
    "id": "sequence",
    "origin": "serial_parallel_mul_synth",
    "input_files": {
        "input/phase1_prompt.md": "Serial-parallel arithmetic metadata with synchronous active-high reset.\n",
        "phase1/generated_docs/L2_FRS.json": json.dumps({
            "ic_name": "neutral_sequence", "frs_sections": [{"content":
                "serial-parallel multiplier: p = (x * y) mod 2^N; synchronous active-high reset"}],
        }),
        "phase1/generated_docs/L9_INTEGRATION_SPEC.json": json.dumps({
            "top_module": "neutral_sequence", "top_ports": [
                {"name": "clk", "direction": "input", "width": 1},
                {"name": "rst", "direction": "input", "width": 1},
                {"name": "x", "direction": "input", "width": "size-1:0",
                 "width_symbolic": "size-1:0", "msb": "size-1", "lsb": "0"},
                {"name": "y", "direction": "input", "width": 1},
                {"name": "p", "direction": "output", "width": 1},
            ],
        }),
    },
    "handoff_input_files": {
        "input/phase1_prompt.md": "Retain the existing implementation; no replacement behavior is specified.\n",
        "phase1/generated_docs/L2_FRS.json": json.dumps({
            "ic_name": "neutral_sequence", "frs_sections": [{"content":
                "Retain the existing implementation; no replacement behavior is specified."}],
        }),
    },
}


@pytest.fixture
def origin_session(monkeypatch):
    R._phase1_replace_session_binding(None)
    monkeypatch.setattr(R, "_RTL_SESSION_OWNED", False)
    monkeypatch.setattr(R, "_RTL_SESSION_PROJECT", None)
    yield
    R._phase1_replace_session_binding(None)


def _origin_project(tmp_path, declared):
    project = tmp_path / declared["id"]
    for rel, text in declared["input_files"].items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    result = R.step_rtl_gen(project, "digital_arithmetic_primitive")
    assert result.status == "PASS", result.detail
    ledger = R._rtl_prov.load_ledger(project)
    assert ledger["generator"] == declared["origin"], ledger
    assert R._rtl_prov.classify(project)[0] == R._rtl_prov.GENERATED
    return project, result


def _origin_observed(tmp_path, record_property, observed):
    import hashlib
    observed["input_sha256"] = hashlib.sha256(
        _ORIGIN_INPUT.read_bytes()).hexdigest()
    observed["effective_cases_sha256"] = hashlib.sha256(
        json.dumps(_ORIGIN_CASES, sort_keys=True).encode()).hexdigest()
    record_property("observed", json.dumps(observed, sort_keys=True))
    (tmp_path / "origin_observed.json").write_text(
        json.dumps(observed, indent=2, sort_keys=True) + "\n")


@pytest.mark.parametrize("declared", _ORIGIN_CASES,
                         ids=[c["id"] for c in _ORIGIN_CASES])
@pytest.mark.parametrize("late_work", ["unchanged", "wrapper", "hygiene"])
@pytest.mark.parametrize("consumer", ["pure", "standalone", "terminal"])
def test_origin_survives_actual_producer_finalization_and_handoff(
        tmp_path, monkeypatch, origin_session, declared, late_work, consumer,
        record_property):
    from test_flow_phase_attribution_is_general import (
        _input_state, _terminal_report_only)
    import flow_phase_attribution as attribution
    import ai_signed_judgement

    project, emitted = _origin_project(tmp_path, declared)
    original_ledger = R._rtl_prov.load_ledger(project)
    if late_work == "wrapper":
        (_rtl(project) / "neutral_alias.v").write_text(
            "module neutral_alias; endmodule\n")
    elif late_work == "hygiene":
        primary = next(_rtl(project).glob("*.v"))
        primary.write_text(primary.read_text() + "// runner hygiene pass\n")
    owned_bytes = {p.name: p.read_bytes() for p in _rtl(project).glob("*.v")}
    emitted_record = json.dumps(emitted.__dict__, sort_keys=True)
    R._finalize_rtl_provenance()
    final_ledger = R._rtl_prov.load_ledger(project)
    final_kind = R._rtl_prov.classify(project)
    assert final_kind[0] == R._rtl_prov.GENERATED, final_kind
    assert {p.name: p.read_bytes() for p in _rtl(project).glob("*.v")} == owned_bytes
    assert set(final_ledger["files"]) == set(owned_bytes)
    assert json.dumps(emitted.__dict__, sort_keys=True) == emitted_record
    # A repeated exit callback has no remaining held transaction to publish.
    finalized_state = _input_state(project)
    R._finalize_rtl_provenance()
    assert _input_state(project) == finalized_state
    assert R._RTL_SESSION_BINDING is None

    R._RTL_SESSION_OWNED = False
    R._RTL_SESSION_PROJECT = None
    # The second public subject declares a later unsupported specification.
    # Exercise a real subsequent no-emission handoff, without stubbing dispatch.
    for rel, text in declared.get("handoff_input_files", {}).items():
        (project / rel).write_text(text)
    handoff = R.step_rtl_gen(project, "digital_arithmetic_primitive")
    assert handoff.status == "PASS_WITH_WAIVERS", handoff.detail
    assert handoff.output_files == []
    assert handoff.extras["fallback_skill"] == "spec-to-rtl"
    report = project / "reports/orchestrator/phase2_one_shot.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"verdict": "PASS_WITH_WAIVERS",
                                 "steps": [handoff.__dict__]}) + "\n")
    before = _input_state(project)
    signature_before = ai_signed_judgement._requested(project, "1")
    pure = attribution.attribute(project)
    if consumer == "standalone":
        proc = subprocess.run([
            sys.executable, str(PROGRAMS_DIR / "flow_phase_attribution.py"),
            str(project), "--json", "--no-write"],
            capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
        actual = json.loads(proc.stdout)
    elif consumer == "terminal":
        actual = _terminal_report_only(project)
    else:
        actual = pure
    assert actual == pure
    after = _input_state(project)
    solving = actual["phase2_solving"]
    _origin_observed(tmp_path, record_property, {
        "producer": declared["id"], "late_work": late_work,
        "consumer": consumer, "emission": emitted.__dict__,
        "original_ledger": original_ledger, "final_ledger": final_ledger,
        "final_classification": final_kind, "handoff": handoff.__dict__,
        "attribution": actual, "before_report": before, "after_report": after,
        "signature_requested": signature_before})
    assert after == before
    assert R._rtl_prov.classify(project) == final_kind
    assert ai_signed_judgement._requested(project, "1") == signature_before is False
    assert (solving["solved_by"], solving["emitter"]) == (
        "EMITTER", declared["origin"]), solving
    assert final_ledger["generator"] == declared["origin"]
    assert solving["reused"] is True
    assert solving["emitted_in_this_invocation"] is False
    assert solving["ai_authored_in_this_invocation"] is False
    assert solving["current_dispatch"] == {
        "status": "PASS_WITH_WAIVERS", "fallback_skill": "spec-to-rtl",
        "mechanism": "AI_HANDOFF", "actor": "spec-to-rtl"}


@pytest.mark.parametrize("damage", [
    "missing-ledger", "invalid-ledger", "missing-producer",
    "invalid-producer", "blank-producer"])
def test_finalizer_does_not_invent_an_unvalidated_origin(
        tmp_path, origin_session, damage, record_property):
    import flow_phase_attribution as attribution
    project, _ = _origin_project(tmp_path, _ORIGIN_CASES[0])
    lp = R._rtl_prov.ledger_path(project)
    if damage == "missing-ledger":
        lp.unlink()
    elif damage == "invalid-ledger":
        lp.write_text("{invalid public ledger")
    else:
        ledger = R._rtl_prov.load_ledger(project)
        ledger["generator"] = {"missing-producer": None,
                               "invalid-producer": {"name": "unvalidated"},
                               "blank-producer": "  "}[damage]
        lp.write_text(json.dumps(ledger))
    R._finalize_rtl_provenance()
    kind = R._rtl_prov.classify(project)
    row = attribution.phase2_solving({"steps": [{
        "name": "rtl_gen", "status": "PASS_WITH_WAIVERS",
        "extras": {"fallback_skill": "spec-to-rtl"}}]}, None, project=project)
    _origin_observed(tmp_path, record_property,
                     {"damage": damage, "classification": kind, "solving": row})
    assert (row["solved_by"], row["emitter"]) == ("AI_BACKUP", None), row
    assert kind[0] == (R._rtl_prov.UNKNOWN if damage.endswith("ledger")
                       else R._rtl_prov.GENERATED)
    assert R._RTL_SESSION_BINDING is None


@pytest.mark.parametrize("state", [
    "foreign", "modified", "added", "missing-ledger", "invalid-ledger", "empty"])
def test_finalizer_without_session_preserves_unowned_state(
        tmp_path, origin_session, state):
    from test_flow_phase_attribution_is_general import _input_state
    project = _new_project(tmp_path)
    source = _rtl(project) / "neutral.v"
    if state != "empty":
        source.write_text("// generator=spoofed_name\nmodule neutral; endmodule\n")
    if state in ("modified", "added"):
        R._rtl_prov.stamp(project, generator="prior-public-emitter")
        if state == "modified":
            source.write_text(source.read_text() + "// foreign edit\n")
        else:
            (_rtl(project) / "foreign.sv").write_text("module foreign; endmodule\n")
    elif state == "invalid-ledger":
        R._rtl_prov.ledger_path(project).write_text("{invalid public ledger")
    before = _input_state(project)
    classification = R._rtl_prov.classify(project)
    R._finalize_rtl_provenance()
    assert _input_state(project) == before
    assert R._rtl_prov.classify(project) == classification
    assert classification[0] != R._rtl_prov.GENERATED


def test_origin_finalization_refuses_a_replaced_held_project(
        tmp_path, origin_session):
    from test_flow_phase_attribution_is_general import _input_state
    project, _ = _origin_project(tmp_path, _ORIGIN_CASES[0])
    # Give finalization real runner work to stamp; an unchanged ledger is an
    # idempotent no-op even when the project-inode refusal is removed.
    (_rtl(project) / "runner_owned_alias.v").write_text(
        "module runner_owned_alias; endmodule\n")
    displaced = project.with_name("held-original")
    project.rename(displaced)
    project.mkdir()
    (project / "foreign.txt").write_text("foreign replacement\n")
    original_state, foreign_state = _input_state(displaced), _input_state(project)
    R._finalize_rtl_provenance()
    assert _input_state(displaced) == original_state
    assert _input_state(project) == foreign_state
    assert R._RTL_SESSION_BINDING is None
