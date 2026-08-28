"""#564 — disclosing a zero denominator and refusing on one are different properties.

`gate_discloses_denominator_check` audits the same population and passes gates
that say "I read 0 files" and exit 0 — correctly, because its contract is "a
PASS must say how much it looked at" and they do. The P0 umbrella then reads the
EXIT CODE, so the disclosure is in the output and the aggregation reads the code:
a silent pass.

MEASURED over the whole population, which is what the issue asked for and could
not have known without probing:

    gates probed                 497
    stated a zero population      22
      of those, REFUSED           20        <- already correct
      of those, exited 0           2        <- the findings
    unrunnable                     1

So the suspicion was right and the size was not: **2 more, not 490**. Both are
now fixed and the re-run is 22 of 22 refusing.

    container_exec_deadline_check    "PASS — 0 finding(s) over 0 file(s) scanned"
    loop_watchdog_compliance_check   "PASS — 0 file(s) scanned, no unguarded …"

`container_exec_deadline_check` is worth quoting on itself. Two lines above the
`return PASS` it says:

    # The denominator is printed ALWAYS: a clean result over zero files is not
    # a clean result, and a reader must be able to tell those apart.

It stated the principle in a comment and returned PASS on zero files anyway.

THE LINE THIS TURNS ON is the issue's own: an empty artefact is not a missing
one. `analysed 1 file(s), found 0` is a real result over a real population and
rc 0 is correct; `analysed 0 file(s)` is not a result at all. So the predicate
keys on a zero beside a POPULATION word and never beside a FINDING word.

NOT A BLANKET REFUSAL. #564 asks for the probe, and a blanket change is
measurably wrong — forcing refusal on four gates flipped 182 / 159 / 94 / 42 of
182 tracked run dirs and was reverted. The probe names the offenders; each fix
is then its own measured change, which is what the two above are.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import pytest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


G = _load("gate_zero_denominator_refuses_check")


# ── the discriminator, which is the whole predicate ─────────────────────────
@pytest.mark.parametrize("text", [
    "analyzed 0 file(s)",
    "0 interfaces analyzed",
    "scanned 0 designs",
    "read 0 records",
])
def test_a_zero_population_is_recognised(text):
    assert G.states_zero_population(text), text


@pytest.mark.parametrize("text", [
    "analyzed 1 file(s), found 0",
    "scanned 12 designs, found 0 violations",
    "found 0 violations",
    "0 errors",
    "PASS: 493 gate(s) probed",
])
def test_a_zero_FINDING_over_a_real_population_is_not(text):
    """LOAD-BEARING, and the issue's own line: an empty artefact is not a
    missing one. An empty `.v` that WAS opened and read is a real result."""
    assert not G.states_zero_population(text), text


def test_a_missing_input_counts_as_reading_nothing():
    """The `fpga_qsf_lint` shape — it never said a number, it said the file was
    not there. Same class: it read nothing."""
    assert G.states_missing_input("ERROR: QSF file not found")
    assert G.states_missing_input("WARNING: file not found")
    assert not G.states_missing_input("PASS: 3 file(s) scanned")


def test_a_finding_word_beside_the_zero_is_not_a_population():
    """`analysed 0 violations` reads like a population but names a finding.
    The negative lookahead is what keeps it out."""
    assert not G.states_zero_population("analyzed 0 violations")


# ── the two gates this issue's probe caught ─────────────────────────────────
@pytest.mark.parametrize("gate", ["container_exec_deadline_check",
                                  "loop_watchdog_compliance_check"])
def test_a_zero_file_scan_now_refuses(gate, tmp_path):
    """rc 2 is this repo's disclosed-skip convention and promotes the step to
    VACUOUS-PASS. rc 0 made it a silent pass."""
    # DRIVEN THE WAY THE PROBER DRIVES IT — `[gate, "."]` with cwd set — not
    # by cwd alone. `loop_watchdog_compliance_check` defaults its population to
    # the programs directory, so a bare invocation from an empty cwd still
    # scanned 1063 files and the first version of this test failed on its own
    # driving rather than on the fix.
    r = _pr.run([sys.executable, str(_PROGRAMS / f"{gate}.py"), "."],
                       cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 2, (
        f"{gate} exits {r.returncode} over an empty directory: "
        f"{(r.stdout + r.stderr)[-200:]}")
    assert "VACUOUS_PASS" in (r.stdout + r.stderr)


@pytest.mark.parametrize("gate", ["container_exec_deadline_check",
                                  "loop_watchdog_compliance_check"])
def test_the_real_population_still_passes(gate):
    """THE ACCEPT CASE. A refusal that also fires on the real repo is the same
    gate switched off from the other end."""
    r = _pr.run([sys.executable, str(_PROGRAMS / f"{gate}.py"), "."],
                       cwd=str(_PROGRAMS), capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout + r.stderr)[-300:]


# ── the prober's own contract ───────────────────────────────────────────────
def test_it_publishes_its_own_denominator():
    """A check that reports only findings publishes no denominator of its own,
    which is the thing it is here to require of others."""
    src = (_PROGRAMS / "gate_zero_denominator_refuses_check.py").read_text(
        encoding="utf-8")
    assert '"gates_probed"' in src
    assert "NOTHING_PROBED" in src, "an empty population must not be a pass"


def test_an_empty_population_refuses_rather_than_passing(tmp_path):
    r = _pr.run(
        [sys.executable, str(_PROGRAMS / "gate_zero_denominator_refuses_check.py"),
         "--programs-dir", str(tmp_path)],
        capture_output=True, text=True)
    assert r.returncode == G.RC_CANNOT_PROBE, r.stdout + r.stderr


#: The exemptions this repository has actually granted. PINNED, so adding or
#: removing one still costs a visible edit here — the property
#: `_ZERO_IS_A_PASS == {}` was really enforcing.
EXEMPTED_TODAY = {"professional_tb_check"}


def test_the_exemption_inventory_is_pinned_dated_and_reasoned():
    """`_ZERO_IS_A_PASS == {}` was not the property; it was the population.

    That assertion was written at v1.9.28 (`d00a58d27`) when nothing had been
    exempted, so "empty" and "every entry is justified" were indistinguishable.
    v1.10.40 (`75776dbbb`) granted the first exemption and the two came apart:
    the test's own failure message asks for "a measured date and a reason",
    which the new entry carries, while its assertion demanded there be no entry
    at all.

    So this pins the SET — adding one still requires a visible edit here, which
    is the ratchet the old assertion actually bought — and additionally checks
    the shape the old message only described. Strictly more is checked than
    before, not less.

    That an exemption is still TRUE is a different question, and it is not
    asserted here on purpose: `STALE_INVENTORY_ENTRY` decides it against the
    real 543-gate population at gate-run time, which no unit test can afford.
    """
    assert set(G._ZERO_IS_A_PASS) == EXEMPTED_TODAY, (
        "the exemption inventory moved. An exemption is a gate whose zero is a "
        "CORRECT pass; adding one must be a deliberate, reviewed edit, so "
        "update EXEMPTED_TODAY in the same commit and say why in the entry.")
    for name, entry in G._ZERO_IS_A_PASS.items():
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry.get("measured", "")), (
            f"{name}: an exemption must record the DATE it was measured — an "
            f"undated one cannot be re-checked")
        reason = entry.get("reason", "")
        # A reason short enough to be a label is not an argument. The one real
        # entry runs to ~500 characters and cites the source line it came from.
        assert len(reason) >= 80, (
            f"{name}: the reason must argue why this zero is a CORRECT pass, "
            f"not merely name the gate again (got {len(reason)} chars)")


def test_a_stale_exemption_is_a_finding(monkeypatch, tmp_path):
    """EXERCISED, not asserted by substring. The first version of this test
    checked that the string `_MEASURED_ON` appeared in the source, which a
    rename to `_MEASURED_ON_X` satisfies. Drive it instead: an entry naming a
    gate that does NOT state a zero-and-exit-0 must raise
    STALE_INVENTORY_ENTRY, so the list can only shrink by a visible edit.

    It substitutes its own inventory rather than reading the real one — which
    since v1.10.40 is no longer empty — so the entry under test is the only one
    in play and the assertion cannot be satisfied by an unrelated exemption.
    """
    monkeypatch.setattr(G, "_ZERO_IS_A_PASS", {
        "a_gate_that_does_not_exist": {"measured": "2026-01-01",
                                       "reason": "stale on purpose"}})
    # A one-gate population so the probe is cheap; the entry names none of it.
    probe = tmp_path / "trivial_check.py"
    probe.write_text("import sys\nprint('PASS: 3 file(s) scanned')\n",
                     encoding="utf-8")
    verdict, findings, stats = G.audit(tmp_path, timeout=60, workers=1)
    kinds = {f["kind"] for f in findings}
    assert "STALE_INVENTORY_ENTRY" in kinds, (verdict, findings, stats)


@pytest.fixture
def synthetic_population(monkeypatch):
    """Audit a SYNTHETIC population without the real inventory bleeding in.

    `_ZERO_IS_A_PASS` is module-global and describes the real 543-gate
    registry, but `audit()` flags every entry it does not observe stating
    zero-and-rc-0 in the population it was handed. A tmp_path population of one
    made-up gate never contains `professional_tb_check`, so the moment the
    inventory stopped being empty EVERY synthetic audit began emitting
    `STALE_INVENTORY_ENTRY` — which is what turned main red at v1.10.40, not
    anything about the predicate these tests exist to check.

    `test_a_stale_exemption_is_a_finding` already isolates the inventory for
    exactly this reason; the two below only omitted it because an empty dict
    made the difference invisible. Isolating asserts nothing weaker: each test
    keeps its own assertion in full, over the population it actually built.

    (That `audit()` reads "this entry's gate was not in the population" as
    "this exemption went stale" is a real defect in the gate — an absence of
    observation reported as an observation of absence. It is out of scope for
    this main-red fix and is recorded on the PR rather than changed here.)
    """
    monkeypatch.setattr(G, "_ZERO_IS_A_PASS", {})


def test_a_gate_that_states_a_zero_and_exits_zero_is_a_finding(
        tmp_path, synthetic_population):
    """The prober's own positive control — without it, a PASS here could mean
    the predicate never matches anything."""
    (tmp_path / "silent_check.py").write_text(
        "print('PASS: analyzed 0 file(s)')\n", encoding="utf-8")
    verdict, findings, _ = G.audit(tmp_path, timeout=60, workers=1)
    assert verdict == "FINDINGS"
    assert findings[0]["kind"] == "ZERO_DENOMINATOR_EXITS_ZERO"


def test_a_gate_that_states_a_zero_and_REFUSES_is_not(
        tmp_path, synthetic_population):
    """THE ACCEPT CASE, and 20 of the 22 real ones are in it."""
    (tmp_path / "honest_check.py").write_text(
        "import sys\nprint('VACUOUS_PASS: analyzed 0 file(s)')\n"
        "sys.exit(2)\n", encoding="utf-8")
    verdict, findings, _ = G.audit(tmp_path, timeout=60, workers=1)
    assert verdict == "PASS", findings


def test_the_prober_is_not_in_its_own_population(tmp_path):
    """LOAD-BEARING, and found the expensive way. `project_check_programs` is
    `glob("*_check.py")`, so this file is in it: probing drove a nested copy,
    which drove another. It hung a landing gate for 35 minutes and left 75
    orphaned processes.

    `gate_discloses_denominator_check` has the same shape and survives only
    because its 120s per-gate budget truncates the recursion at depth 1 — which
    is exactly the "1 unrunnable" this gate's first census reported, and which
    went to 0 once the self-exclusion landed. A timeout absorbing a
    self-inflicted recursion is not the same as not having one.
    """
    import shutil
    shutil.copy(_PROGRAMS / "gate_zero_denominator_refuses_check.py",
                tmp_path / "gate_zero_denominator_refuses_check.py")
    (tmp_path / "other_check.py").write_text(
        "print('PASS: 3 file(s) scanned')\n", encoding="utf-8")
    # A one-second budget: if the prober drove itself, the nested run could not
    # finish inside it and would surface as `unrunnable`.
    _v, _f, stats = G.audit(tmp_path, timeout=20, workers=2)
    assert stats["gates_probed"] == 1, (
        f"probed {stats['gates_probed']} — the prober is in its own "
        f"population again")
    assert stats["unrunnable"] == 0, stats


def test_the_population_and_driver_are_imported_not_rebuilt():
    """A second scanner over the same question is how this repo has previously
    reproduced a bug the first one already defended against — the fresh
    directory per gate, in this case."""
    src = (_PROGRAMS / "gate_zero_denominator_refuses_check.py").read_text(
        encoding="utf-8")
    assert "from gate_discloses_denominator_check import" in src
    assert "_drive_on_empty_project" in src
