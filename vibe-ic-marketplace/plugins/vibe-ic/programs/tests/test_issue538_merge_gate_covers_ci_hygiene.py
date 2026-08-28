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

import _watchdog  # noqa: E402


def _supervised(cmd, **kw):
    """`subprocess.run(cmd, capture_output=True, text=True, check=False)` with
    the wall-clock budget REPLACED by forward-progress supervision.

    These call sites used to carry a fixed `timeout=`. That number is not a
    property of the subject — it is a guess about a HOST — and when the guess is
    wrong on a loaded machine `TimeoutExpired` propagates out of the test and is
    recorded as the SUBJECT being broken. The verdict is then manufactured by
    the machine rather than measured on the program; the owner hit exactly that
    on a module nobody had changed.

    `_watchdog.run_host_supervised` bounds NO FORWARD PROGRESS instead — CPU and
    I/O summed over the child's whole /proc tree, plus the growth of its
    captured output — so a child that is merely slow runs to completion however
    long that legitimately takes, while one that is genuinely hung is still
    killed. A kill arrives as rc `_watchdog.RC_STALLED` with WATCHDOG_STALLED on
    stderr: a distinct code none of these subjects produces itself, so a hang
    can never be misread as an ordinary non-zero exit."""
    res = _watchdog.run_host_supervised(cmd, **kw)
    return _watchdog.completed_process(cmd, res)


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


#: The dispatcher's synthetic row for a corpus that expanded to nothing. Written
#: by `gate_dispatch_over` in `tools/ci/_gate_dispatch.sh` (vibe-ic#1075), NOT by
#: any `run` line — see `split_empty_corpus_records`.
#:
#: THERE ARE THREE OF THEM, not one, and each is written out in full rather than
#: reached by loosening the first. vibe-ic#1764 split the population refusal into
#: the states it had been collapsing — a corpus that was READ and holds none, a
#: corpus that was NOT FOUND so nothing was opened, and a producer that FAILED so
#: the denominator is unknown. A `.+` in place of the differing clause would let
#: any future dispatcher row walk past the fabrication control below, which is
#: the one assertion in this file that catches an invented gate; so the price of
#: a new row is a new anchored pattern here, deliberately.
_POPULATION_REFUSAL_LABEL_RES = (
    re.compile(r'\Acorpus "(?P<name>.+)" is EMPTY — nothing was checked over it\Z'),
    re.compile(r'\Acorpus "(?P<name>.+)" was NOT FOUND — nothing was opened to check\Z'),
    re.compile(r'\Acorpus "(?P<name>.+)" producer FAILED — denominator unknown\Z'),
)
#: The original name, kept because it is the shape the live hygiene script emits
#: whenever its corpus is bound and holds no routed DEF.
_EMPTY_CORPUS_LABEL_RE = _POPULATION_REFUSAL_LABEL_RES[0]


#: Leading shell environment assignments on a command line, e.g. the
#: `GATE_DISPATCH_ATTEST_POPULATION=1 ` in front of a `gate_dispatch_over` call.
_ENV_ASSIGN_PREFIX = re.compile(
    r'^(?:[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|\'[^\']*\'|\S*)\s+)+')


def declared_corpora(script: Path):
    """Every corpus name the script hands to `gate_dispatch_over`, by PARSING.

    Deliberately read out of the script rather than out of the record's own
    `corpora` list: this file's whole design is that one side EXECUTES the
    script and the other PARSES it, and letting the record vouch for its own
    synthetic rows would collapse that into the document explaining itself.
    """
    out = []
    for _lineno, line in GD._logical_lines(script.read_text(errors="replace")):
        # A leading `NAME=value` assignment is part of the COMMAND, not a
        # different command: `VAR=1 cmd args` runs `cmd` with VAR in its
        # environment. 7c376e348 (v1.10.69) declared the routed-DEF corpus as
        # `GATE_DISPATCH_ATTEST_POPULATION=1 gate_dispatch_over ...`, and a
        # prefix match alone stopped seeing it — so its dispatcher row looked
        # fabricated, which is the one thing this test is meant to catch for
        # real. Strip the assignments, then match the command.
        stripped = _ENV_ASSIGN_PREFIX.sub("", line.strip())
        if not stripped.startswith("gate_dispatch_over"):
            continue
        got = GD._read_quoted(stripped[len("gate_dispatch_over"):].strip())
        if got is not None:
            out.append(got[0])
    return out


def split_empty_corpus_records(recorded_labels):
    """(`run`-line invocations, corpus names whose loop expanded to NOTHING).

    A RECORD IS NOT ALWAYS AN INVOCATION. `gate_dispatch_over` deliberately
    appends one synthetic NOT_CHECKED row when its producer yields zero items,
    because until vibe-ic#1075 a corpus that silently emptied cost the run
    nothing and read exactly like a corpus with nothing wrong in it. That row is
    written by the dispatcher, not by a `run` line, so no declaration can ever
    explain it and `reconcile` was right to call it unattributed — it was being
    asked the wrong question.

    MEASURED on this checkout: the corpus `published cells carrying a routed
    DEF` is 1 item on origin/main and 0 here, because the published cells moved
    to `vibeic/benchmark-data`. At 0 the dispatcher emits its synthetic row, the
    live reconciliation reported "the dispatcher recorded gate(s) no `run` line
    explains", and the merge gate looked broken. Nothing about the merge gate
    changed; a corpus emptied.

    Partitioning here rather than teaching `reconcile` about corpora keeps the
    drift check at full strength AND makes it independent of how many cells
    happen to be published — the same test now runs at 0 items and at 100. The
    caller must still prove each name is one the script DECLARES; a synthetic
    row naming a corpus no `gate_dispatch_over` line mentions is exactly the
    fabrication this file exists to catch, so it is returned, not swallowed.

    IT PARTITIONS EVERY POPULATION REFUSAL, not only the empty one. vibe-ic#1764
    gave a corpus that was NOT FOUND its own row, because "I read the index and
    it holds none" and "there was no index to read" had been arriving here as
    the same sentence; a producer that FAILED has had its own row since #1739.
    All three are written by the dispatcher and none of them can ever trace to a
    `run` line, so all three are set aside — and all three still have to name a
    corpus the script declares.
    """
    invocations, empty = [], []
    for label in recorded_labels:
        matched = next(
            (m for m in (rx.match(label)
                         for rx in _POPULATION_REFUSAL_LABEL_RES) if m), None)
        if matched:
            empty.append(matched.group("name"))
        else:
            invocations.append(label)
    return invocations, empty


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
        out = _supervised(
            ["bash", str(script), "--list", "--summary-json", str(rec)],
            cwd=str(cwd))
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

    # A record written BY THE DISPATCHER rather than by a `run` line is set
    # aside first — and only after the script is made to account for it. See
    # `split_empty_corpus_records`: an empty corpus leaves a synthetic
    # NOT_CHECKED row behind on purpose, and reconciling it against `run` lines
    # asks a question it can never answer. It is not waved through: its corpus
    # must be one the script DECLARES, so a synthetic-looking label the script
    # never asked for is still a fabricated gate and still red.
    invocations, empty_corpora = split_empty_corpus_records(recorded)
    fabricated = sorted(set(empty_corpora) - set(declared_corpora(_SCRIPT)))
    assert not fabricated, (
        "the dispatcher recorded an EMPTY-corpus row for a corpus no "
        f"`gate_dispatch_over` line in the script declares: {fabricated}")

    unattributed, silent = reconcile(decls, invocations)
    assert not unattributed, (
        "the dispatcher recorded gate(s) no `run` line in the script "
        f"explains: {sorted(set(unattributed))}")
    assert not silent, (
        "these `run` lines are declared outside any loop and never reached "
        f"the dispatcher — they are wired through something that bypasses "
        f"the recording: {silent}")
    assert doc["declared"] == len(recorded)
    # IT USED TO SAY `len(recorded) >= len(decls)`, and that is false on a
    # correct script the moment a loop expands to nothing: 4 templated `run`
    # lines that fire zero times are 4 declarations backing 0 invocations, so
    # 80 recorded invocations against 84 declarations is the HEALTHY reading of
    # an empty corpus. What actually holds in every case is that each LITERAL
    # declaration contributes one invocation, so the invocations can never fall
    # below the literal count. `assert_invocations_decompose` then makes the
    # books close exactly; this is the floor it cannot be satisfied without.
    literal = [d for d in decls if not d.runtime_expansion]
    assert len(invocations) >= len(literal), (invocations, literal)
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
    assert_invocations_decompose(decls, invocations)


def test_an_EMPTY_corpus_reconciles_and_a_FABRICATED_one_still_does_not():
    """The control for `split_empty_corpus_records`, which must not become a
    hole through which any unexplained record escapes.

    Driven over a REAL script that sources the REAL dispatch library and runs a
    `gate_dispatch_over` whose producer prints nothing — the same code path the
    live hygiene script takes here — so this measures the dispatcher's actual
    behaviour rather than a hand-written label.

    Three things, and the third is the one that makes the partition safe:

      1. the empty corpus DOES leave a synthetic row behind (vibe-ic#1075); if
         it ever stops, this control dies rather than quietly passing over a
         shape that no longer occurs;
      2. with that row set aside the reconciliation is clean, which is the
         repair — the same script reconciles at 0 items and at 3;
      3. a synthetic-looking row naming a corpus the script never declared is
         STILL unexplained. Without this, "is EMPTY — nothing was checked over
         it" would be a phrase any fabricated label could wear to walk past the
         one assertion that catches fabricated labels.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _probe(root, "p_ok", "import sys\nprint('[PASS] fine')\nsys.exit(0)\n")
        script = _fixture_script(root, (
            f'run "flat one" "$ROOT" python3 "{root}/p_ok.py"\n'
            '_per_item() {\n'
            f'  run "per cell ($(basename "$1"))" "$ROOT" '
            f'python3 "{root}/p_ok.py"\n'
            '}\n'
            'gate_dispatch_over "cells that do not exist" _per_item '
            'printf ""\n'))
        decls = GD.parse_declarations(script)
        doc = _list_record(script, root)
        recorded = [g["label"] for g in doc["gates"]]
        # Read inside the tempdir's lifetime — the script is gone below.
        corpora = declared_corpora(script)

    assert corpora == ["cells that do not exist"]

    # 1. the dispatcher really does record the empty corpus.
    invocations, empty = split_empty_corpus_records(recorded)
    assert empty == ["cells that do not exist"], recorded
    assert len(recorded) == len(invocations) + 1

    # 2. and with it set aside, a script whose loop expanded to nothing is
    #    clean — one literal declaration, one invocation, one templated
    #    declaration that legitimately fired zero times.
    assert reconcile(decls, invocations) == ([], [])
    assert_invocations_decompose(decls, invocations)
    # Reconciling the RAW record is what was red, and naming it here is what
    # stops the partition being confused for a no-op.
    assert reconcile(decls, recorded)[0] == [
        'corpus "cells that do not exist" is EMPTY — nothing was checked over it']

    # 3. THE CLAUSE THAT KEEPS IT HONEST: same phrasing, corpus the script never
    #    declared, still caught.
    forged = 'corpus "a corpus nobody declared" is EMPTY — nothing was checked over it'
    _inv, forged_empty = split_empty_corpus_records(recorded + [forged])
    assert sorted(set(forged_empty) - set(corpora)) == ["a corpus nobody declared"]
    # …and a record that is not the synthetic shape at all is untouched by the
    # partition and reaches `reconcile` as before.
    assert split_empty_corpus_records(["something else"]) == (["something else"], [])


def test_a_NOT_FOUND_corpus_reconciles_and_a_FABRICATED_one_still_does_not():
    """The same control for vibe-ic#1764's row, and it is a separate test.

    Folding it into the sibling above would have let one shape stand in for
    both, which is the exact substitution #1764 filed: a corpus NOTHING OPENED
    reported under the row that says a corpus WAS READ. The two rows are pinned
    apart here for the same reason they are pinned apart in the dispatcher.

    Driven over a REAL script sourcing the REAL dispatch library, whose producer
    exits `GATE_DISPATCH_ABSENT_RC` — the code `tools/ci/routed_def_corpus.py`
    leaves with when no corpus resolves.
    """
    import tempfile
    absent_rc = re.search(r'^GATE_DISPATCH_ABSENT_RC=(\d+)$',
                          _LIB.read_text(encoding="utf-8"), re.MULTILINE)
    assert absent_rc, (
        "the dispatcher no longer declares GATE_DISPATCH_ABSENT_RC, so a corpus "
        "nothing opened has no row of its own (vibe-ic#1764)")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _probe(root, "p_ok", "import sys\nprint('[PASS] fine')\nsys.exit(0)\n")
        script = _fixture_script(root, (
            f'run "flat one" "$ROOT" python3 "{root}/p_ok.py"\n'
            '_per_item() {\n'
            f'  run "per cell ($(basename "$1"))" "$ROOT" '
            f'python3 "{root}/p_ok.py"\n'
            '}\n'
            'gate_dispatch_over "cells nobody could open" _per_item '
            f"bash -c 'exit {absent_rc.group(1)}'\n"))
        decls = GD.parse_declarations(script)
        doc = _list_record(script, root)
        recorded = [g["label"] for g in doc["gates"]]
        corpora = declared_corpora(script)

    assert corpora == ["cells nobody could open"]

    # 1. the dispatcher really does record the NOT FOUND corpus, and NOT under
    #    the empty corpus's row.
    not_found = ('corpus "cells nobody could open" was NOT FOUND — nothing was '
                 'opened to check')
    assert not_found in recorded, recorded
    assert not any("is EMPTY" in label for label in recorded), recorded

    # 2. with it set aside the reconciliation is clean.
    invocations, empty = split_empty_corpus_records(recorded)
    assert empty == ["cells nobody could open"], recorded
    assert len(recorded) == len(invocations) + 1
    assert reconcile(decls, invocations) == ([], [])
    assert_invocations_decompose(decls, invocations)
    assert reconcile(decls, recorded)[0] == [not_found]

    # 3. the clause that keeps it honest: same phrasing, corpus the script never
    #    declared, still caught.
    forged = ('corpus "a corpus nobody declared" was NOT FOUND — nothing was '
              'opened to check')
    _inv, forged_empty = split_empty_corpus_records(recorded + [forged])
    assert sorted(set(forged_empty) - set(corpora)) == ["a corpus nobody declared"]


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


def test_a_run_with_no_forward_progress_is_an_ERROR_not_a_pass(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    _probe(root, "p_slow", "import time; time.sleep(60)\n")
    script = _fixture_script(
        root, f'run "slow" "$ROOT" python3 "{root}/p_slow.py"\n')
    res = GR.repo_hygiene_gate(root, script=script, stall_grace=1)
    assert res.rc == 2 and "progress watchdog" in res.summary, res.summary
    assert "nothing was concluded" in res.summary


# ==========================================================================
# 4. NO SKIP BUTTON
# ==========================================================================
def test_the_cli_offers_no_way_to_skip_the_hygiene_set():
    """The seam that points at a fixture script is a function kwarg only.

    A command-line flag to skip or redirect the hygiene set would be a skip
    button on the one gate whose entire purpose is that it cannot be
    forgotten — which is how v1.7.92 nearly went red twice.
    """
    out = _supervised([sys.executable,
                       str(_PROGRAMS / "gatekeeper_review.py"), "--help"])
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
    return _supervised(["bash", str(script)], cwd=str(root))


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


# ── One gate, declared twice: clean to git, invisible to every check above ──
#
# vibe-ic#1241 shard PR #1256 wired `atomic_artifact_write_check` at line 159
# of the hygiene script. Its base branch had already wired the SAME program,
# blockingly, at line 981. The two `run` lines sit ~840 lines apart, so:
#
#     git merge <base> <shard>          rc=0, NO conflict reported
#     grep -c atomic_artifact_write_check.py  ->  2
#
# and the merged landing gate runs the checker TWICE under two different
# labels. Nothing caught it. `checker_execution_wiring_audit` asks whether a
# checker is run, not how many times; the reconciliation above asks whether
# every record traces to a `run` line and every `run` line reaches the
# dispatcher, and two honest declarations firing once each satisfy both.
#
# MEASURED on the merged tree before writing this: 30 passed.
#
# WHY THE KEY IS THE WHOLE INVOCATION, NOT THE PROGRAM. `sync_image_version.py`
# is legitimately declared twice on clean main -- `--check` and
# `--report-upstream --require-remote` are different questions, and a check
# keyed on the program name would ban a pair the repo deliberately has. Two
# declarations are redundant only when the SAME command runs in the SAME cwd:
# then the second can differ from the first in nothing but its label.
#
# The key also covers every declaration (74/74 on main), which a program-path
# key does not: 46 of 76 spell the program through `$PG/` or `$ROOT/` and are
# invisible to a `programs/...` path regex. There is no denominator hole to
# disclose here because there is no extraction to fail.


def _invocation(decl):
    """The identity of what bash will actually run: (cwd, normalised argv)."""
    cmd = " ".join(decl.cmd) if isinstance(decl.cmd, (list, tuple)) \
        else str(decl.cmd)
    return (str(decl.cwd_token), " ".join(cmd.split()))


def duplicate_invocations(declarations):
    """Invocations declared more than once -> the labels that declare them."""
    from collections import defaultdict
    by_key = defaultdict(list)
    for d in declarations:
        by_key[_invocation(d)].append(d.label)
    return {k: labels for k, labels in by_key.items() if len(labels) > 1}


def test_no_gate_is_declared_twice_with_the_same_invocation():
    """The real script must not run one command twice in one lane.

    A duplicate costs the landing its runtime twice over and, worse, makes the
    gate list lie about how many distinct questions are being asked. It is the
    one drift shape `git merge` cannot see, because the two lines need not be
    anywhere near each other.
    """
    decls = GD.parse_declarations(_SCRIPT)
    assert decls, "the parser found no gates in the real hygiene script"
    dups = duplicate_invocations(decls)
    assert not dups, (
        "the same command is declared more than once in the hygiene script — "
        "the second adds nothing but a label:\n" + "\n".join(
            f"  cwd={k[0]} cmd={k[1]}\n    labels: {labels}"
            for k, labels in sorted(dups.items())))


def test_NEGATIVE_CONTROL_the_same_program_with_different_arguments_is_not_a_duplicate():
    """Proof this is a check and not a ban.

    Keyed on the program alone, this clause would red on clean main today:
    `sync_image_version.py` is declared twice, and both are wanted. If this
    test ever fails, the key has been narrowed to the program name and a
    legitimate pair is about to be deleted to satisfy it.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _probe(root, "p_ok", "import sys\nprint('[PASS] fine')\nsys.exit(0)\n")
        script = _fixture_script(root, (
            f'run "asks one thing"  "$ROOT" python3 "{root}/p_ok.py" --check\n'
            f'run "asks another"    "$ROOT" python3 "{root}/p_ok.py" --report\n'))
        decls = GD.parse_declarations(script)

    assert len(decls) == 2, decls
    assert not duplicate_invocations(decls), (
        "two invocations of one program with DIFFERENT arguments were read as "
        "duplicates — this clause has become a ban on declaring a program "
        "twice, which clean main already violates on purpose")


def test_POSITIVE_CONTROL_two_run_lines_with_the_same_command_are_caught():
    """The clause must die on the shape #1256 actually produced.

    Same program, same cwd, same arguments, DIFFERENT labels — which is what a
    merge of two independently-correct branches yields, and what git reports
    as a clean merge.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _probe(root, "p_ok", "import sys\nprint('[PASS] fine')\nsys.exit(0)\n")
        # THE TEMPLATED LINE IS LOAD-BEARING, for the reason
        # `test_POSITIVE_CONTROL_a_literal_line_firing_twice_is_caught` records
        # above: `assert_invocations_decompose` checks the LOOP clause first, so
        # a fixture of literal `run` lines alone makes it raise on clause 1 and
        # proves nothing about the duplicate. With the loop present, the
        # existing machinery is genuinely satisfied and only the new clause
        # speaks. (I hit exactly that trap writing this control.)
        script = _fixture_script(root, (
            f'run "wired by the base"  "$ROOT" python3 "{root}/p_ok.py" progs\n'
            f'run "wired by the shard" "$ROOT" python3 "{root}/p_ok.py" progs\n'
            'while IFS= read -r _x; do\n'
            '  [ -n "$_x" ] || continue\n'
            f'  run "per cell ($(basename "$_x"))" "$ROOT" '
            f'python3 "{root}/p_ok.py"\n'
            'done < <(printf "alpha\\n")\n'))
        decls = GD.parse_declarations(script)
        doc = _list_record(script, root)
        recorded = [g["label"] for g in doc["gates"]]

    dups = duplicate_invocations(decls)
    assert len(dups) == 1, dups
    (labels,) = dups.values()
    assert sorted(labels) == ["wired by the base", "wired by the shard"]

    # EVERY CLAUSE ABOVE THIS ONE IS SATISFIED by the same script. The two
    # labels are distinct, so each declaration is explained and fires exactly
    # once, and the templated line decomposes. Pinned so nobody concludes the
    # existing reconciliation already covered the duplicate — it does not.
    assert firings(decls, recorded) == [1, 1, 1], firings(decls, recorded)
    unattributed, silent = reconcile(decls, recorded)
    assert not unattributed and not silent, (unattributed, silent)
    assert_invocations_decompose(decls, recorded)
