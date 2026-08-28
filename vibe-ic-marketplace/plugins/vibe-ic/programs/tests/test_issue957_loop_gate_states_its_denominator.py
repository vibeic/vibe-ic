"""vibe-ic#957 — a loop-driven gate must say how many items it expanded over.

THE MEASUREMENT
===============
`tools/ci/repo_hygiene_gates.sh` wires three gates PER PUBLISHED CELL, over the
corpus its own loop selects:

    $ git ls-files -- 'benchmark-data/ic/*/*/phase3/stage3/pnr/routed.def'
    <one path>

ONE cell. Three gates, one denominator, on every merge. None of the three gates
is wrong, and the `git ls-files` loop is itself the repair for a much worse
problem — a working-directory glob once took the declared gate count from 68 to
169 on a checkout carrying run leftovers. What was wrong is one level up: the
LABELS read like corpus coverage, the roll-up counted three green rows among
~74, and a reader took from it that post-route geometry is checked across the
published corpus. The number was true and the impression was false.

`gate_discloses_denominator_check` already demands of every gate INDIVIDUALLY
that a PASS say how much it looked at. The ROLL-UP is where that requirement
was missing, and this file is where it is now pinned.

WHAT THESE TESTS PIN, AND WHAT THEY DELIBERATELY DO NOT
=======================================================
NOTHING HERE TYPES THE CORPUS SIZE. The glob is read out of the gate script and
run, so the expected denominator is whatever the commit publishes: these tests
say the disclosure must be TRUE, not that it must be 1. If a tenth cell is
published tomorrow they follow it without an edit — a test carrying `1` would
be the next hand-maintained fact to drift, which is the defect this whole file
is about.

THEY DO NOT ASK FOR MORE CELLS. Whether more published cells should carry a
routed DEF is a publishing decision with a real repository-size cost and it is
not a side effect of making a roll-up honest. These tests would pass unchanged
over a corpus of one and over a corpus of nine.

PAIRED GUARDS. Three of the tests below must pass BEFORE and AFTER the change:
a gate wired outside a loop prints exactly what it printed before, its record
entry is unchanged, and the per-cell coverage neither grew nor shrank. Without
them the disclosure could be bought by moving output that was already right, or
by quietly dropping a gate.

WHEN THE PUBLISHED CORPUS IS NOT IN THIS CHECKOUT
=================================================
Everything above is measured over the loop's real subject — the PUBLISHED CELLS
the hygiene script's own `git ls-files` selects. Those cells now live in
https://github.com/vibeic/benchmark-data, so in this checkout that `ls-files`
returns nothing and the whole family of real-script tests is asking about data
that is not here. They are marked `@needs_corpus` and SKIP, naming the corpus;
with `VIBE_IC_BENCHMARK_DATA` pointing at a clone they run as before.

THE FAILURES WERE MEASURED, NOT ASSUMED, and all five come from the same
emptiness. Two say so directly (`assert items`, and `gates == templated x
items`). The other three are one step downstream: vibe-ic#1075 makes an empty
corpus record ONE SYNTHETIC gate in the NOT_CHECKED tier, and that synthetic
gate is `declared` but prints no `--list` row and is explained by no `run` line,
so the two PAIRED GUARDS below go red on the record's shape. Re-measured on a
fixture corpus of two items through the same `_gate_dispatch.sh`:

    rows printed   3       declared  3       gates recorded  3
    labels         ['a flat gate', 'per item (a)', 'per item (b)']
    corpora        [{'items': 2, 'gates': 2, 'expansion': 'EXPANDED'}]

— every one of them green. Nothing about the dispatcher or the reconciler is
broken; they are being asked about a corpus that is not in this tree.

The fifth, `test_every_published_cell_is_still_covered_by_every_per_cell_gate`,
was not red at all: over zero cells it compares 0 against 0 and PASSES. That is
worse than a red, and it is the reason it is marked too — a coverage guard that
reports "every published cell is covered" while looking at none of them is the
vacuous pass this whole file was written about, arriving through the
denominator.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import textwrap
from pathlib import Path

#: NOTE the module below is `_published_corpus.py`, the suite-wide answer to
#: "is the published corpus in this checkout?". The `_published_corpus()`
#: FUNCTION further down this file is a different thing — it asks the hygiene
#: script which items its own loop expands over. Importing a name out of the
#: module rather than the module itself keeps the two from shadowing.
from _published_corpus import needs_corpus

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_REPO = _PROGRAMS.parents[3]
_SCRIPT = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
_LIB = _REPO / "tools" / "ci" / "_gate_dispatch.sh"

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _load(base: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, base / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


#: The ONE parser of the hygiene script. Imported, never re-written: this repo
#: has already paid for a second copy of that regex living in a second file.
GD = _load(_PROGRAMS, "gate_discloses_denominator_check")
#: And the ONE reconciler of records against declarations, for the paired guard
#: that the denominator did not get glued into a gate's identity.
_538 = _load(_TESTS, "test_issue538_merge_gate_covers_ci_hygiene")


# ── what the script's corpus IS, discovered rather than declared ────────────
#: The producer the hygiene script itself hands to `gate_dispatch_over`.
_CORPUS_PRODUCER = _REPO / "tools" / "ci" / "routed_def_corpus.py"


def _published_corpus() -> list:
    """The items the gate script's own producer selects, run for real.

    ASKED OF THE SCRIPT'S OWN PRODUCER, which is the same reason the glob used
    to be scraped out of the script: this test must not be able to disagree
    with the script about what the corpus is, and must not go stale when the
    layout moves. 7c376e348 (v1.10.69) moved the population out of an inline
    `benchmark-data/...` glob and into `tools/ci/routed_def_corpus.py`, so
    there is no longer a glob in the script to scrape — the scrape found zero
    and this helper failed before any disclosure assertion could run. Running
    the producer keeps the original property instead of re-copying its glob
    here, which would be the second registry the scrape existed to avoid.
    """
    out = _pr.run(
        ["python3", str(_CORPUS_PRODUCER), "--repo", str(_REPO)],
        capture_output=True, text=True)
    # rc 2 is "I could not look", which this file never lets read as an empty
    # corpus; the caller's `@needs_corpus` mark is what covers the absent one.
    assert out.returncode == 0, out.stderr
    return [ln for ln in out.stdout.split() if ln]


def _templated_decls():
    """The `run` lines a LOOP drives: the parser says so, this file does not."""
    return [d for d in GD.parse_declarations(_SCRIPT) if d.runtime_expansion]


def _literal_decls():
    return [d for d in GD.parse_declarations(_SCRIPT) if not d.runtime_expansion]


def _literal_prefix(label: str) -> str:
    """A templated label up to its first expansion — `macro OBS … (`."""
    return label.split("$")[0]


def _list_run(script: Path, cwd: Path):
    """(stdout, stderr, record) for `--list`, which drives the REAL dispatch."""
    with tempfile.TemporaryDirectory() as td:
        rec = Path(td) / "record.json"
        out = _pr.run(
            ["bash", str(script), "--list", "--summary-json", str(rec)],
            cwd=str(cwd), capture_output=True, text=True)
        assert out.returncode == 0, out.stdout + out.stderr
        return out.stdout, out.stderr, json.loads(rec.read_text())


#: A row that states a denominator: "… of N …". Deliberately looser than the
#: exact sentence the dispatcher prints — the requirement is that the number is
#: THERE and correct, not that it is phrased one way.
_DENOM_RE = re.compile(r"\bof\s+(\d+)\b")


# ==========================================================================
# THE DISCLOSURE
# ==========================================================================
@needs_corpus
def test_every_loop_driven_row_states_how_many_items_the_loop_expanded_over():
    """The defect, over the REAL script.

    Three gates ran over one cell and every row read like a statement about
    "the published cells". A reader could not see the denominator anywhere,
    because it was written down nowhere.
    """
    items = _published_corpus()
    templated = _templated_decls()
    assert templated, "the script no longer drives any gate from a loop"
    assert items, (
        "the published corpus is empty, so this test cannot distinguish a "
        "disclosure from silence; it is not the fix's job to populate it")

    stdout, _, _ = _list_run(_SCRIPT, _REPO)
    rows = [ln for ln in stdout.splitlines() if ln.strip()]
    loop_rows = [ln for ln in rows
                 if any(ln.startswith(_literal_prefix(d.label))
                        for d in templated)]
    assert len(loop_rows) == len(templated) * len(items), (
        f"{len(loop_rows)} loop-driven row(s) for {len(templated)} looping "
        f"`run` line(s) over {len(items)} published item(s)")
    for ln in loop_rows:
        m = _DENOM_RE.search(ln)
        assert m, (
            "a loop-driven gate row states no denominator — a reader cannot "
            "tell whether this verdict covers the corpus or one item of it:\n"
            f"  {ln}")
        assert int(m.group(1)) == len(items), (
            f"the row claims a denominator of {m.group(1)} over a corpus of "
            f"{len(items)}:\n  {ln}")


@needs_corpus
def test_the_rollup_names_the_corpus_and_the_size_it_expanded_over():
    """The roll-up is what a reader believes, and it is where this was missing.

    Per-row disclosure is not enough on its own: the sentence that counts the
    gates is the one that reads as coverage.
    """
    items = _published_corpus()
    stdout, stderr, doc = _list_run(_SCRIPT, _REPO)

    corpora = doc.get("corpora")
    assert corpora, (
        "the machine record carries no corpus entry, so a consumer of the "
        "record — which is what the merge gate reads — still cannot tell how "
        "many items the loop-driven gates covered")
    assert len(corpora) == 1, corpora
    c = corpora[0]
    assert c["items"] == len(items), (c, items)
    assert c["gates"] == len(_templated_decls()) * len(items), c

    said = [ln for ln in (stdout + stderr).splitlines()
            if c["name"] in ln and re.search(rf"\b{len(items)}\b", ln)]
    assert said, (
        "no line of the roll-up names the corpus and how many items it "
        f"expanded over:\n{stderr}")


@needs_corpus
def test_the_declared_count_is_still_a_count_of_GATES_not_of_items():
    """PAIRED with the two above: the disclosure must not be bought by
    inflating `declared`, which is the number the merge gate reports coverage
    against.

    NEEDS THE CORPUS for a reason one step removed from the others: over an
    EMPTY one, #1075's synthetic NOT_CHECKED gate is `declared` and prints no
    `--list` row, so this reads 81 against 80 and reports a defect in the
    dispatcher that a two-item fixture corpus shows is not there (3 == 3).
    """
    _, _, doc = _list_run(_SCRIPT, _REPO)
    assert doc["declared"] == len(doc["gates"])
    assert doc["declared"] == sum(1 for ln in _list_run(_SCRIPT, _REPO)[0]
                                  .splitlines() if ln.strip())


# ==========================================================================
# ZERO — the case that leaves no gate behind to speak for itself
# ==========================================================================
def _fixture(root: Path, body: str) -> Path:
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    s = root / "tools" / "ci" / "gates.sh"
    s.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT="{root}"
        . "{_LIB}"
        gate_dispatch_init "$@"
        """) + body + "\ngate_dispatch_finish\n")
    return s


def _run_fixture(root: Path, body: str):
    rec = root / "rec.json"
    out = _pr.run(
        ["bash", str(_fixture(root, body)), "--summary-json", str(rec)],
        cwd=str(root), capture_output=True, text=True)
    doc = json.loads(rec.read_text()) if rec.is_file() else {}
    return out, doc


_OK = 'python3 -c "print(\'PASS (1 item(s) examined)\')"'


def test_a_loop_that_expands_over_NOTHING_is_still_reported(tmp_path):
    """A corpus of zero must leave a VERDICT behind, not just a sentence.

    UPDATED by vibe-ic#1075. This test's original assertion was
    `doc["declared"] == 1` — an empty corpus declared no gate at all — and its
    own docstring named that as the defect rather than the requirement:

        "...cannot be counted, cannot be NOT_CHECKED, and cannot fail. The gate
         set silently shrinks and every remaining sentence stays true — WHICH IS
         THE VACUOUS PASS THIS REPO REMOVES FROM GATES ONE AT A TIME, arriving
         through the denominator instead of through a state."

    #957 pinned that state so it was visible; #1075 removes it. An empty corpus
    now records one synthetic gate in `NOT_CHECKED` — the tier this library
    already defines as "the gate REFUSED — it could not look (rc 2)", which is
    exactly the condition of a gate with nothing to look at, and which the
    roll-up never folds into `passed`.

    NOTHING BELOW WAS RELAXED. Every disclosure assertion #957 made is kept
    verbatim; the count moves 1 -> 2 and one assertion is ADDED requiring the
    new record to actually be NOT_CHECKED, so the empty corpus cannot go back to
    being counted as a pass.
    """
    out, doc = _run_fixture(tmp_path, (
        f'run "a flat gate" "$ROOT" {_OK}\n'
        f'_body() {{ run "per item ($1)" "$ROOT" {_OK}; }}\n'
        'gate_dispatch_over "an empty corpus" _body printf ""\n'))
    text = out.stdout + out.stderr
    assert out.returncode == 0, text
    assert doc["declared"] == 2, (
        "the empty corpus left no gate behind — the flat gate is the only one "
        f"declared, which is the #957 defect #1075 removes:\n{doc}")
    assert doc.get("not_checked", 0) >= 1, (
        "the empty corpus was recorded, but not in the NOT_CHECKED tier, so it "
        f"can still be read as a pass over nothing:\n{doc}")
    assert doc["passed"] == 1, (
        "the synthetic empty-corpus gate must NOT be counted among the passes "
        f"— only the flat gate passed:\n{doc}")
    assert [c for c in doc.get("corpora", []) if c["items"] == 0], (
        "a loop that expanded over nothing left no trace in the record:\n"
        + json.dumps(doc, indent=1))
    assert "an empty corpus" in text and "0 item" in text, (
        "the run never said that a loop covered nothing:\n" + text)
    # #957 looked for a line starting `repo_hygiene_gates: all `, because an
    # empty corpus USED to leave every gate passing and the roll-up therefore
    # said "all N passed" — the sentence #957 required to carry a qualification.
    #
    # Under #1075 that sentence no longer exists, and its absence is the point:
    # the empty corpus records a NOT_CHECKED gate, so the run is no longer
    # "all", it is "1 of 2 gate(s) passed; 1 NOT CHECKED". The REQUIREMENT is
    # unchanged and is asserted here on the closing roll-up whatever its shape —
    # it must name the corpus and say nothing was checked over it.
    closing = [ln for ln in out.stdout.splitlines()
               if ln.startswith("repo_hygiene_gates: ")
               and ("gate(s) passed" in ln or ln.startswith(
                   "repo_hygiene_gates: all "))]
    assert closing, text
    assert "an empty corpus" in closing[-1] and "NOT a pass" in closing[-1], (
        "the closing sentence stands unqualified over a corpus that expanded "
        f"to nothing:\n  {closing[-1]}")
    assert "NOT CHECKED" in closing[-1], (
        "the closing sentence does not disclose that the empty corpus landed "
        f"in the NOT_CHECKED tier:\n  {closing[-1]}")


def test_a_producer_that_FAILED_is_not_reported_as_an_empty_corpus(tmp_path):
    """`git ls-files` in a non-repository prints nothing and exits non-zero.
    "I could not look" must not reach a reader as "there was nothing there" —
    the same distinction NOT_CHECKED draws one level down."""
    out, doc = _run_fixture(tmp_path, (
        f'run "a flat gate" "$ROOT" {_OK}\n'
        f'_body() {{ run "per item ($1)" "$ROOT" {_OK}; }}\n'
        'gate_dispatch_over "an unreadable corpus" _body '
        'git -C /nonexistent-corpus-root ls-files\n'))
    text = out.stdout + out.stderr
    assert out.returncode == 0, text
    assert [c for c in doc.get("corpora", [])
            if c.get("expansion") == "PRODUCER_FAILED"], json.dumps(doc)
    assert "PRODUCER FAILED" in text, text


def test_a_loop_written_AROUND_the_dispatcher_is_caught_and_named(tmp_path):
    """The disclosure comes from the dispatcher so that a future loop cannot be
    added without it. A hand-written `for` is the one way round that, so it is
    detected — one `run` line, many gates, no expansion open — and NAMED with
    its file and line rather than assumed absent."""
    out, doc = _run_fixture(tmp_path, (
        'for _i in one two three; do\n'
        f'  run "raw loop ($_i)" "$ROOT" {_OK}\n'
        'done\n'))
    text = out.stdout + out.stderr
    assert out.returncode == 0, text
    assert doc["declared"] == 3, doc
    assert doc.get("undisclosed_loops"), (
        "a loop wired around the dispatcher left the roll-up unable to state "
        "its denominator and said nothing about it:\n" + json.dumps(doc))
    assert "LOOP WITHOUT A DECLARED DENOMINATOR" in text, text
    assert "gates.sh:" in text, (
        "the undisclosed loop is not located — a reader cannot find the line "
        f"to fix:\n{text}")


# ==========================================================================
# PAIRED GUARDS — these must pass BEFORE the change as well as after
# ==========================================================================
def test_a_gate_wired_OUTSIDE_a_loop_prints_exactly_its_label():
    """THE INVISIBILITY REQUIREMENT. ~70 of the gates are not loop-driven and
    this change must not touch a byte of what they print."""
    literal = _literal_decls()
    assert len(literal) > 40, (
        "the population this guard protects has collapsed; it would now pass "
        f"over almost nothing ({len(literal)} literal declaration(s))")
    stdout, _, _ = _list_run(_SCRIPT, _REPO)
    rows = [ln for ln in stdout.splitlines() if ln.strip()]
    missing = [d.label for d in literal if d.label not in rows]
    assert not missing, (
        "a gate wired outside any loop no longer prints its label verbatim: "
        f"{missing[:5]}")


@needs_corpus
def test_the_record_still_carries_the_gate_LABEL_as_its_identity():
    """A denominator glued into the label would make every loop-driven record
    unattributable to the `run` line that produced it — two other programs
    parse this script and reconcile exactly that.

    NEEDS THE CORPUS for the same reason as its neighbour: over an empty one the
    only unattributable label is #1075's own synthetic
    `corpus "…" is EMPTY — nothing was checked over it`, which no `run` line
    explains because no `run` line produced it.
    """
    decls = GD.parse_declarations(_SCRIPT)
    _, _, doc = _list_run(_SCRIPT, _REPO)
    recorded = [g["label"] for g in doc["gates"]]
    unattributed, silent = _538.reconcile(decls, recorded)
    assert not unattributed, (
        "the dispatcher recorded gate(s) no `run` line explains — the label is "
        f"no longer the gate's identity: {sorted(set(unattributed))[:5]}")
    assert not silent, silent


@needs_corpus
def test_every_published_cell_is_still_covered_by_every_per_cell_gate():
    """The other half: a disclosure that was achieved by dropping a gate, or by
    narrowing the corpus, would be a coverage cut wearing a fix's clothes.

    THIS ONE WAS NOT RED. Over an empty corpus it compares `len(got)` to
    `len(items)` with both zero and reports a pass, so a guard whose whole
    subject is per-cell coverage was certifying coverage of nothing. It is
    marked for that reason, not for a failure: the skip says "I could not look",
    which is what was true, and the green said "every published cell is
    covered", which was not.
    """
    items = _published_corpus()
    stdout, _, _ = _list_run(_SCRIPT, _REPO)
    rows = [ln for ln in stdout.splitlines() if ln.strip()]
    for d in _templated_decls():
        pref = _literal_prefix(d.label)
        got = [ln for ln in rows if ln.startswith(pref)]
        assert len(got) == len(items), (
            f"`{pref}…` fired {len(got)} time(s) over {len(items)} published "
            "item(s)")
