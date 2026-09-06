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
import textwrap

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
