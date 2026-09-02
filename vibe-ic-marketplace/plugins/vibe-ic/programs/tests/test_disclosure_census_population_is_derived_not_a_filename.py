#!/usr/bin/env python3
"""The #511 census asked `*_check.py`, and the third instance was a `*_lint.py`.

WHAT WAS MEASURED, on 79d3ebbe8 (v1.16.45)
==========================================
`gate_discloses_denominator_check --population project` selected its population
with `programs_dir.glob("*_check.py")` — 595 programs — and called it "every
registered gate program". The repository's OWN answer to "which programs are
checkers" lives in `checker_execution_wiring_audit._CHECKER_SUFFIXES` and is
five suffixes wide (651 programs), and its answer to "which programs behave like
one whatever they are called" lives in
`checker_population_is_structural_not_filename_shaped_census` (54 more). So the
disclosure census carried a SIXTH, private, narrower definition of one
population, and 110 programs were never asked the #511 question at all.

One of them was answering it wrong:

    analog_netlist_path_lint, empty project    [PASS] analog_netlist_path_lint
    analog_netlist_path_lint, one clean deck   [PASS] analog_netlist_path_lint

byte for byte — a `*_lint.py` driven by `analog_a3_netlist_emit` side by side
with two `*_check.py` that the census DID ask. That gate is fixed in its own
commit; this file is about the reason it survived.

THE POPULATION IS NOW DERIVED, from those two sources, neither re-typed here.
The tests below drive the real program over synthetic trees, in both directions:
a silent gate outside the old glob must be FOUND, a disclosing one must NOT be
flagged, and a tree that cannot supply the definition must say so LOUDLY rather
than fall back to the old glob in silence.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
STANDING = PROGRAMS / "gate_discloses_denominator_check.py"

sys.path.insert(0, str(PROGRAMS))
import gate_discloses_denominator_check as GD  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_SILENT = 'print("[PASS] {name}")\nsys.exit(0)\n'
_DISCLOSING = ('print("[VACUOUS_PASS] {name}: examined 0 widget(s) — no '
               'widget in this project")\nsys.exit(0)\n')


def _programs_dir(tmp_path: Path, *, suffixes=("*_check.py", "*_lint.py"),
                  audit: bool = True) -> Path:
    """A synthetic programs/ dir carrying its own definition source.

    The suffix tuple written here is DELIBERATELY not the shipped one: the
    property under test is that the census READS the tuple out of
    `checker_execution_wiring_audit.py`, and a fixture that repeated the real
    five would pass just as well against a census with them hard-coded.
    """
    d = tmp_path / "fake_programs"
    d.mkdir(exist_ok=True)
    if audit:
        body = ", ".join(f'"{s}"' for s in suffixes)
        (d / "checker_execution_wiring_audit.py").write_text(
            f"_CHECKER_SUFFIXES = ({body},)\n")
    return d


def _write(d: Path, name: str, body: str) -> None:
    (d / f"{name}.py").write_text(
        "#!/usr/bin/env python3\nimport sys\n" + body.format(name=name)
        + '\nif __name__ == "__main__":\n    pass\n')


def _run(tmp_path: Path, d: Path, out: Path):
    return _pr.run([sys.executable, str(STANDING), "--population", "project",
                    "--programs-dir", str(d), "--json", str(out)],
                   cwd=str(tmp_path), capture_output=True, text=True)


def _flagged(out: Path, kind="PASS_WITHOUT_DENOMINATOR"):
    rep = json.loads(out.read_text())
    return rep, {f["gate"] for f in rep["findings"] if f["kind"] == kind}


# ── 1. the injected defect the OLD population could not see ────────────────

def test_a_silent_lint_outside_the_old_glob_is_now_found(tmp_path):
    """THE DEFECT, injected under the name that used to be invisible.

    Against the pre-change population this test cannot fail: `brand_new_silent_lint`
    is not a `*_check.py`, so it was never driven and never reported."""
    d = _programs_dir(tmp_path)
    _write(d, "brand_new_silent_lint", _SILENT)
    out = tmp_path / "r.json"
    r = _run(tmp_path, d, out)
    assert r.returncode == 1, r.stdout + r.stderr
    rep, flagged = _flagged(out)
    assert "brand_new_silent_lint" in flagged, rep["findings"]
    assert "brand_new_silent_lint" in r.stderr


def test_a_disclosing_lint_is_not_flagged(tmp_path):
    """The other direction: without this, the test above would also pass for a
    census that simply rejects everything it can now see."""
    d = _programs_dir(tmp_path)
    _write(d, "brand_new_disclosing_lint", _DISCLOSING)
    out = tmp_path / "r.json"
    _run(tmp_path, d, out)
    _, flagged = _flagged(out)
    assert "brand_new_disclosing_lint" not in flagged


def test_the_suffix_tuple_is_read_from_the_tree_not_assumed(tmp_path):
    """A tuple the shipped repository does NOT have must still be obeyed — that
    is the difference between reading the definition and repeating it."""
    d = _programs_dir(tmp_path, suffixes=("*_probe.py",))
    _write(d, "silent_probe", _SILENT)          # matches the declared suffix
    _write(d, "silent_check", _SILENT)          # matches the OLD hard-coded one
    out = tmp_path / "r.json"
    r = _run(tmp_path, d, out)
    rep, flagged = _flagged(out)
    assert "silent_probe" in flagged, rep["findings"]
    assert rep["population_definition"]["suffixes"] == ["*_probe.py"]
    # `silent_check` is reached by the BEHAVIOUR half (a `[PASS]` banner and an
    # entry point), not by the name — which is the point of having both.
    assert "silent_check" in flagged, rep["findings"]


# ── 2. the behaviour half, on its own ──────────────────────────────────────

def test_a_verdict_emitter_with_no_checker_suffix_at_all_is_in(tmp_path):
    """`zzz_widget` matches no suffix in any tuple. It prints a verdict and has
    an entry point, so the repository recognises it by RELATION."""
    d = _programs_dir(tmp_path, suffixes=("*_check.py",))
    _write(d, "zzz_widget", _SILENT)
    out = tmp_path / "r.json"
    r = _run(tmp_path, d, out)
    assert r.returncode == 1, r.stdout + r.stderr
    rep, flagged = _flagged(out)
    assert "zzz_widget" in flagged
    assert rep["population_definition"]["by_behaviour"] >= 1, \
        rep["population_definition"]


# ── 3. a file that DOES NOTHING when executed is not a gate ────────────────

def test_a_library_with_no_entry_point_is_excluded_and_named(tmp_path):
    """Executing a library imports it. Its rc 0 and its silence are facts about
    Python, and reporting them as a gate defect would be a census that fires on
    legitimate state."""
    d = _programs_dir(tmp_path)
    (d / "pure_library_check.py").write_text(
        "SOME = 1\n\n\ndef helper(x):\n    return x\n")
    _write(d, "real_silent_check", _SILENT)
    out = tmp_path / "r.json"
    r = _run(tmp_path, d, out)
    rep, flagged = _flagged(out)
    assert "pure_library_check" not in flagged
    assert "pure_library_check.py" in \
        rep["population_definition"]["no_entry_point"]
    # …and the exclusion is not a way to lose a real gate.
    assert "real_silent_check" in flagged


def test_a_top_level_script_with_no_main_guard_is_still_driven(tmp_path):
    """The rule is RUNNABILITY, not the `__main__` idiom: a script whose work
    sits at top level has no guard and is still a program. Keyed on the idiom
    this would have silently left the population."""
    d = _programs_dir(tmp_path)
    (d / "bare_script_check.py").write_text(
        "import sys\nprint('[PASS] bare_script_check')\nsys.exit(0)\n")
    out = tmp_path / "r.json"
    r = _run(tmp_path, d, out)
    rep, flagged = _flagged(out)
    assert "bare_script_check" in flagged, rep["population_definition"]
    assert "bare_script_check.py" not in \
        rep["population_definition"]["no_entry_point"]


@pytest.mark.parametrize("body,runnable", [
    ("import os\n\n\ndef f():\n    return 1\n", False),
    ('"""doc"""\nX = 2\n', False),
    ("import sys\nsys.exit(0)\n", True),
    ('if __name__ == "__main__":\n    pass\n', True),
    ("this is not python(((\n", True),          # unparseable stays IN
])
def test_the_runnability_predicate_both_ways(tmp_path, body, runnable):
    f = tmp_path / "probe.py"
    f.write_text(body)
    assert GD._has_entry_point(f) is runnable, body


# ── 4. a tree that cannot supply the definition must say so ────────────────

def test_a_missing_definition_source_degrades_loudly(tmp_path):
    """Falling back to the old glob in silence would re-open the exact hole
    this change closes, invisibly."""
    d = _programs_dir(tmp_path, audit=False)
    _write(d, "quiet_check", _DISCLOSING)
    out = tmp_path / "r.json"
    r = _run(tmp_path, d, out)
    rep = json.loads(out.read_text())
    defn = rep["population_definition"]
    assert defn["degraded"] is True, defn
    assert defn["suffix_source"] == "FALLBACK"
    assert defn["suffixes"] == [GD._HISTORICAL_SUFFIX]
    assert defn["degraded_reason"].strip()
    kinds = {f["kind"] for f in rep["findings"]}
    assert "POPULATION_DEFINITION_DEGRADED" in kinds, rep["findings"]
    assert r.returncode == 1
    assert "DEGRADED" in r.stderr


def test_a_readable_definition_source_is_not_degraded(tmp_path):
    d = _programs_dir(tmp_path)
    _write(d, "quiet_check", _DISCLOSING)
    out = tmp_path / "r.json"
    r = _run(tmp_path, d, out)
    rep = json.loads(out.read_text())
    assert rep["population_definition"]["degraded"] is False
    # A synthetic dir necessarily carries none of the shipped inventory, so the
    # two STALE_* ratchets fire here by construction and are not what this test
    # is about. What must be absent is the degrade and any disclosure finding.
    kinds = {f["kind"] for f in rep["findings"]}
    assert "POPULATION_DEFINITION_DEGRADED" not in kinds, rep["findings"]
    assert "PASS_WITHOUT_DENOMINATOR" not in kinds, rep["findings"]


# ── 5. the population is PUBLISHED, and it never silently shrinks ──────────

def test_the_definition_is_on_stderr_of_a_passing_run(tmp_path):
    """A denominator nobody sees until something breaks is the shape that lets
    a population shrink."""
    r = _pr.run([sys.executable, str(STANDING), "--population", "project"],
                cwd=str(PROGRAMS), capture_output=True, text=True)
    text = r.stdout + r.stderr
    assert "POPULATION:" in text
    assert "by name" in text and "by behaviour" in text
    assert "checker_execution_wiring_audit.py" in text


def test_the_shipped_population_is_a_strict_superset_of_the_old_glob():
    derived = {p.name for p in GD.project_check_programs(PROGRAMS)}
    old = {p.name for p in PROGRAMS.glob("*_check.py")}
    assert old - derived == set(), sorted(old - derived)[:10]
    assert len(derived) > len(old)
    # The instance that motivated this is IN, by name and by behaviour.
    assert "analog_netlist_path_lint.py" in derived


# ── 6. the second exemption list is dated, reasoned and ratcheted ──────────

def test_not_project_driven_entries_are_dated_reasoned_and_real():
    assert GD._NOT_PROJECT_DRIVEN, (
        "an empty list here would make the ratchet below vacuous")
    for gate, meta in GD._NOT_PROJECT_DRIVEN.items():
        assert (PROGRAMS / f"{gate}.py").is_file(), gate
        assert meta["reason"].strip(), gate
        assert len(meta["measured"]) == 10 and meta["measured"][4] == "-", gate
        assert gate not in GD._EMPTY_PROJECT_SILENT_PASS, gate


def test_an_entry_that_no_longer_applies_must_be_deleted(tmp_path):
    """The list can only ever be made shorter by a visible edit."""
    fixed = sorted(GD._NOT_PROJECT_DRIVEN)[0]
    # The declared suffix must reach the entry's own name, or the population is
    # empty and the run refuses before the ratchet is ever consulted.
    d = _programs_dir(tmp_path, suffixes=("*_check.py", f"{fixed}.py"))
    _write(d, fixed, _DISCLOSING)
    _write(d, "companion_check", _DISCLOSING)
    out = tmp_path / "r.json"
    r = _run(tmp_path, d, out)
    assert r.returncode == 1, r.stdout + r.stderr
    _, stale = _flagged(out, "STALE_NOT_PROJECT_DRIVEN_ENTRY")
    assert fixed in stale
