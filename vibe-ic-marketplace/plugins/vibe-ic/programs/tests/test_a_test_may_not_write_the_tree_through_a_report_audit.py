"""A test may not hand a CWD-resolving report audit a tree-relative output path.

THE MEASUREMENT (vibe-ic#2058 FP-13, lane czspmfp, host 8HD-6, image label
0.3.46, plugin v1.17.90). Run this ONE module, on a pristine checkout::

    $ python3 -m pytest tests/test_gds_geometry_signoff_wiring.py -q
    29 passed in 18.01s
    [FAIL] suite_write_guard: this pytest session WROTE INTO THE TREE —
      1 path(s) that `git add -A` would ship:
         M  .../programs/reports/phase3/antenna.json   (appeared)
    rc=1

Twenty-nine green assertions and a red session. The written path is TRACKED,
and the diff is a real one — the audit's summary gained `design_binding`
between the commit and the run::

    +    "design_binding": "NOT_DETERMINED",

THE MECHANISM, and why it is a class rather than one typo. `eda_report_audit`
resolves `--json` against the PROCESS CWD. `gds_antenna_deck_check`, invoked
three lines away in the same test, resolves its `--json` against the PROJECT it
was handed (`_verdict()` reads `proj / "out.json"`). Two programs, two meanings
for the same relative string, and a test helper that does not set `cwd`:

    _run(PROGRAMS / "antenna_report_check.py", proj,
         "--json", "reports/phase3/antenna.json")   # -> programs/reports/...
    _run(ANTENNA_GATE,                        proj,
         "--json", "out.json")                      # -> <proj>/out.json

PRODUCTION IS NOT THE DEFECT and is not changed to close this.
`flow_compliance_check` launches every gate with `cwd=project`, so step 26's
declared relative `reports/phase3/antenna_signoff.json` lands inside the run
directory exactly as declared. The rule below therefore binds TESTS, which do
not chdir, and leaves the flow's own declarations alone.

WHAT THIS GATE IS. A census over every test module in the tree, for calls that
name one of the seven CWD-resolving audit entry points AND pass an output flag
followed by a relative string literal. Population measured at v1.17.90: 1 (the
site above). Required population: 0.

BOTH DIRECTIONS, and the negative is the load-bearing half: `test_the_census_
still_sees_a_relative_output_path` feeds the census a synthetic module carrying
exactly the offending call and asserts it is caught. A census that cannot find
anything would pass this file forever while the tree filled up again.

NOT A STYLE RULE. `-` (stdout) is not a path and is exempt by name; an absolute
literal is fine; anything built from a fixture (`tmp_path`, `proj`) is not a
constant and is never examined.
"""
import ast
import pathlib
import re
import subprocess
import sys
import textwrap

Path = pathlib.Path

PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
TESTS = PROGRAMS / "tests"

#: The entry points that resolve `--json` against the process CWD. Derived from
#: the tree, never listed by hand: `eda_report_audit` is the implementation and
#: every `*_report_check.py` is a wrapper that forwards argv to its `main`.
def _cwd_resolving_entry_points() -> set:
    names = {"eda_report_audit.py"}
    for p in sorted(PROGRAMS.glob("*_report_check.py")):
        if "from eda_report_audit import main" in p.read_text(errors="replace"):
            names.add(p.name)
    return names


_OUT_FLAGS = {"--json", "--out", "--output"}
#: `-` is the conventional spelling of stdout, not a path.
_NOT_A_PATH = {"-"}


def _string_constants(call: ast.Call):
    for a in call.args:
        for n in ast.walk(a):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                yield n.value


def _offences_in_source(src: str, where: str, entry_points: set):
    """Every (line, flag, value) this module hands an audit as a relative path."""
    stems = {n[:-3] for n in entry_points}
    out = []
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        strs = set(_string_constants(node))
        names = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Attribute):
                names.add(n.attr)
            elif isinstance(n, ast.Name):
                names.add(n.id)
        if not (strs & entry_points or names & stems):
            continue
        for i, a in enumerate(node.args):
            if not (isinstance(a, ast.Constant) and a.value in _OUT_FLAGS):
                continue
            if i + 1 >= len(node.args):
                continue
            nxt = node.args[i + 1]
            if not (isinstance(nxt, ast.Constant)
                    and isinstance(nxt.value, str)):
                continue          # built from a fixture — not a tree literal
            if nxt.value in _NOT_A_PATH or nxt.value.startswith("/"):
                continue
            out.append((where, node.lineno, a.value, nxt.value))
    return out


def _census():
    entry_points = _cwd_resolving_entry_points()
    assert len(entry_points) >= 2, \
        f"the entry-point derivation found only {entry_points} — a census " \
        f"over an empty population cannot fail and is not a check"
    offences = []
    for f in sorted(TESTS.rglob("test_*.py")):
        try:
            src = f.read_text(errors="replace")
        except OSError:
            continue
        try:
            offences += _offences_in_source(
                src, str(f.relative_to(PROGRAMS)), entry_points)
        except SyntaxError:
            continue
    return offences


def test_no_test_hands_a_report_audit_a_tree_relative_output_path():
    offences = _census()
    assert offences == [], (
        "a test launches a CWD-resolving report audit with a relative output "
        "path. Under pytest the process CWD is the TREE, so the audit writes "
        "its verdict document into the checkout — measured once as a modified "
        "TRACKED file and a red `suite_write_guard`. Pass an absolute path "
        "(e.g. `proj / \"reports\" / \"phase3\" / \"antenna_signoff.json\"`):\n"
        + "\n".join(f"    {w}:{ln}  {flag} {val!r}"
                    for w, ln, flag, val in offences))


def test_the_census_still_sees_a_relative_output_path():
    """THE NEGATIVE CONTROL — the census must be able to fail.

    The synthetic module below is the exact call shape that was in the tree at
    v1.17.90. If this ever stops being reported, the gate above has become a
    tautology and the tree is unprotected.
    """
    planted = textwrap.dedent('''
        from pathlib import Path
        PROGRAMS = Path("x")

        def test_thing(proj):
            _run(PROGRAMS / "antenna_report_check.py", proj,
                 "--json", "reports/phase3/antenna.json")
    ''')
    got = _offences_in_source(planted, "<planted>",
                              _cwd_resolving_entry_points())
    assert [(ln, flag, val) for _, ln, flag, val in got] == [
        (6, "--json", "reports/phase3/antenna.json")], got


def test_an_absolute_path_and_a_dash_are_not_offences():
    """The census must not manufacture a finding either."""
    clean = textwrap.dedent('''
        from pathlib import Path
        PROGRAMS = Path("x")

        def test_abs(proj, tmp_path):
            _run(PROGRAMS / "antenna_report_check.py", proj,
                 "--json", "/tmp/somewhere/antenna.json")
            _run(PROGRAMS / "drc_report_check.py", proj, "--json", "-")
            _run(PROGRAMS / "sta_report_check.py", proj,
                 "--json", tmp_path / "sta.json")
    ''')
    assert _offences_in_source(clean, "<clean>",
                               _cwd_resolving_entry_points()) == []


# --------------------------------------------------------------------------- #
# measure_on_a_clean_tree — the guard #2058 item 3 names, and its control
# --------------------------------------------------------------------------- #
# The census above is STATIC: it reads source and finds the shape. It cannot
# see a write that arrives some other way — a program that grows a default
# output path, a helper that chdirs. This pair MEASURES instead:
#
#   measure_on_a_clean_tree     drive the audit exactly as the fixed module
#                               drives it, and assert `git status` is unchanged
#   the negative control        drive it the PRE-FIX way inside a THROWAWAY git
#                               repo and assert the same comparison SEES the
#                               write — so the assertion above is known to be
#                               capable of failing, without ever dirtying the
#                               real checkout to prove it
#
# WHICH OF THESE ACTUALLY CATCHES A REGRESSION — measured, not assumed. Reverting
# `test_gds_geometry_signoff_wiring.py` to its pre-fix relative `--json` and
# re-running this whole file:
#
#     test_no_test_hands_a_report_audit_a_tree_relative_output_path   FAILED
#     measure_on_a_clean_tree                                         passed
#     the negative control                                            passed
#     (and the module itself: 29 passed, rc 1, "WROTE INTO THE TREE")
#
# So the CENSUS is the regression guard; `measure_on_a_clean_tree` drives its own
# absolute-path call and by construction cannot see another module's call site.
# What the pair adds is the MECHANISM: that the audit writes nothing when driven
# correctly, and that a write WOULD be seen if one happened. Do not read a green
# `measure_on_a_clean_tree` as "no test writes into the tree" — that is the
# census's claim, and only the census can lose it.
sys.path.insert(0, str(PROGRAMS))
import suite_write_guard as _swg                                # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def test_measure_on_a_clean_tree(tmp_path):
    """THE GUARD (vibe-ic#2058 item 3). Running the audit the way this tree's
    tests now run it must leave `git status --porcelain` exactly as it was.

    MEASURED before the fix: `pytest tests/test_gds_geometry_signoff_wiring.py`
    was `29 passed` AND rc 1, with `suite_write_guard` naming the TRACKED
    `programs/reports/phase3/antenna.json` as having appeared.
    """
    repo = Path(_git(PROGRAMS, "rev-parse", "--show-toplevel").stdout.strip()
                or PROGRAMS)
    before = _swg.snapshot(repo)

    proj = tmp_path / "proj" / "reports" / "phase3"
    proj.mkdir(parents=True)
    (proj / "antenna.rpt").write_text(
        "OpenROAD check_antennas (ANT)\n"
        "antenna check: 0 net violations, 0 pin violations\n"
        "antenna clean: YES\n" + "# " + "x" * 400 + "\n")
    cp = subprocess.run(
        [sys.executable, str(PROGRAMS / "antenna_report_check.py"),
         str(tmp_path / "proj"), "--mode", "antenna",
         "--json", str(tmp_path / "out.json")],
        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout[-400:]
    assert (tmp_path / "out.json").is_file(), "the audit wrote nothing at all"

    result = _swg.compare(before, _swg.snapshot(repo))
    assert result["blocking"] == [], (
        "the audit wrote into the tree under test: "
        + ", ".join(f["path"] for f in result["blocking"]))


def test_the_clean_tree_guard_can_see_a_write(tmp_path):
    """THE NEGATIVE CONTROL, and it never touches the real checkout.

    A guard that cannot fail proves nothing, but proving THIS one can must not
    mean dirtying the tree it protects. So the pre-fix call shape is driven
    inside a throwaway git repo: a RELATIVE `--json`, resolved against the
    process CWD exactly as `eda_report_audit` resolves it, lands inside that
    repo and the same `snapshot`/`compare` pair reports it.
    """
    repo = tmp_path / "throwaway"
    (repo / "reports" / "phase3").mkdir(parents=True)
    _git(repo.parent, "init", "-q", str(repo))
    (repo / "reports" / "phase3" / "keep.txt").write_text("tracked\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    assert _git(repo, "status", "--porcelain").stdout == "", "fixture not clean"

    proj = repo / "proj" / "reports" / "phase3"
    proj.mkdir(parents=True)
    (proj / "antenna.rpt").write_text(
        "OpenROAD check_antennas (ANT)\n"
        "antenna check: 0 net violations, 0 pin violations\n"
        "antenna clean: YES\n" + "# " + "x" * 400 + "\n")

    before = _swg.snapshot(repo)
    cp = subprocess.run(                       # the PRE-FIX shape: relative --json
        [sys.executable, str(PROGRAMS / "antenna_report_check.py"),
         str(repo / "proj"), "--mode", "antenna",
         "--json", "reports/phase3/antenna.json"],
        cwd=str(repo), capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout[-400:]
    assert (repo / "reports" / "phase3" / "antenna.json").is_file(), \
        "the relative path did not resolve against the process CWD — the " \
        "mechanism this guard exists for is not the mechanism being tested"

    result = _swg.compare(before, _swg.snapshot(repo))
    assert result["blocking"], \
        "the guard did not see a write it must see — it cannot fail, so the " \
        "clean-tree assertion above proves nothing"
    assert any("antenna.json" in f["path"] for f in result["blocking"]), \
        [f["path"] for f in result["blocking"]]


def test_the_production_call_site_is_unchanged_by_name(tmp_path):
    """THE CONTROL #2058 item 3 names: production is NOT the defect and must
    NOT have been edited to work around it.

    `flow_compliance_check` launches every gate with `cwd=project`, so step 26's
    RELATIVE declaration lands inside the run directory exactly as written. The
    fix belongs in the tests, which do not chdir. If this declaration ever grows
    an absolute path, someone has moved the fix to the wrong side.
    """
    flow = (PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml").read_text()
    decls = re.findall(r'"(antenna_report_check [^"]*)"', flow)
    assert decls, "step 26 no longer declares antenna_report_check at all"
    for d in decls:
        m = re.search(r"--json\s+(\S+)", d)
        assert m, f"the declaration states no --json target: {d}"
        assert not m.group(1).startswith("/"), (
            f"step 26's declared output path became ABSOLUTE ({m.group(1)}). "
            f"The gate runs with cwd=project; a relative path is correct there "
            f"and this is the production side the test-side fix must not have "
            f"moved into")
        assert m.group(1) == "reports/phase3/antenna_signoff.json", d
