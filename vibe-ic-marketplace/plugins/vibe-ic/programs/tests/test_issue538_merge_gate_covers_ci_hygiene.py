"""vibe-ic#538 — MERGE_OK must not be answered over 5 of 34 hygiene gates.

`gatekeeper_review` is what a maintainer runs before every push, and MERGE_OK
reads as "this will land green". Measured at v1.7.92 it was not:

    tools/ci/repo_hygiene_gates.sh wires        34 gate invocations
    gatekeeper_review.review() ran              17 gates of its own
    present in BOTH                              5
    in CI and invisible to the merge gate       29

Twice in one day the verdict was wrong. v1.7.89 was MERGE_OK and main went RED
on `published_record_staleness_check`. v1.7.92 was MERGE_OK while `INDEX.md`
was stale, and was caught only because the maintainer had by then taken to
running the hygiene script BY HAND — a step that appears in no skill, runbook
or agent file.

WHAT THESE TESTS PIN, AND WHAT THEY DELIBERATELY DO NOT
=======================================================
The repair is that the merge gate INVOKES the hygiene script instead of
carrying a second copy of its gate list. So the tests here never assert a
LITERAL COUNT of gates — a test that said `34` would have to be edited every
time CI grows a gate, which is the same hand-maintained-list defect one level
up. Every count below is DERIVED on both sides and compared:

    the record the script emits  ==  the `run` lines a parser finds in it

Adding a gate to CI moves both numbers together and no test needs touching;
wiring a gate through some new wrapper that skips the recording moves only one,
and that is red.

They also pin the OTHER direction, which is NOT a hole: the ten gates that
judge the LANDING rather than the tree (is this exactly one commit ahead of
main, is the version bump monotonic, does any commit message carry an NDA
token) stay merge-only. CI cannot meaningfully ask those questions, and
"fixing" that asymmetry would be a regression.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_SCRIPT = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
_LIB = _REPO / "tools" / "ci" / "_gate_dispatch.sh"

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_test_module(name: str):
    """Import a sibling TEST module for its fixture builders (not its tests)."""
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


GR = _load("gatekeeper_review")
#: The parser `gate_discloses_denominator_check` and `gate_host_independence_
#: check` already use over this same script. Imported rather than re-written so
#: this file does not become a third copy of it.
GD = _load("gate_discloses_denominator_check")


# --------------------------------------------------------------------------
# fixture helpers — a throwaway hygiene script that sources the REAL dispatch
# library, so these tests exercise the recording code that actually runs in CI
# rather than a copy of it.
# --------------------------------------------------------------------------
def _fixture_script(root: Path, gate_lines: str) -> Path:
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    script = root / "tools" / "ci" / "repo_hygiene_gates.sh"
    script.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT="{root}"
        PLUGIN="{_PROGRAMS.parent}"
        PG="{_PROGRAMS}"
        . "{_LIB}"
        gate_dispatch_init "$@"
        """) + gate_lines + "\ngate_dispatch_finish\n")
    return script


def _code_only(path: Path) -> str:
    """The module's executable substance: identifiers and non-docstring string
    literals, with comments and docstrings removed."""
    import ast
    tree = ast.parse(path.read_text())
    doc_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                doc_nodes.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in doc_nodes:
                out.append(node.value)
        elif isinstance(node, ast.Name):
            out.append(node.id)
        elif isinstance(node, ast.Attribute):
            out.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            out.append(node.name)
    return "\n".join(out)


def _probe(root: Path, name: str, body: str) -> Path:
    p = root / f"{name}.py"
    p.write_text(textwrap.dedent(body))
    return p


# ==========================================================================
# 1. THE COVERAGE IS DERIVED, NOT DUPLICATED
# ==========================================================================
def _label_matcher(decl):
    """A predicate accepting the labels one DECLARATION can produce.

    A literal label matches itself. A label carrying a shell expansion —
    `"macro OBS not crossed ($(basename "$(dirname "$_cell")"))"` — is a
    TEMPLATE: bash fills it in per iteration, so the concrete labels are only
    knowable by running the loop. The expansion is replaced by a wildcard and
    everything around it still has to match exactly, so two different
    templates cannot claim each other's invocations.
    """
    label = decl.label
    if "$" not in label:
        return lambda got: got == label
    pattern, i = [], 0
    while i < len(label):
        if label.startswith("$(", i):
            depth, j = 1, i + 2
            while j < len(label) and depth:
                depth += (label[j] == "(") - (label[j] == ")")
                j += 1
            pattern.append("(?s:.*)")
            i = j
        elif label[i] == "$":
            j = i + 1
            while j < len(label) and (label[j].isalnum() or label[j] == "_"):
                j += 1
            pattern.append("(?s:.*)")
            i = j
        else:
            pattern.append(re.escape(label[i]))
            i += 1
    rx = re.compile("".join(pattern) + r"\Z")
    return lambda got: bool(rx.match(got))


def reconcile(declarations, recorded_labels):
    """(records no declaration explains, literal declarations never invoked).

    A DECLARATION IS NOT AN INVOCATION. A `run` line inside a `for` is written
    once and executed once per iteration, so the two counts differ by design
    and comparing them for equality — which this file used to do — is red on a
    correct script. What must hold is that every invocation traces back to a
    declaration, and that a declaration OUTSIDE a loop actually fires. A
    templated declaration may legitimately fire zero times: its loop's glob
    matched nothing.
    """
    matchers = [(d, _label_matcher(d)) for d in declarations]
    fired = {id(d): 0 for d in declarations}
    unattributed = []
    for got in recorded_labels:
        hit = [d for d, m in matchers if m(got)]
        if not hit:
            unattributed.append(got)
            continue
        for d in hit:
            fired[id(d)] += 1
    silent = [d.label for d in declarations
              if d.runtime_expansion is None and fired[id(d)] == 0]
    return unattributed, silent


def firings(declarations, recorded_labels):
    """How many invocations each declaration explains, in declaration order.

    Deliberately a SECOND function rather than a third return value from
    `reconcile`: one of that helper's callers asserts on the whole tuple
    (``reconcile(...) == ([], [])``), so widening it would edit a test to
    accommodate a change instead of measuring one.

    This exists because the count is the thing the loop assertion below actually
    needs. Asking "did the loop expand" through the SIZES of two lists is a
    proxy, and the proxy is wrong at exactly one matched item -- see the comment
    at its call site.
    """
    matchers = [(d, _label_matcher(d)) for d in declarations]
    counts = {id(d): 0 for d in declarations}
    for got in recorded_labels:
        for d, m in matchers:
            if m(got):
                counts[id(d)] += 1
    return [counts[id(d)] for d in declarations]


def assert_invocations_decompose(declarations, recorded_labels):
    """The invocation count decomposes into the declarations that explain it.

    A FUNCTION rather than three inline asserts so that the positive controls
    can drive THIS, under `pytest.raises`, instead of restating its condition
    and asserting the restatement. A control that asserts a precondition tells
    you the precondition holds; it does not tell you the assertion still fires.
    """
    templated = [d for d in declarations if d.runtime_expansion]
    assert templated, (
        "no templated `run` line remains in the hygiene script, so a "
        "declaration and an invocation are now the same thing and this file's "
        "central distinction is untested. Restore a loop or delete the "
        "distinction -- do not leave this assertion passing over nothing.")
    counts = firings(declarations, recorded_labels)
    literal_total = sum(c for c, d in zip(counts, declarations)
                        if not d.runtime_expansion)
    templated_total = sum(c for c, d in zip(counts, declarations)
                          if d.runtime_expansion)
    assert literal_total + templated_total == len(recorded_labels), (
        "the invocation count does not decompose into the declarations that "
        f"explain it: {literal_total} literal + {templated_total} templated "
        f"!= {len(recorded_labels)} recorded")
    assert literal_total == len(declarations) - len(templated), (
        "a literal `run` line fired a number of times other than once: "
        f"{literal_total} invocations from "
        f"{len(declarations) - len(templated)} literal declarations")


def _list_record(script: Path, cwd: Path):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        rec = Path(td) / "record.json"
        # A real file, not `/dev/stdout`: `--list` also prints the labels, and
        # recovering the document by slicing at the first "{" would break the
        # moment a gate label contained one.
        out = subprocess.run(
            ["bash", str(script), "--list", "--summary-json", str(rec)],
            cwd=str(cwd), capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        return json.loads(rec.read_text())


def test_the_scripts_own_record_enumerates_every_gate_a_parser_finds():
    """Every gate the dispatcher records traces to a `run` line, and every
    unconditional `run` line reaches the dispatcher.

    This is the anti-drift assertion, and it is why nothing here says "34":
    both sides are derived from the same file by different means — one by
    EXECUTING it (`--list`, which records through the same `_dispatch` every
    real run goes through) and one by PARSING it. A gate wired through a
    wrapper that bypassed the recording would appear on the parser side only.

    IT USED TO ASSERT SET EQUALITY, and that was wrong in two directions at
    once. Measured at v1.9.77: the dispatcher recorded 68 invocations and the
    parser found 59 `run` lines, so the test was red — and BOTH numbers were
    describing something real. Nine of the invocations come from three
    `run_tolerating_uncheckable` lines inside `for _cell in …/benchmark-data/ic/
    */*/`, executed once per published cell; those three lines were invisible
    to the old regex (its label group `"([^"]+)"` stopped at the first inner
    quote of `$(basename "$(dirname "$_cell")")`). Fixing the parser alone
    would still have left the assertion red, because 62 declarations can never
    equal 68 invocations. Both were repaired: the parser sees the loop lines,
    and this reconciles rather than equates.
    """
    decls = GD.parse_declarations(_SCRIPT)
    assert decls, "the parser found no gates in the real hygiene script"
    doc = _list_record(_SCRIPT, _REPO)
    recorded = [g["label"] for g in doc["gates"]]

    unattributed, silent = reconcile(decls, recorded)
    assert not unattributed, (
        "the dispatcher recorded gate(s) no `run` line in the script "
        f"explains: {sorted(set(unattributed))}")
    assert not silent, (
        "these `run` lines are declared outside any loop and never reached "
        f"the dispatcher — they are wired through something that bypasses "
        f"the recording: {silent}")
    assert doc["declared"] == len(recorded)
    assert len(recorded) >= len(decls), (recorded, decls)
    # The loop really is what makes the two numbers differ, asserted so that a
    # future script with no loop does not leave this test passing vacuously
    # over an equality it no longer checks.
    #
    # IT USED TO ASK THAT THROUGH `len(recorded) > len(decls)`, and that is a
    # PROXY for "the loop expanded" rather than the property. The two disagree
    # at exactly ONE matched item: a templated `run` line that fires once
    # contributes one declaration and one invocation, so the sizes are EQUAL
    # while the loop is running perfectly. Measured on 2026-08-11 --
    # `git ls-files -- 'benchmark-data/ic/*/*/phase3/stage3/pnr/routed.def'`
    # returns exactly 1 path, so the three templated lines fire three times
    # against three declarations, and this assertion reported a defect that was
    # not there. It had been red on main since the corpus reached one cell.
    #
    # Asked directly instead. Two clauses, and BOTH are needed:
    #   1. a templated declaration must still EXIST -- otherwise the
    #      declaration-vs-invocation distinction this whole file is built on has
    #      quietly stopped being exercised, which is the vacuity the original
    #      comment was defending against;
    #   2. the books must CLOSE -- every recorded invocation is explained by
    #      some declaration, each literal one exactly once, each templated one
    #      as many times as its loop expanded. An equality over counts, so it
    #      cannot be satisfied by the corpus happening to have any size.
    # Both clauses live in `assert_invocations_decompose` so the two
    # POSITIVE_CONTROL tests below drive the REAL assertion under
    # `pytest.raises` rather than restating its condition -- a control that
    # asserts the precondition is a control that cannot tell you the assertion
    # still fires.
    assert_invocations_decompose(decls, recorded)


def test_a_continued_run_line_is_read_as_the_one_command_bash_runs():
    """The second half of the same parser defect, and the one no label count
    can see.

    Four gates in the real script are written across a `\\` continuation. The
    old regex captured only the first physical line, so `severity=ERROR is
    consumed` was handed to both readers as `… error_diagnostic_consumed_check
    .py . \\` — a trailing backslash where `--allow MACRO_STAGED_UNUSABLE`
    should be. argparse rejected the stray argument with rc 2 in BOTH trees,
    and the host-independence probe recorded the agreement as coverage of a
    gate it had never actually run.
    """
    continued = [d for d in GD.parse_declarations(_SCRIPT)
                 if d.label == "severity=ERROR is consumed"]
    assert len(continued) == 1, "the gate this was measured on is gone"
    assert continued[0].cmd.endswith("--allow MACRO_STAGED_UNUSABLE"), (
        "the continuation was dropped — the command is truncated",
        continued[0].cmd)
    assert "\\" not in continued[0].cmd, continued[0].cmd


def test_a_gate_wired_through_a_wrapper_that_skips_the_recording_is_CAUGHT():
    """The mutation the assertion above exists to fail on.

    Driven end to end against the REAL dispatch library, because the claim is
    about what `_dispatch` records and a fixture copy of it would not be
    evidence of anything.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _probe(root, "p_ok", 'print("PASS (0 item(s) examined)")\n')
        # `run_sneaky` matches the parser's `run(?:_\w+)?` shape and never
        # calls `_dispatch` — exactly the wrapper #538 is about.
        script = _fixture_script(root, (
            'run_sneaky() { ( cd "$2" && "${@:3}" ); }\n'
            f'run "declared and recorded" "$ROOT" python3 "{root}/p_ok.py"\n'
            f'run_sneaky "declared and INVISIBLE" "$ROOT" '
            f'python3 "{root}/p_ok.py"\n'))
        decls = GD.parse_declarations(script)
        doc = _list_record(script, root)
        recorded = [g["label"] for g in doc["gates"]]

    assert len(decls) == 2 and recorded == ["declared and recorded"]
    unattributed, silent = reconcile(decls, recorded)
    assert unattributed == []
    assert silent == ["declared and INVISIBLE"]


def test_one_looping_declaration_covers_every_iteration_it_produced():
    """The other direction, and the shape that was red.

    Three invocations from one `run` line must reconcile, and the label a
    template cannot predict must still be attributed to the line that wrote it.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _probe(root, "p_ok", 'print("PASS (0 item(s) examined)")\n')
        for cell in ("alpha", "beta", "gamma"):
            (root / "cells" / cell).mkdir(parents=True)
        script = _fixture_script(root, (
            'for _c in "$ROOT"/cells/*/; do\n'
            '  run "per cell ($(basename "$(dirname "$_c/x")"))" "$ROOT" '
            f'python3 "{root}/p_ok.py"\n'
            'done\n'))
        decls = GD.parse_declarations(script)
        doc = _list_record(script, root)
        recorded = [g["label"] for g in doc["gates"]]

    assert len(decls) == 1 and decls[0].runtime_expansion
    assert sorted(recorded) == ["per cell (alpha)", "per cell (beta)",
                                "per cell (gamma)"]
    assert reconcile(decls, recorded) == ([], [])
    # …and a record the template does NOT explain is still caught.
    assert reconcile(decls, recorded + ["something else"])[0] == \
        ["something else"]


def test_POSITIVE_CONTROL_the_loop_clause_fires_on_a_script_with_no_loop():
    """The clause that replaced `len(recorded) > len(decls)` must be able to die.

    The assertion it replaces was red on a correct script, which is one kind of
    useless. Swapping it for one that is green on EVERY script would be the
    other kind, and the more dangerous one, because it looks like a repair. So
    this drives the replacement over a script whose `run` lines are all literal
    and requires it to refuse.

    Not a unit test of a helper: it builds a real hygiene script, sources the
    real dispatch library, and asks the same two questions the live assertion
    asks — because a helper test gets greener the more thorough it is and never
    dies under the condition that matters.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _probe(root, "p_ok", "import sys\nprint('[PASS] fine')\nsys.exit(0)\n")
        script = _fixture_script(root, (
            f'run "flat one" "$ROOT" python3 "{root}/p_ok.py"\n'
            f'run "flat two" "$ROOT" python3 "{root}/p_ok.py"\n'))
        decls = GD.parse_declarations(script)
        doc = _list_record(script, root)
        recorded = [g["label"] for g in doc["gates"]]

    assert not [d for d in decls if d.runtime_expansion], \
        "fixture is wrong: it was supposed to have no loop"
    # THE REAL ASSERTION, driven over this script, required to DIE.
    with pytest.raises(AssertionError, match="no templated .run. line remains"):
        assert_invocations_decompose(decls, recorded)
    # …and the two clauses are independent: by every OTHER measure this script
    # is fine — every record is explained and every literal line fired once —
    # so the refusal above is the loop clause alone and not collateral.
    assert reconcile(decls, recorded) == ([], [])
    assert firings(decls, recorded) == [1, 1] and len(recorded) == 2


def test_POSITIVE_CONTROL_a_literal_line_firing_twice_is_caught():
    """The decomposition clause must die when a literal declaration over-fires.

    `len(recorded) > len(decls)` could not see this at all: a literal gate
    invoked twice makes recorded EXCEED decls, which the old assertion read as
    healthy loop expansion. Counting per declaration tells them apart.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _probe(root, "p_ok", "import sys\nprint('[PASS] fine')\nsys.exit(0)\n")
        # THE TEMPLATED LINE IS LOAD-BEARING, and its absence is what made this
        # control theatre. `assert_invocations_decompose` checks the LOOP clause
        # FIRST. A fixture of two literal `run` lines has no templated
        # declaration at all, so the loop clause raised and the decomposition
        # clause — the one this test is named for — was never reached. With a
        # bare `pytest.raises(AssertionError)` the two are indistinguishable,
        # and the control passed while asserting nothing about clause 2.
        # MEASURED: neutering BOTH decomposition clauses to `... or True` left
        # the file at 30 passed. The loop below satisfies clause 1 so the
        # decomposition clause is the one that must speak.
        script = _fixture_script(root, (
            f'run "twice over" "$ROOT" python3 "{root}/p_ok.py"\n'
            f'run "twice over" "$ROOT" python3 "{root}/p_ok.py"\n'
            'while IFS= read -r _x; do\n'
            '  [ -n "$_x" ] || continue\n'
            f'  run "per cell ($(basename "$_x"))" "$ROOT" '
            f'python3 "{root}/p_ok.py"\n'
            'done < <(printf "alpha\\n")\n'))
        decls = GD.parse_declarations(script)
        doc = _list_record(script, root)
        recorded = [g["label"] for g in doc["gates"]]

    # Clause 1 is SATISFIED here, so it cannot be what fires below.
    assert [d for d in decls if d.runtime_expansion], \
        "fixture is wrong: it was supposed to carry a templated declaration"
    # Two declarations sharing one label: every matcher claims every record, so
    # the per-declaration counts sum to MORE than there are records. The
    # templated line fires once and is explained exactly once.
    assert firings(decls, recorded) == [2, 2, 1], firings(decls, recorded)
    # THE REAL ASSERTION, driven over this script, required to DIE — and on the
    # DECOMPOSITION clause, not the loop clause, which is the half
    # `len(recorded) > len(decls)` was structurally unable to reach. `match=`
    # is what makes that sentence checkable rather than merely asserted.
    with pytest.raises(AssertionError, match="does not decompose"):
        assert_invocations_decompose(decls, recorded)
    # The old proxy would have read this script as HEALTHY: 3 declarations,
    # 3 records is not `recorded > decls`, and even a third duplicate would
    # have looked like loop expansion. Pinned so the regression is named.
    assert not (len(recorded) > len(decls))


def test_a_gate_added_to_ci_is_covered_with_no_edit_to_the_merge_gate():
    """The point of invoking rather than re-listing.

    A brand-new gate nobody told `gatekeeper_review` about must still be able
    to turn the verdict red. If this ever needed an edit to the merge gate,
    the second hand-maintained list would be back.
    """
    assert "repo_hygiene_gates.sh" in GR.__doc__
    # Judged on CODE, not on prose. The module deliberately NAMES the two
    # incidents in its comments — `published_record_staleness_check` is why
    # v1.7.89 went red — and a rule that could not tell an explanation from a
    # duplicated list would push the next author to delete the explanation.
    # Comments never reach the AST; docstrings are dropped explicitly; every
    # other string literal and identifier stays, which is the shape a real
    # copied gate list would take (`_PROGRAMS_DIR / "<name>.py"`).
    src = _code_only(_PROGRAMS / "gatekeeper_review.py")
    # The merge gate must not name the hygiene gates one by one. It legitimately
    # runs five of them itself against `--plugin-root`; anything BEYOND those
    # would be the copied list.
    own = {"source_chip_agnostic_check", "shipped_path_portability_check",
           "loop_watchdog_compliance_check", "marketplace_version_sync_check",
           "plugin_full_audit"}
    hygiene_programs = set()
    for _label, _wd, cmd in GD.parse_gates(_SCRIPT):
        for tok in cmd.split():
            # Unquote FIRST. The repo-root gates are written `"$PG/x.py"`, so a
            # suffix test before stripping sees a trailing quote and collects
            # only the eight plugin-relative gates — which left this assertion
            # blind to 26 of the 34 and let a mutation walk straight through it.
            tok = tok.strip('"')
            if tok.endswith(".py"):
                hygiene_programs.add(Path(tok).stem)
    assert len(hygiene_programs) >= 25, (
        f"only {len(hygiene_programs)} hygiene program name(s) recovered from "
        "the script — this assertion would be near-vacuous")
    leaked = sorted(p for p in (hygiene_programs - own) if p in src)
    assert not leaked, (
        "gatekeeper_review names hygiene gate program(s) directly instead of "
        f"invoking the script: {leaked} — that is the duplicated list #538 "
        "exists to remove")


def test_the_merge_gate_really_EXECUTES_the_script():
    """Proof of invocation, not of a plausible-looking summary.

    A gate that fabricated a record would pass every count assertion above.
    This one makes the fixture gate leave a side effect on disk.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        witness = root / "the_gate_ran"
        _probe(root, "p_touch", f"""
            from pathlib import Path
            Path({str(witness)!r}).write_text("ran")
            print("PASS (1 item(s) examined)")
        """)
        script = _fixture_script(
            root, f'run "touch" "$ROOT" python3 "{root}/p_touch.py"\n')
        res = GR.repo_hygiene_gate(root, script=script)
        # Read INSIDE the context manager: the witness lives under the
        # temporary directory, which is removed on exit.
        assert res.rc == 0, res.summary
        assert witness.read_text() == "ran", \
            "the hygiene script was never executed"


# ==========================================================================
# 2. A RED HYGIENE GATE REFUSES THE LANDING
# ==========================================================================
#: The minimal plugin tree `test_gatekeeper_review` already builds so the
#: file-walking gates report PASS quickly. Imported rather than re-created:
#: it has to track `plugin_full_audit`'s D2 guard list, and a second copy
#: would silently stop tracking it.
_TGR = _load_test_module("test_gatekeeper_review")


def _review_over(repo: Path, plugin: Path, script: Path):
    """Drive the full `review()` with a synthetic change-set, so the assertion
    is about the VERDICT a maintainer reads, not about one gate in isolation.

    `plugin_root` is the SYNTHETIC tree, not the real one: against the real
    plugin each of these took ~40s (`plugin_full_audit` alone is 52s there),
    and CI allows 180s per test on runners slower than this box. What is being
    asserted is `review()`'s aggregation of gate results into a verdict, which
    the synthetic root exercises identically.
    """
    return GR.review("HEAD", "HEAD", repo=repo, plugin_root=plugin,
                     override_files=["README.md"], override_cur=None,
                     override_prev=None, hygiene_script=script)


def test_a_failing_hygiene_gate_makes_the_verdict_REQUEST_CHANGES(tmp_path):
    root, plugin = _TGR._build_clean_plugin(tmp_path)
    _probe(root, "p_bad", """
        import sys
        print("found a defect")
        sys.exit(1)
    """)
    script = _fixture_script(
        root, f'run "a red gate" "$ROOT" python3 "{root}/p_bad.py"\n')
    v = _review_over(root, plugin, script)
    assert v.verdict == "REQUEST_CHANGES", v.gates
    assert any("repo_hygiene_gates" in b and "a red gate" in b
               for b in v.blocking), v.blocking


def test_a_clean_tree_still_returns_MERGE_OK(tmp_path):
    """No false alarm: the gate must not be a permanent red that gets ignored."""
    root, plugin = _TGR._build_clean_plugin(tmp_path)
    _probe(root, "p_ok", 'print("PASS (2 item(s) examined)")\n')
    script = _fixture_script(
        root, f'run "a green gate" "$ROOT" python3 "{root}/p_ok.py"\n')
    v = _review_over(root, plugin, script)
    hyg = [g for g in v.gates if g.name == "repo_hygiene_gates"]
    assert len(hyg) == 1 and hyg[0].rc == 0, [(g.name, g.rc) for g in v.gates]
    assert v.verdict == "MERGE_OK", v.blocking


# ==========================================================================
# 3. THE VERDICT SAYS WHAT IT DID NOT RUN
# ==========================================================================
def test_a_gate_that_refused_is_reported_apart_from_the_ones_that_passed(tmp_path):
    """`NOT_CHECKED` is never folded into the pass count.

    `run_tolerating_uncheckable` exists because a probe needing a clean tree
    must not fail a developer whose tree has scratch in it — but "I could not
    look" must not reach a reader as "I looked and it was clean". This is the
    `_vacuous_exit` convention applied to the hygiene set as a whole.
    """
    root = tmp_path / "r"
    root.mkdir()
    _probe(root, "p_ok", 'print("PASS (2 item(s) examined)")\n')
    _probe(root, "p_refuse", """
        import sys
        print("cannot look: the tree is dirty")
        sys.exit(2)
    """)
    script = _fixture_script(root, (
        f'run "a green gate" "$ROOT" python3 "{root}/p_ok.py"\n'
        # #584 — the tolerance is now BOUGHT at the wiring site. The property
        # this test pins is unchanged and is the one #584 had to preserve: an
        # EXEMPTED refusal is still non-blocking, because a permanently red
        # script is a skipped script. The unexempted arm lives in
        # `test_issue584_not_checked_is_load_bearing.py`.
        f'uncheckable_until 2999-01-01 "needs a clean checkout, which a '
        f'developer tree is not obliged to be"\n'
        f'run_tolerating_uncheckable "a refusing gate" "$ROOT" '
        f'python3 "{root}/p_refuse.py"\n'))
    res = GR.repo_hygiene_gate(root, script=script)
    assert res.rc == 0                      # non-blocking, as CI treats it
    assert "NOT CHECKED" in res.summary and "a refusing gate" in res.summary, \
        res.summary
    assert "not a pass" in res.summary


def test_the_summary_always_states_its_denominator(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    _probe(root, "p_ok", 'print("PASS (0 item(s) examined)")\n')
    script = _fixture_script(root, (
        f'run "one" "$ROOT" python3 "{root}/p_ok.py"\n'
        f'run "two" "$ROOT" python3 "{root}/p_ok.py"\n'
        f'run "three" "$ROOT" python3 "{root}/p_ok.py"\n'))
    res = GR.repo_hygiene_gate(root, script=script)
    assert "3/3" in res.summary, res.summary


def test_a_hygiene_script_that_wires_NOTHING_is_not_a_pass(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    script = _fixture_script(root, "# no gates at all\n")
    res = GR.repo_hygiene_gate(root, script=script)
    assert res.rc == 2 and not GR.GateResult("x", res.rc, "").green, res.summary
    assert "0 gates" in res.summary


def test_a_missing_hygiene_script_says_it_consulted_zero_gates(tmp_path):
    res = GR.repo_hygiene_gate(tmp_path / "no-such-tree")
    assert res.rc == -1
    assert "0 gate(s) consulted" in res.summary, res.summary


def test_a_run_that_never_finished_is_an_ERROR_not_a_pass(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    _probe(root, "p_slow", "import time; time.sleep(60)\n")
    script = _fixture_script(
        root, f'run "slow" "$ROOT" python3 "{root}/p_slow.py"\n')
    res = GR.repo_hygiene_gate(root, script=script, timeout=2)
    assert res.rc == 2 and "did not finish" in res.summary, res.summary


# ==========================================================================
# 4. NO SKIP BUTTON
# ==========================================================================
def test_the_cli_offers_no_way_to_skip_the_hygiene_set():
    """The seam that points at a fixture script is a function kwarg only.

    A command-line flag to skip or redirect the hygiene set would be a skip
    button on the one gate whose entire purpose is that it cannot be
    forgotten — which is how v1.7.92 nearly went red twice.
    """
    out = subprocess.run([sys.executable,
                          str(_PROGRAMS / "gatekeeper_review.py"), "--help"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    for forbidden in ("--hygiene", "--skip-hygiene", "--no-hygiene"):
        assert forbidden not in out.stdout, (
            f"{forbidden} is reachable from the CLI — that is a skip button")


# ==========================================================================
# 5. THE OTHER DIRECTION IS NOT A HOLE
# ==========================================================================
#: Gates that judge the LANDING, not the tree. CI cannot meaningfully ask "is
#: this exactly one commit ahead of main", so these are merge-gate-only BY
#: DESIGN. Listed here so that "fixing" the asymmetry — pushing them into the
#: repo-hygiene script, where they would be vacuous — turns a test red instead
#: of looking like an improvement.
_LANDING_ONLY = (
    "landing_is_one_commit_check", "version_bump_monotonic_check",
    "gatekeeper_stale_branch_check", "nda_diff_scan_check",
    "commit_msg_nda_check", "acceptance_control_check", "blindness_audit",
    "full_suite_run_check", "run_output_completeness_check",
    "real_artefact_test_backing_check",
    # Grades the control a base..head CHANGE was measured against. In the
    # repo-hygiene lane there is no change and no control run, so it would have
    # nothing to read and would report a vacuous clean result.
    "control_substance_check",
)


@pytest.mark.parametrize("gate", _LANDING_ONLY)
def test_landing_shaped_gates_stay_out_of_the_repo_hygiene_lane(gate):
    body = _SCRIPT.read_text()
    for label, _wd, cmd in GD.parse_gates(_SCRIPT):
        assert gate not in cmd, (
            f"{gate} judges the LANDING (a base..head range), not the tree; "
            f"wired into the repo-hygiene lane as {label!r} it would have no "
            f"range to judge and would report a vacuous clean result")
    assert body  # the script was actually read


# ==========================================================================
# 6. THE v1.7.92 INCIDENT, REPRODUCED AGAINST THE REAL TREE
# ==========================================================================
def test_a_new_program_without_a_regenerated_index_is_refused():
    """The v1.7.92 state, end to end through the merge gate.

    A program is added and `INDEX.md` is not regenerated — exactly what
    happened, and exactly what `gatekeeper_review` answered MERGE_OK over. The
    gate that catches it (`tools/gen_programs_index.py --check`) is one of the
    six in the hygiene set whose filename ends in neither `_check` nor
    `_audit`, so it is invisible to a name-shaped derivation of the gate list;
    only invoking the script reaches it.

    Uses the REAL gate against the REAL tree — the probe program is written
    into the live `programs/` directory and removed in `finally`, which is the
    technique `test_gate_discloses_denominator.py` already uses for the same
    reason: a fixture cannot prove a gate reads the artefacts it ships to read.
    """
    import tempfile
    # NOT `_probe_…`: `gen_programs_index._is_helper` skips any name starting
    # with an underscore, so the underscore-prefixed probe the neighbouring
    # denominator test uses would leave the index legitimately fresh and this
    # test would pass while proving nothing. Caught by the (a) control below,
    # which is the reason it is there.
    probe = _PROGRAMS / "probe_issue538_unindexed_throwaway.py"
    line = ('run "programs index fresh" "$ROOT" '
            f'python3 "{_REPO}/tools/gen_programs_index.py" --check\n')
    try:
        with tempfile.TemporaryDirectory() as td:
            script = _fixture_script(Path(td), line)

            # (a) control — before the program exists, the index is fresh.
            before = GR.repo_hygiene_gate(_REPO, script=script)
            assert before.rc == 0, (
                "the index was ALREADY stale before this test touched "
                f"anything, so it proves nothing: {before.summary}")

            # (b) the incident — a new program, no regenerated index.
            probe.write_text('"""throwaway (vibe-ic#538 test)."""\n')
            after = GR.repo_hygiene_gate(_REPO, script=script)
    finally:
        if probe.exists():
            probe.unlink()

    assert after.rc == 1, (
        "the merge gate did NOT refuse a landing that adds a program without "
        f"regenerating INDEX.md — this is the v1.7.92 state: {after.summary}")
    assert "programs index fresh" in after.summary


# ==========================================================================
# 7. vibe-ic#539 — THE ROLL-UP MUST NOT PRINT A SENTENCE THAT IS FALSE
# ==========================================================================
def _run_fixture_script(root: Path, gate_lines: str):
    script = _fixture_script(root, gate_lines)
    return subprocess.run(["bash", str(script)], cwd=str(root),
                          capture_output=True, text=True, timeout=60)


def test_the_rollup_does_not_claim_all_passed_when_a_gate_refused(tmp_path):
    """#539: `gate_host_independence_check` said, in those words, "This is not
    a pass" and exited 2, and the aggregation printed `all gates passed` over
    it. The gate was honest; the roll-up was not, and it is the roll-up a
    reader believes.

    The refusing gates must also be NAMED. A bare count cannot answer the only
    question a reader has — was it the gate I cared about?
    """
    root = tmp_path / "r"
    root.mkdir()
    _probe(root, "p_ok", 'print("PASS (2 item(s) examined)")\n')
    _probe(root, "p_refuse", """
        import sys
        print("DIRTY_CHECKOUT: this is not a pass")
        sys.exit(2)
    """)
    out = _run_fixture_script(root, (
        f'run "a green gate" "$ROOT" python3 "{root}/p_ok.py"\n'
        # #584 — see the note on the neighbouring refusal test.
        f'uncheckable_until 2999-01-01 "needs a clean checkout to compare '
        f'against a fresh worktree at the same commit"\n'
        f'run_tolerating_uncheckable "gates are host-independent" "$ROOT" '
        f'python3 "{root}/p_refuse.py"\n'))
    text = out.stdout + out.stderr
    assert "all gates passed" not in text, (
        "the roll-up still claims every gate passed while one REFUSED — "
        f"that is the false sentence #539 is about:\n{text}")
    # Scoped to the ROLL-UP LINE, not to the whole stream. `_dispatch` already
    # echoes a `── <label>` header for every gate, so asserting over all of
    # stdout is satisfied by that header and says nothing about whether the
    # summary names the refusal — a mutation replacing the name with "(some
    # gate)" walked straight through the unscoped version of this assertion.
    rollup = [ln for ln in out.stdout.splitlines()
              if ln.startswith("repo_hygiene_gates:")]
    assert len(rollup) == 1, f"expected exactly one roll-up line:\n{text}"
    assert "1 of 2 gate(s) passed" in rollup[0], rollup[0]
    assert "gates are host-independent" in rollup[0], (
        "the refusing gate is not NAMED in the roll-up; a bare count cannot "
        f"tell a reader whether the gate they care about ran:\n{rollup[0]}")
    assert "NOT a pass" in rollup[0], rollup[0]
    # rc stays 0 ON PURPOSE — see `gate_dispatch_finish`. A maintainer whose
    # tree is dirty by construction must not face a permanently red script,
    # because a permanently red gate is a skipped gate.
    assert out.returncode == 0, text


def test_the_unqualified_sentence_survives_when_nothing_refused(tmp_path):
    """The other half: the fix must not make the clean case read as degraded."""
    root = tmp_path / "r"
    root.mkdir()
    _probe(root, "p_ok", 'print("PASS (2 item(s) examined)")\n')
    out = _run_fixture_script(root, (
        f'run "one" "$ROOT" python3 "{root}/p_ok.py"\n'
        f'run "two" "$ROOT" python3 "{root}/p_ok.py"\n'))
    assert out.returncode == 0, out.stdout + out.stderr
    assert "all 2 gate(s) passed" in out.stdout, out.stdout
    assert "NOT CHECKED" not in out.stdout
