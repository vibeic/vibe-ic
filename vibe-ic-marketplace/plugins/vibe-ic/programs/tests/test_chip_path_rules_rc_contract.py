"""The twelve chip-path rules obey ONE rc contract, and a crash is never a finding.

WHY THIS FILE EXISTS SEPARATELY FROM THE TWELVE PER-RULE TESTS
==============================================================
Each rule has its own test asserting its own verdicts. What none of them can
assert is the property the whole FAMILY has to share, because it is about what
happens when the checker itself goes wrong:

    Python exits 1 on an uncaught exception.

rc=1 is this family's code for "I found a defect". So a checker that raises —
a malformed input reaching an unguarded path, a helper import that fails, a
permission error — reports A FINDING it never made, in the one direction that
costs someone real work. The brief this lane implements names it exactly: an
escaped traceback that becomes rc=1 is an unearned claim about silicon.

Every one of the twelve wraps its scan in `try/except -> return 2`. That is easy
to write and easy to break later by moving one line of work outside the guard,
and NOTHING would notice: the checker would keep passing its own tests, because
its own tests exercise the paths that work.

WHAT THIS TEST DOES
===================
For each rule it replaces the scan function with one that raises, calls `main()`,
and requires rc=2. It also requires the failure to be ANNOUNCED rather than
swallowed — a silent 2 is a different defect with the same exit code.

MEASURED, WHICH IS WHY THE FAMILY IS TESTED AND NOT ASSUMED
===========================================================
One of these twelve shipped with a real instance of this class of error:
`every_required_metric_key_has_a_producer` computed its findings BEFORE checking
whether it had read any record, so over an empty corpus it printed nine
"STRUCTURALLY UNPROVABLE ... forever" lines and then returned NOT CHECKED. Its
exit code was correct and its output was an unearned claim, and its own tests
passed throughout, because they asserted the exit code.

chip-AGNOSTIC: exit codes and exception handling. No design, PDK or vendor literal.
"""
from __future__ import annotations

import contextlib
import importlib.util
import ast
import io
import os
import re
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

#: rule -> EVERY function that does scanning for it. A gate with two scanning
#: arms needs both injected: an arm that is not in this map is an arm whose
#: traceback can still escape, and the other arm's entry hides that from view.
#: `signoff_report_states_its_stage` is the live case — arm B was added after
#: this map was first written and inherited a passing test it never exercised.
SCANNERS = {
    "local_clone_does_not_borrow_objects": ("audit",),
    "prepared_checkout_states_the_revision_it_holds": ("audit_source",),
    "printed_remedy_runs_as_printed": ("audit",),
    "declared_basis_matches_the_session_inputs": ("audit",),
    "pytest_aggregate_carries_its_runtime_identity": ("_walk",),
    "explicit_argument_outranks_the_environment_pointer": ("audit",),
    "provenance_value_is_resolved_not_constant": ("audit",),
    "only_the_declaring_step_writes_its_output": ("audit",),
    "signoff_report_states_its_stage": ("scan", "sibling_stamp_gaps"),
    "every_required_metric_key_has_a_producer": ("evaluate",),
    "measurement_only_artefact_is_not_a_verdict_source": ("audit",),
    "generated_values_state_whether_they_were_read_or_defaulted": ("audit",),
}


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


#: rule -> prepares a tree that REACHES that rule's later arms. A bare tmp_path
#: is enough for a first arm, but a gate whose first arm returns 2 on an empty
#: directory never reaches its second, and the injection there tests nothing.
def _signoff_tree(root):
    f = (root / "vibe-ic-marketplace/plugins/vibe-ic/flow"
                "/phase1_phase2_phase3.yaml")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("steps:\n  - id: 23\n    required_outputs:\n"
                 "      - phase3/stage3/sta/post_route_timing.rpt\n")
    d = root / "vibe-ic-marketplace/plugins/vibe-ic/programs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "m.py").write_text(
        'def emit(project, body):\n'
        '    p = project / "sta" / "post_route_timing.rpt"\n'
        '    p.write_text("# STA_BASIS: POST_ROUTE_SPEF\\n" + body)\n')


TREES = {"signoff_report_states_its_stage": _signoff_tree}

_PAIRS = sorted((r, fn) for r, fns in SCANNERS.items() for fn in fns)


@pytest.mark.parametrize("rule,scanner", _PAIRS)
def test_a_crashing_scan_is_not_checked_never_a_finding(rule, scanner, tmp_path):
    """THE NEGATIVE CONTROL for the whole family: make the scan raise."""
    mod = _load(rule)
    prep = TREES.get(rule)
    if prep is not None:
        prep(tmp_path)
    assert hasattr(mod, scanner), (
        f"{rule} has no {scanner}() — this map has drifted from the source, and "
        f"a drifted map tests nothing")

    called = []

    def boom(*a, **k):
        called.append(1)
        raise RuntimeError("injected: the scan itself blew up")

    setattr(mod, scanner, boom)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = mod.main([str(tmp_path)])
    except Exception as exc:                        # noqa: BLE001
        pytest.fail(f"{rule}: the exception ESCAPED main() "
                    f"({type(exc).__name__}), so the process would exit 1 and a "
                    f"crash would be read as a finding")
    # VACUITY GUARD. If the injected function was never reached, this pair
    # proves nothing: an EARLIER arm returned 2 on its own and the assertions
    # below are satisfied by a gate that never ran the code under test. Measured:
    # registering `sibling_stamp_gaps` passed exactly this way, because `scan()`
    # fails first on a tmp_path with no flow file. A green that survives deleting
    # the guard it tests is the defect this family exists to refuse.
    assert called, (
        f"{rule}: {scanner}() was never called, so this pair is VACUOUS. Give "
        f"the rule a tree that reaches {scanner}() before asserting on its rc.")
    assert rc == 2, (
        f"{rule}: a crashing scan returned rc={rc}. rc=1 is this family's code "
        f"for 'I found a defect', so a crash would be published as one.")
    said = (out.getvalue() + err.getvalue()).upper()
    assert "NOT CHECKED" in said, (
        f"{rule}: returned 2 but never said so — a silent NOT CHECKED is a "
        f"different defect with the same exit code:\n{said[:400]}")


@pytest.mark.parametrize("rule", sorted(SCANNERS))
def test_a_bad_invocation_is_three_not_one(rule, tmp_path):
    """rc=3 exists so 'you pointed me at nothing' cannot be read as a finding."""
    mod = _load(rule)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = mod.main([str(tmp_path / "does-not-exist")])
    assert rc == 3, f"{rule}: absent root returned rc={rc}, expected 3"


@pytest.mark.parametrize("rule", sorted(SCANNERS))
def test_an_empty_population_reports_no_finding(rule, tmp_path):
    """An empty tree has no defects for the same reason it has nothing else.

    Pinned across the family because one of the twelve shipped violating it:
    findings computed from a source other than the population being counted, so
    every axis looked unprovable when no record had been read.
    """
    mod = _load(rule)
    (tmp_path / "unrelated.py").write_text("x = 1\n")
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = mod.main([str(tmp_path)])
    assert rc == 2, f"{rule}: empty tree returned rc={rc}, expected 2"
    findings = [ln for ln in out.getvalue().splitlines()
                if ln.strip() and not ln.startswith("examined")]
    assert not findings, (
        f"{rule}: an empty tree produced {len(findings)} finding line(s) on "
        f"stdout while returning NOT CHECKED — absence rendered as a "
        f"finding:\n" + "\n".join(findings[:5]))


# ── THE SWEEP AS A STANDING RULE ────────────────────────────────────────────
# A hardcoded map is only correct on the day it is written. The thirteenth gate
# added to this lane inherits nothing: it is simply absent from SCANNERS, every
# test above still passes, and its traceback escapes unexercised. So the map's
# COMPLETENESS is itself a test, keyed on the capture that defines this lane.
#
# Pre-existing repo gates that a rule was repointed onto are NOT in this family
# and carry their own tests; they are named here so the exemption is legible
# rather than silent.
_NOT_THIS_FAMILY = {
    "emitted_script_portability_check",     # pre-existing; the rule was repointed
}                                           # onto it after a duplicate was found

_CAPTURE = (_PROGRAMS.parents[3]
            / "docs/capture/2026-08-21-jcap-chip/recoveries.json")


def test_every_bucket_a_rule_with_a_program_is_swept():
    """Adding a gate without registering it must FAIL, not pass quietly."""
    # A SKIP HERE WOULD TAKE THE STANDING RULE DARK, so the two absences that
    # look identical to `is_file()` are separated.
    #
    # This plugin is shipped through a marketplace and can legitimately be
    # installed and tested WITHOUT the repository's docs/ tree. That is a real
    # skip. But if docs/capture/ is present and this one file is not, the
    # reference has ROTTED — the capture was renamed or moved — and skipping
    # would retire "a thirteenth gate added without registration must FAIL"
    # without anyone being told. The second case is a failure, not a skip.
    if not _CAPTURE.is_file():
        if not _CAPTURE.parent.parent.is_dir():
            pytest.skip(
                f"docs/capture/ is absent entirely — this is the packaged-plugin "
                f"context, where {_CAPTURE.name} legitimately does not ship")
        pytest.fail(
            f"docs/capture/ exists but {_CAPTURE} does not. The completeness "
            f"sweep is keyed on that file, so this is a rotted reference and "
            f"NOT a reason to stop enforcing registration. Re-point _CAPTURE at "
            f"wherever the capture moved to.")
    rows = json.loads(_CAPTURE.read_text(encoding="utf-8"))
    names = {r.get("rule_name") for r in rows if r.get("bucket") == "A"}
    assert names, "the capture declared no Bucket-A rule — this sweep is vacuous"
    with_program = {n for n in names if n and (_PROGRAMS / f"{n}.py").is_file()}
    assert with_program, (
        "no Bucket-A rule has a program, so this test would pass against a lane "
        "that shipped nothing at all")
    missing = with_program - set(SCANNERS) - _NOT_THIS_FAMILY
    assert not missing, (
        "these Bucket-A rules ship a program that NO rc-contract test injects a "
        "crash into, so a traceback in them exits 1 and is read as a finding "
        "about silicon:\n  " + "\n  ".join(sorted(missing)))


def test_the_completeness_sweep_can_actually_fail():
    """PROVE THE STANDING RULE FIRES. A completeness check that cannot fail is
    the same defect it exists to catch, one level up."""
    pretend = {"local_clone_does_not_borrow_objects", "a_thirteenth_gate"}
    missing = pretend - set(SCANNERS) - _NOT_THIS_FAMILY
    assert missing == {"a_thirteenth_gate"}, (
        "an unregistered gate did not survive the set difference, so the "
        "completeness assertion above could never fail")


def test_every_registered_scanner_exists():
    """The other direction: a map naming a function no longer in the module."""
    for rule, fns in sorted(SCANNERS.items()):
        mod = _load(rule)
        for fn in fns:
            assert hasattr(mod, fn), (
                f"{rule} has no {fn}() — the map drifted from the source and a "
                f"drifted map tests nothing")


# ── A VERDICT OWES A DENOMINATOR, AND SO DOES AN ADMISSION ──────────────────
# Two rules, folded into one sweep over the whole family:
#
#   * a real verdict (rc 0 or 1) owes the population it judged, on its own line,
#     so a PASS is legible as "looked at N and found none" rather than "found
#     none"; and
#   * rc=2 is not a verdict, it is an admission, and it must NAME what it could
#     not read. "NOT CHECKED" with nothing after it is indistinguishable from a
#     gate that decided not to bother.
#
# The empty-tree case above already builds the cheap fixture for the second, and
# it asserted only that no FINDING was printed — never that the gate said what it
# had failed to look at.

@pytest.mark.parametrize("rule", sorted(SCANNERS))
def test_not_checked_names_what_it_could_not_read(rule, tmp_path):
    mod = _load(rule)
    (tmp_path / "unrelated.py").write_text("x = 1\n")
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = mod.main([str(tmp_path)])
    assert rc == 2, f"{rule}: empty tree returned rc={rc}, expected 2"
    both = out.getvalue() + err.getvalue()
    assert "NOT CHECKED" in both.upper(), (
        f"{rule}: returned 2 without saying NOT CHECKED, so a caller reading the "
        f"text cannot tell an admission from a pass:\n{both[:300]}")
    # NAMING TAKES TWO SHAPES, AND DEMANDING THE WRONG ONE BREAKS A CORRECT GATE.
    #
    # When a population was established and turned out empty, the gate owes the
    # COUNT: "examined 0 X". When the declaration source itself was unreadable no
    # population was ever established, and "examined 0" would be a lie of a
    # familiar kind — it reads as "looked and found nothing" when the truth is
    # "could not look at all". Those two states are the whole subject of this
    # lane and must not be collapsed into one line.
    #
    # MEASURED: this assertion first demanded the count from all twelve and
    # reddened `only_the_declaring_step_writes_its_output` and
    # `signoff_report_states_its_stage`, both of which correctly name the flow
    # file they could not read. The gates were right and the assertion was wrong.
    denominator = [ln for ln in out.getvalue().splitlines()
                   if ln.strip().startswith("examined")]
    named_subject = re.search(r"(?:[\w./-]+\.(?:yaml|yml|json|py|rpt|sdc)"
                              r"|[\w-]+/[\w./-]+)", both)
    assert denominator or named_subject, (
        f"{rule}: said NOT CHECKED and named NEITHER the population it counted "
        f"nor the subject it could not read. A bare admission is "
        f"indistinguishable from a gate that decided not to bother:\n"
        f"{both[:300]}")
    if denominator:
        assert re.search(r"examined\s+\d", denominator[0]), (
            f"{rule}: the population line carries no count: {denominator[0]!r}")


def test_the_denominator_sweep_can_fail():
    """PROVE THE SWEEP FIRES — a bare NOT CHECKED must satisfy NEITHER shape."""
    def shapes(text):
        den = [ln for ln in text.splitlines()
               if ln.strip().startswith("examined")]
        sub = re.search(r"(?:[\w./-]+\.(?:yaml|yml|json|py|rpt|sdc)"
                        r"|[\w-]+/[\w./-]+)", text)
        return bool(den), bool(sub)

    assert shapes("[g] NOT CHECKED — nothing to see here\n") == (False, False), (
        "a bare NOT CHECKED satisfied one of the two naming shapes, so the "
        "sweep above could never fail")
    assert shapes("examined 0 widget(s)\n[g] NOT CHECKED — none\n")[0]
    assert shapes("[g] NOT CHECKED — flow/phase1.yaml is absent\n")[1]


# ── AN ASSERTION THAT COMPARES A LITERAL TO ITS OWN SIZE ────────────────────
# Standing rule: such an assertion can never fail, so it is the defect and not
# the guard. It is worth a sweep rather than vigilance because it arrives by
# editing -- a list grows by one, the number beside it is updated to match, and
# the assertion that was once a real expectation becomes a tautology in the same
# keystroke.

def _self_referential_assertions(source: str):
    """(line, why) for assertions that cannot fail by construction."""
    found = []
    tree = ast.parse(source)
    for scope in ast.walk(tree):
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        sizes = {}
        for n in ast.walk(scope):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                    and isinstance(n.targets[0], ast.Name) \
                    and isinstance(n.value, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
                v = n.value
                sizes[n.targets[0].id] = len(
                    v.keys if isinstance(v, ast.Dict) else v.elts)

        def _len_of(x):
            if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) \
                    and x.func.id == "len" and len(x.args) == 1 \
                    and isinstance(x.args[0], ast.Name):
                return x.args[0].id
            return None

        for n in ast.walk(scope):
            if not isinstance(n, ast.Assert) or not isinstance(n.test, ast.Compare):
                continue
            if not n.test.comparators:
                continue
            left, right = n.test.left, n.test.comparators[0]
            a, b = _len_of(left), _len_of(right)
            if a and b and a == b:
                found.append((n.lineno, f"len({a}) compared to len({a})"))
            elif a and isinstance(right, ast.Constant) \
                    and isinstance(right.value, int) and sizes.get(a) == right.value:
                found.append((n.lineno, f"len({a}) == {right.value}, and {a} is a "
                                        f"literal of exactly {right.value} here"))
            elif isinstance(left, ast.Name) and isinstance(right, ast.Name) \
                    and left.id == right.id:
                found.append((n.lineno, f"{left.id} compared to itself"))
    return found


def test_the_self_reference_detector_finds_known_positives():
    """VALIDATE THE INSTRUMENT ON A KNOWN ANSWER BEFORE TRUSTING ITS ZERO.

    A sweep that reports nothing is indistinguishable from a sweep that looks at
    nothing, and this lane has already been bitten by exactly that.
    """
    probe = ("def t1():\n"
             "    KNOWN = ['a', 'b', 'c']\n"
             "    assert len(KNOWN) == 3\n"
             "def t2():\n"
             "    ROWS = {'x': 1}\n"
             "    assert len(ROWS) == len(ROWS)\n"
             "def t3():\n"
             "    ROWS = ['a', 'b']\n"
             "    assert len(ROWS) == 5\n"
             "def t4(x):\n"
             "    seen = compute()\n"
             "    assert len(seen) == 3\n")
    lines = sorted(l for l, _ in _self_referential_assertions(probe))
    assert lines == [3, 6], (
        f"the detector found {lines}, expected the two known positives at lines "
        f"[3, 6] and neither of the two real expectations at 9 and 12")


def test_no_assertion_in_this_lane_compares_a_literal_to_its_own_size():
    lane = ("local_clone", "prepared_checkout", "printed_remedy", "declared_basis",
            "pytest_aggregate", "explicit_argument", "provenance_value",
            "only_the_declaring", "signoff_report", "every_required_metric",
            "measurement_only", "generated_values", "chip_path_rules")
    here = Path(__file__).resolve().parent
    targets = [p for p in sorted(here.glob("test_*.py"))
               + sorted(_PROGRAMS.glob("*.py")) if any(n in p.name for n in lane)]
    assert targets, "the sweep found no files, so its zero would mean nothing"
    bad = []
    for p in targets:
        try:
            for line, why in _self_referential_assertions(
                    p.read_text(encoding="utf-8")):
                bad.append(f"{p.name}:{line} — {why}")
        except SyntaxError:
            continue
    assert not bad, (
        "these assertions cannot fail by construction, so they are the defect "
        "and not the guard:\n  " + "\n  ".join(bad))


def test_the_capture_reference_has_not_rotted():
    """The sweep above is keyed on a file. Pin that the key still resolves.

    Kept separate from the sweep so the failure names the CAUSE: the sweep going
    quiet and the capture moving are different events and must not share a line.
    """
    if not _CAPTURE.parent.parent.is_dir():
        pytest.skip("packaged-plugin context — docs/capture/ does not ship")
    assert _CAPTURE.is_file(), (
        f"{_CAPTURE} is gone. Every registration guarantee in this file is keyed "
        f"on it, so its absence silently retires them.")
    rows = json.loads(_CAPTURE.read_text(encoding="utf-8"))
    assert any(r.get("bucket") == "A" for r in rows), (
        "the capture no longer declares a single Bucket-A rule, so the sweep "
        "would pass over an empty set")


# ── THE POPULATIONS THESE GATES DEPEND ON MUST STAY ALIVE ───────────────────
# The inverse of a gate reading a key that is never there is a gate whose CORPUS
# goes away. It then examines nothing, finds nothing, and passes — and a passing
# gate over an empty set is the failure this repository has already had: an
# unresolved corpus pointer once hid four hygiene failures behind a green run.
#
# The gates themselves say "examined 0 ... NOT CHECKED" and refuse to call that a
# pass, which is the first line of defence. This is the second: the SOURCES they
# draw from are asserted to be non-trivial here, so a corpus that moves is a red
# test rather than a quiet green suite.
#
# FLOORS, NOT PINS. Exact counts would break on every legitimate addition and
# would be re-dated rather than fixed, which is the habit the standing rules
# forbid. Measured at f8760c4e0: 69 steps, 164 required_outputs, 1250 top-level
# programs, 1236 JSON files. The floors sit far below all four.
_FLOORS = {"steps": 10, "required_outputs": 50, "programs": 500, "json": 100}


def _population_sizes():
    import yaml
    root = _PROGRAMS.parents[3]
    flow = (root / "vibe-ic-marketplace/plugins/vibe-ic/flow"
                   "/phase1_phase2_phase3.yaml")
    doc = yaml.safe_load(flow.read_text(encoding="utf-8"))
    steps = doc.get("steps") or []
    n_json = 0
    for dp, dn, fn in os.walk(root, followlinks=False):
        dn[:] = [d for d in dn if d not in (".git", "node_modules", "__pycache__")]
        n_json += sum(1 for f in fn if f.endswith(".json"))
    return {
        "steps": len(steps),
        "required_outputs": sum(len(s.get("required_outputs") or [])
                                for s in steps),
        "programs": len(list(_PROGRAMS.glob("*.py"))),
        "json": n_json,
    }


def test_the_populations_these_gates_draw_from_are_not_empty():
    sizes = _population_sizes()
    thin = {k: (v, _FLOORS[k]) for k, v in sizes.items() if v < _FLOORS[k]}
    assert not thin, (
        "a population these gates depend on has collapsed, so they would examine "
        "little or nothing and PASS. Fix the corpus or the pointer — never lower "
        "the floor:\n  " + "\n  ".join(
            f"{k}: {got} (floor {floor})" for k, (got, floor) in sorted(thin.items())))


def test_the_population_floor_check_can_fail():
    """PROVE IT FIRES — a collapsed corpus must not satisfy the floors."""
    collapsed = {"steps": 0, "required_outputs": 0, "programs": 1250, "json": 3}
    thin = {k: v for k, v in collapsed.items() if v < _FLOORS[k]}
    assert set(thin) == {"steps", "required_outputs", "json"}, (
        "the floor comparison did not catch a collapsed corpus, so the assertion "
        f"above could never fail: {thin}")
